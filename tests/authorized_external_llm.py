"""Secret-safe configuration and budget controls for an authorized live host."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from src.service.token_estimator import estimate_tokens

AUTHORIZED_FIELDS = frozenset({"endpoint_url", "api_key", "model"})


class AuthorizedExternalConfigurationError(ValueError):
    """Raised with a fixed safe code when live-test authorization is invalid."""


class AuthorizedExternalBudgetError(RuntimeError):
    """Raised before traffic when a cumulative live-test limit would be exceeded."""


@dataclass(frozen=True)
class AuthorizedExternalConfig:
    endpoint_url: str
    api_key: str = field(repr=False)
    model: str

    @property
    def api_base(self) -> str:
        clean = self.endpoint_url.rstrip("/")
        if clean.endswith("/v1/chat/completions"):
            return clean[: -len("/v1/chat/completions")]
        if clean.endswith("/v1"):
            return clean[: -len("/v1")]
        return clean


def load_authorized_external_config(
    path: Path | None = None,
) -> AuthorizedExternalConfig:
    """Load an explicit path or AQA_AUTHORIZED_EXTERNAL_CONFIG with secret-safe errors."""
    if path is None:
        configured = os.getenv("AQA_AUTHORIZED_EXTERNAL_CONFIG", "").strip()
        if not configured:
            raise AuthorizedExternalConfigurationError("authorized_config_unavailable")
        path = Path(configured)
    try:
        if not path.is_file():
            raise AuthorizedExternalConfigurationError("authorized_config_unavailable")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except AuthorizedExternalConfigurationError:
        raise
    except Exception:
        raise AuthorizedExternalConfigurationError("authorized_config_invalid") from None

    if not isinstance(payload, dict) or set(payload) != AUTHORIZED_FIELDS:
        raise AuthorizedExternalConfigurationError("authorized_config_fields_invalid")
    values = {key: payload.get(key) for key in AUTHORIZED_FIELDS}
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise AuthorizedExternalConfigurationError("authorized_config_values_invalid")

    endpoint = values["endpoint_url"].strip()
    parsed = urlparse(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise AuthorizedExternalConfigurationError("authorized_endpoint_invalid")
    return AuthorizedExternalConfig(
        endpoint_url=endpoint,
        api_key=values["api_key"].strip(),
        model=values["model"].strip(),
    )


class RemoteBudget:
    """Persist cumulative live-request counts without storing provider data."""

    def __init__(self, path: Path):
        self.path = path
        self._mutex = threading.Lock()

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            raise AuthorizedExternalBudgetError("remote_budget_unavailable") from None
        if not isinstance(value, dict) or not isinstance(value.get("limits"), dict):
            raise AuthorizedExternalBudgetError("remote_budget_invalid")
        return value

    @contextmanager
    def lease(
        self,
        *,
        completion: bool,
        input_tokens: int = 0,
        input_bytes: int = 0,
        output_tokens: int | None = None,
    ) -> Iterator[float]:
        if not self._mutex.acquire(blocking=False):
            raise AuthorizedExternalBudgetError("remote_concurrency_limit_exceeded")
        lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        lock_fd: int | None = None
        try:
            try:
                lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                raise AuthorizedExternalBudgetError("remote_concurrency_limit_exceeded") from None
            state = self._read()
            now = datetime.now(UTC)
            limits = state["limits"]
            input_limit = int(limits["input_tokens_per_completion"])
            if completion and (input_tokens > input_limit or input_bytes > input_limit):
                raise AuthorizedExternalBudgetError("completion_input_limit_exceeded")
            output_limit = limits.get("output_tokens_per_completion")
            if (
                completion
                and output_tokens is not None
                and (
                    isinstance(output_tokens, bool)
                    or not isinstance(output_tokens, int)
                    or output_tokens <= 0
                    or (output_limit is not None and output_tokens > int(output_limit))
                )
            ):
                raise AuthorizedExternalBudgetError("completion_output_limit_invalid")
            if completion and output_tokens is None and output_limit is not None:
                raise AuthorizedExternalBudgetError("completion_output_limit_missing")

            window_raw = state.get("current_window_started_at")
            if window_raw:
                try:
                    window_start = datetime.fromisoformat(window_raw)
                except (TypeError, ValueError):
                    raise AuthorizedExternalBudgetError("remote_budget_invalid") from None
            else:
                window_start = now
            remaining_seconds = (
                window_start + timedelta(minutes=int(limits["elapsed_minutes"])) - now
            ).total_seconds()
            if remaining_seconds <= 0:
                raise AuthorizedExternalBudgetError("remote_elapsed_limit_exceeded")
            if int(state.get("requests_used", 0)) >= int(limits["requests"]):
                raise AuthorizedExternalBudgetError("remote_request_limit_exceeded")
            if completion and int(state.get("completion_requests_used", 0)) >= int(
                limits["completion_requests"]
            ):
                raise AuthorizedExternalBudgetError("remote_completion_limit_exceeded")

            state["requests_used"] = int(state.get("requests_used", 0)) + 1
            if completion:
                state["completion_requests_used"] = (
                    int(state.get("completion_requests_used", 0)) + 1
                )
            timestamp = now.isoformat()
            state["first_request_at"] = state.get("first_request_at") or timestamp
            state["current_window_started_at"] = window_raw or timestamp
            state["last_request_at"] = timestamp
            temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
            temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(self.path)
            yield time.monotonic() + remaining_seconds
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
                lock_path.unlink(missing_ok=True)
            self._mutex.release()

    def reserve(
        self,
        *,
        completion: bool,
        input_tokens: int = 0,
        input_bytes: int = 0,
        output_tokens: int | None = None,
    ) -> None:
        """Reserve one request without performing network traffic."""
        with self.lease(
            completion=completion,
            input_tokens=input_tokens,
            input_bytes=input_bytes,
            output_tokens=output_tokens,
        ):
            pass


def load_authorized_external_budget(path: Path | None = None) -> RemoteBudget:
    """Use caller-owned cumulative state from an explicit path or environment input."""
    if path is None:
        configured = os.getenv("AQA_AUTHORIZED_EXTERNAL_BUDGET", "").strip()
        if not configured:
            raise AuthorizedExternalBudgetError("remote_budget_unavailable")
        path = Path(configured)
    return RemoteBudget(path)


class _LeasedResponse:
    """Keep a remote-budget lease until a streamed response is closed."""

    def __init__(self, response: requests.Response, release: Any, deadline: float):
        object.__setattr__(self, "_response", response)
        object.__setattr__(self, "_release", release)
        object.__setattr__(self, "_released", False)
        object.__setattr__(self, "_deadline", deadline)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._response, name, value)

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            if not self._released:
                object.__setattr__(self, "_released", True)
                self._release(None, None, None)

    def __enter__(self) -> _LeasedResponse:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def iter_lines(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        """Stop an active stream when its authorization window expires."""
        iterator = iter(self._response.iter_lines(*args, **kwargs))
        while True:
            if time.monotonic() >= self._deadline:
                self.close()
                raise requests.Timeout("authorized_remote_window_elapsed")
            try:
                line = next(iterator)
            except StopIteration:
                return
            if time.monotonic() >= self._deadline:
                self.close()
                raise requests.Timeout("authorized_remote_window_elapsed")
            yield line


class BudgetedSession(requests.Session):
    """Restrict requests to one authorized origin and reserve budget before sending."""

    def __init__(self, config: AuthorizedExternalConfig, budget: RemoteBudget):
        super().__init__()
        self._config = config
        self._budget = budget
        authorized = urlparse(config.api_base)
        self._authorized_origin = (authorized.scheme, authorized.netloc)

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if (parsed.scheme, parsed.netloc) != self._authorized_origin:
            raise AuthorizedExternalConfigurationError("unauthorized_remote_origin")

    def _lease(self, method: str, url: str, kwargs: dict[str, Any]) -> Any:
        self._validate_url(url)
        payload = kwargs.get("json")
        completion = method == "POST" and urlparse(url).path.rstrip("/").endswith(
            "/chat/completions"
        )
        input_tokens = 0
        input_bytes = 0
        output_tokens: int | None = None
        if completion:
            if not isinstance(payload, dict):
                raise AuthorizedExternalBudgetError("completion_payload_invalid")
            messages = payload.get("messages")
            serialized_messages = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
            input_bytes = len(serialized_messages.encode("utf-8"))
            # Allow for a provider-specific tokenizer, chat framing, and
            # bookkeeping without making another remote request.
            estimated_tokens = estimate_tokens(serialized_messages)
            input_tokens = (estimated_tokens * 5 + 3) // 4 + 256
            raw_output = payload.get("max_tokens")
            if raw_output is not None:
                if isinstance(raw_output, bool) or not isinstance(raw_output, int):
                    raise AuthorizedExternalBudgetError("completion_output_limit_invalid")
                output_tokens = raw_output
        if kwargs.get("allow_redirects") is not False:
            raise AuthorizedExternalConfigurationError("remote_redirect_policy_invalid")
        return self._budget.lease(
            completion=completion,
            input_tokens=input_tokens,
            input_bytes=input_bytes,
            output_tokens=output_tokens,
        )

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        lease = self._lease(method.upper(), url, kwargs)
        deadline = lease.__enter__()
        remaining_seconds = max(0.001, deadline - time.monotonic())
        timeout = kwargs.get("timeout")
        if isinstance(timeout, tuple):
            kwargs["timeout"] = tuple(min(float(value), remaining_seconds) for value in timeout)
        elif isinstance(timeout, (int, float)):
            kwargs["timeout"] = min(float(timeout), remaining_seconds)
        else:
            kwargs["timeout"] = remaining_seconds
        try:
            response = super().request(method, url, **kwargs)
        except requests.RequestException:
            lease.__exit__(None, None, None)
            raise requests.ConnectionError("authorized_test_host_request_failed") from None
        except Exception:
            lease.__exit__(None, None, None)
            raise
        if time.monotonic() >= deadline:
            response.close()
            lease.__exit__(None, None, None)
            raise requests.Timeout("authorized_remote_window_elapsed")
        if kwargs.get("stream"):
            return _LeasedResponse(  # type: ignore[return-value]
                response,
                lease.__exit__,
                deadline,
            )
        lease.__exit__(None, None, None)
        return response
