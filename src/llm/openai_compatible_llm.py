"""OpenAI-compatible HTTP adapter used for configured language-model hosts."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from typing import Any

import requests
from requests import Response

from .base_llm import BaseLLM
from .errors import (
    LLMConnectionError,
    LLMGenerationLengthLimitError,
    LLMHealthCheckError,
    LLMModelCrashedError,
    LLMRequestError,
    LLMTokenCountError,
    LLMTokenCountUnsupportedError,
    preview_response_body,
    redact_sensitive_error,
    truncate_error,
)


def _abort_stream_response(response: Any) -> None:
    """Interrupt an active Requests socket read, then close the response."""
    if isinstance(response, Response):
        try:
            # urllib3 does not guarantee that Response.close() from another
            # thread wakes a blocked recv on every platform. This socket is
            # owned by this streamed response and is not reused afterward.
            sock = response.raw._fp.fp.raw._sock  # type: ignore[attr-defined]
            sock.shutdown(socket.SHUT_RDWR)
            # The generator-owning thread closes Requests/urllib3 state while
            # unwinding; cross-thread Response.close() can race that cleanup.
            return
        except (AttributeError, OSError):
            pass
    response.close()


class _AbortableStream(Iterator[str]):
    """Iterator whose cross-thread close aborts its active HTTP response."""

    def __init__(self, factory: Callable[[_AbortableStream], Generator[str]]):
        self._lock = threading.Lock()
        self._response: Any | None = None
        self._closed = False
        self._executing = False
        self._generator = factory(self)

    def __iter__(self) -> _AbortableStream:
        return self

    def __next__(self) -> str:
        with self._lock:
            if self._closed:
                raise StopIteration
            self._executing = True
        try:
            return next(self._generator)
        finally:
            with self._lock:
                self._executing = False

    def _set_response(self, response: Any) -> None:
        with self._lock:
            self._response = response
            close_now = self._closed
        if close_now:
            _abort_stream_response(response)

    def _clear_response(self, response: Any) -> None:
        with self._lock:
            if self._response is response:
                self._response = None

    def _is_closed(self) -> bool:
        with self._lock:
            return self._closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            response = self._response
            self._response = None
            can_close_generator = not self._executing
        if response is not None:
            _abort_stream_response(response)
        if can_close_generator:
            self._generator.close()


class OpenAICompatibleLLM(BaseLLM):
    """Language-model adapter for OpenAI-compatible APIs."""

    def __init__(
        self,
        *,
        model_name: str,
        host: str,
        api_key: str | None = None,
        timeout: int = 60,
        connect_timeout: int | None = None,
        stream_timeout: int | None = None,
        health_timeout: int | None = None,
        health_retries: int = 0,
        retries: int = 0,
        retry_delay: float = 2.0,
        enable_thinking: bool = False,
        request_started: Callable[[], None] | None = None,
        request_finished: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            host=host,
            api_key=api_key,
            timeout=timeout,
            retries=retries,
            retry_delay=retry_delay,
            **kwargs,
        )

        # Canonicalize base, ``/v1``, and chat-completions URLs to one base URL.
        clean = host.rstrip("/")
        if clean.endswith("/v1/chat/completions"):
            clean = clean[: -len("/v1/chat/completions")]
        elif clean.endswith("/v1"):
            clean = clean[: -len("/v1")]
        self.host = clean

        self.api_key = api_key or ""
        self.timeout = max(1, int(timeout))
        # Fail unreachable hosts before waiting for a full generation timeout.
        default_connect_timeout = min(self.timeout, 10)
        self.connect_timeout = max(
            1,
            int(connect_timeout if connect_timeout is not None else default_connect_timeout),
        )
        self.request_timeout = (self.connect_timeout, self.timeout)
        # External servers can legitimately remain silent while processing a
        # large prompt. ``None`` keeps connection establishment bounded without
        # imposing a product-level read or total-generation deadline.
        self.stream_timeout = (
            self.connect_timeout,
            None if stream_timeout is None else max(1, int(stream_timeout)),
        )
        default_health_timeout = min(self.connect_timeout, 5)
        health_timeout_value = (
            int(health_timeout) if health_timeout is not None else default_health_timeout
        )
        self.health_timeout = (max(1, health_timeout_value), max(1, health_timeout_value))
        self.health_retries = max(0, int(health_retries))
        self.enable_thinking = bool(enable_thinking)
        self._request_started = request_started
        self._request_finished = request_finished
        self.session = requests.Session()

    def set_request_activity_callbacks(
        self,
        request_started: Callable[[], None] | None,
        request_finished: Callable[[], None] | None,
    ) -> None:
        self._request_started = request_started
        self._request_finished = request_finished

    @contextmanager
    def _request_activity(self) -> Iterator[None]:
        if self._request_started is not None:
            try:
                self._request_started()
            except Exception:
                pass
        try:
            yield
        finally:
            if self._request_finished is not None:
                try:
                    self._request_finished()
                except Exception:
                    pass

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _is_retryable_stream_runtime_error(error: Exception) -> bool:
        """Return whether a stream-start error is safe to retry."""
        if isinstance(error, LLMModelCrashedError):
            return True
        if isinstance(error, LLMRequestError) and error.code in {
            "provider_timeout",
            "provider_unavailable",
            "provider_stream_incomplete",
        }:
            return True
        text = str(error).lower()
        transient_markers = (
            "model has crashed",
            "exit code",
            "temporarily unavailable",
            "connection reset",
            "internal server error",
            "status code: 500",
            "status code 500",
        )
        return any(marker in text for marker in transient_markers)

    @staticmethod
    def _stream_aborted(stream: _AbortableStream | None) -> bool:
        return stream is not None and stream._is_closed()

    def generate(
        self,
        prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            **kwargs,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        # ``temperature`` is only added when the caller asked for an
        # explicit numeric override.  ``None`` means "provider decides"
        # and is intentionally omitted from the JSON body so the
        # backend's own default takes over.
        if temperature is not None:
            payload["temperature"] = temperature
        if self.enable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": True}
        response = self._post("/v1/chat/completions", payload)
        if not response.ok:
            raise self._provider_http_error(response)
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise LLMRequestError(
                "provider_response_invalid",
                code="provider_response_invalid",
            ) from exc
        if not isinstance(content, str):
            raise LLMRequestError(
                "provider_response_invalid",
                code="provider_response_invalid",
            )
        return content

    @staticmethod
    def _usage_from_stream_event(data: Any) -> dict[str, int] | None:
        usage = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(usage, dict):
            return None
        values = {
            key: usage.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values.values()
        ):
            return None
        return values  # type: ignore[return-value]

    @staticmethod
    def _stream_options_unsupported(status: int, message: str) -> bool:
        lowered = message.lower()
        return status in {400, 422} and ("stream_options" in lowered or "include_usage" in lowered)

    def _safe_error_text(self, value: Any, *, limit: int = 500) -> str:
        return truncate_error(
            redact_sensitive_error(str(value), secrets=(self.api_key,)),
            limit=limit,
        )

    def _provider_error_detail(self, value: Any) -> str:
        """Extract one bounded detail string from common provider error shapes."""
        if isinstance(value, dict):
            for key in ("message", "detail", "error"):
                if key in value:
                    detail = self._provider_error_detail(value[key])
                    if detail:
                        return detail
            return self._safe_error_text(value, limit=200)
        if isinstance(value, str):
            return self._safe_error_text(value)
        if value is None:
            return ""
        return self._safe_error_text(value, limit=200)

    def _stream_error_message(self, response: Any) -> str:
        try:
            error_data = response.json()
            detail = self._provider_error_detail(error_data)
            return detail or self._safe_error_text(preview_response_body(response.text))
        except Exception:
            return self._safe_error_text(preview_response_body(response.text))

    @staticmethod
    def _provider_error_code(status: int, detail: str) -> str:
        lowered = detail.lower()
        if status in {401, 403} or any(
            marker in lowered
            for marker in ("invalid api key", "unauthorized", "authentication failed")
        ):
            return "provider_authentication_failed"
        if status == 402 or any(
            marker in lowered
            for marker in ("insufficient credit", "insufficient_quota", "billing required")
        ):
            return "provider_credit_required"
        if status == 429 or any(
            marker in lowered for marker in ("rate limit", "rate_limit", "too many requests")
        ):
            return "provider_rate_limited"
        if status in {408, 504} or "timed out" in lowered or "timeout" in lowered:
            return "provider_timeout"
        if any(
            marker in lowered
            for marker in (
                "model not found",
                "unknown model",
                "invalid model",
                "deployment not found",
                "unknown deployment",
                "preset not found",
                "unknown preset",
            )
        ) or (
            status in {400, 404, 422}
            and any(marker in lowered for marker in ("model", "deployment", "preset"))
        ):
            return "provider_model_rejected"
        if status >= 500 or any(
            marker in lowered
            for marker in ("temporarily unavailable", "internal server error", "overloaded")
        ):
            return "provider_unavailable"
        return "provider_request_failed"

    def _provider_http_error(self, response: Any) -> LLMRequestError:
        detail = self._stream_error_message(response) or "provider_request_failed"
        code = self._provider_error_code(response.status_code, detail)
        message = f"HTTP {response.status_code}: {detail}"
        if "model has crashed" in detail.lower():
            return LLMModelCrashedError(message)
        return LLMRequestError(message, code=code)

    def _stream_payload(
        self,
        prompt: str,
        temperature: float | None,
        max_tokens: int | None,
        system_prompt: str | None,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            **kwargs,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        if self.enable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": True}
        return payload

    @staticmethod
    def _decode_stream_line(line: str | bytes) -> Any | None:
        """Decode one SSE data field; ignore comments and metadata fields."""
        if isinstance(line, bytes):
            try:
                line = line.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise LLMRequestError(
                    "provider_response_invalid",
                    code="provider_response_invalid",
                ) from exc
        if not line or line.startswith(":") or not line.startswith("data:"):
            return None
        chunk = line[len("data:") :].lstrip()
        if chunk.strip() == "[DONE]":
            return "[DONE]"
        try:
            return json.loads(chunk)
        except (json.JSONDecodeError, TypeError) as exc:
            raise LLMRequestError(
                "provider_response_invalid",
                code="provider_response_invalid",
            ) from exc

    def _raise_stream_provider_error(self, data: Any) -> None:
        if not isinstance(data, dict) or "error" not in data:
            return
        error_msg = self._provider_error_detail(data["error"]) or "provider_request_failed"
        if "model has crashed" in error_msg.lower():
            raise LLMModelCrashedError(error_msg)
        classification_text = f"{error_msg} {data['error']}"
        raise LLMRequestError(
            error_msg,
            code=self._provider_error_code(0, classification_text),
        )

    @staticmethod
    def _stream_content_and_finish(data: Any) -> tuple[str | None, Any]:
        choices = data.get("choices") if isinstance(data, dict) else None
        choice = choices[0] if isinstance(choices, list) and choices else None
        if not isinstance(choice, dict):
            return None, None
        delta = choice.get("delta", {})
        content = delta.get("content") if isinstance(delta, dict) else None
        if content is not None and not isinstance(content, str):
            raise LLMRequestError(
                "provider_response_invalid",
                code="provider_response_invalid",
            )
        return content, choice.get("finish_reason")

    @staticmethod
    @contextmanager
    def _close_response_on_cancel(
        response: Any,
        cancel_event: threading.Event | None,
        stream_handle: _AbortableStream | None,
    ) -> Iterator[None]:
        """Close only this response when its owning generation is cancelled."""
        if cancel_event is None:
            yield
            return

        response_finished = threading.Event()

        def close_cancelled_response() -> None:
            while not response_finished.wait(0.05):
                if cancel_event.is_set():
                    try:
                        if stream_handle is not None:
                            stream_handle.close()
                        else:
                            _abort_stream_response(response)
                    except Exception:
                        pass
                    return

        watcher = threading.Thread(
            target=close_cancelled_response,
            name="aqa-llm-stream-cancellation",
            daemon=True,
        )
        watcher.start()
        try:
            yield
        finally:
            response_finished.set()
            watcher.join(timeout=0.2)

    def _iter_stream_response(
        self,
        response: Any,
        on_usage: Callable[[dict[str, int]], None] | None,
    ) -> Generator[str]:
        """Yield text deltas and raise for terminal provider errors."""

        response.encoding = "utf-8"
        length_reached = False
        terminal_event_seen = False
        for line in response.iter_lines(decode_unicode=True):
            data = self._decode_stream_line(line)
            if data is None:
                continue
            if data == "[DONE]":
                terminal_event_seen = True
                break
            self._raise_stream_provider_error(data)
            if not isinstance(data, dict):
                continue
            usage = self._usage_from_stream_event(data)
            if usage is not None and on_usage is not None:
                on_usage(usage)
            content, finish_reason = self._stream_content_and_finish(data)
            if content:
                yield content
            if finish_reason is not None:
                terminal_event_seen = True
            if finish_reason == "length":
                length_reached = True
        if length_reached:
            raise LLMGenerationLengthLimitError(
                "Die Generierung erreichte das Längen- oder Kontextlimit."
            )
        if not terminal_event_seen:
            raise LLMRequestError(
                "The provider stream ended before a terminal event.",
                code="provider_stream_incomplete",
            )

    def generate_stream(
        self,
        prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        on_usage: Callable[[dict[str, int]], None] | None = None,
        cancel_event: threading.Event | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        def run(stream: _AbortableStream) -> Generator[str]:
            with self._request_activity():
                yield from self._generate_stream(
                    prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                    on_usage=on_usage,
                    _stream_handle=stream,
                    cancel_event=cancel_event,
                    **kwargs,
                )

        return _AbortableStream(run)

    def _generate_stream(  # noqa: C901 - retry and partial-output states must stay coupled
        self,
        prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        on_usage: Callable[[dict[str, int]], None] | None = None,
        _stream_handle: _AbortableStream | None = None,
        cancel_event: threading.Event | None = None,
        **kwargs: Any,
    ) -> Generator[str]:
        payload = self._stream_payload(prompt, temperature, max_tokens, system_prompt, kwargs)

        import requests
        from loguru import logger

        last_error: Exception | None = None
        started_streaming = False
        fallback_without_usage = False
        attempt = 0

        # Retry only before text starts. A provider that rejects the optional
        # OpenAI usage extension gets one immediate provider-specific retry that
        # does not consume the normal retry budget.
        while attempt <= self.retries:
            if cancel_event is not None and cancel_event.is_set():
                return
            try:
                if attempt > 0:
                    wait_time = self.retry_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"LLM stream start failed. Retrying {attempt}/{self.retries} in {wait_time:.1f}s..."
                    )
                    if cancel_event is not None:
                        if cancel_event.wait(wait_time):
                            return
                    else:
                        time.sleep(wait_time)

                with self.session.post(
                    f"{self.host}/v1/chat/completions",
                    headers=self._headers(),
                    # Keep the request object immutable from the caller's
                    # perspective: the provider-specific retry removes only
                    # its own optional stream setting for the next attempt.
                    json={
                        **payload,
                        **(
                            {"stream_options": dict(payload["stream_options"])}
                            if isinstance(payload.get("stream_options"), dict)
                            else {}
                        ),
                    },
                    timeout=self.stream_timeout,
                    stream=True,
                    allow_redirects=False,
                ) as response:
                    if _stream_handle is not None:
                        _stream_handle._set_response(response)
                    try:
                        with self._close_response_on_cancel(response, cancel_event, _stream_handle):
                            if not response.ok:
                                error_msg = self._stream_error_message(response)
                                if (
                                    not started_streaming
                                    and not fallback_without_usage
                                    and self._stream_options_unsupported(
                                        response.status_code, error_msg
                                    )
                                ):
                                    payload.pop("stream_options", None)
                                    fallback_without_usage = True
                                    continue
                                raise self._provider_http_error(response)

                            for content in self._iter_stream_response(response, on_usage):
                                if cancel_event is not None and cancel_event.is_set():
                                    return
                                started_streaming = True
                                yield content
                            return
                    finally:
                        if _stream_handle is not None:
                            _stream_handle._clear_response(response)

            except LLMRequestError as e:
                if self._stream_aborted(_stream_handle) or (
                    cancel_event is not None and cancel_event.is_set()
                ):
                    return
                # Retry transient startup failures only before yielding content.
                if started_streaming:
                    raise
                if self._is_retryable_stream_runtime_error(e):
                    logger.warning(
                        f"LLM stream runtime error at start (attempt {attempt + 1}/{self.retries + 1})."
                    )
                    last_error = e
                    attempt += 1
                    continue
                raise
            except (
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.RequestException,
            ) as e:
                if self._stream_aborted(_stream_handle) or (
                    cancel_event is not None and cancel_event.is_set()
                ):
                    return
                # Retrying after a partial stream would duplicate the request.
                if started_streaming:
                    logger.error("LLM stream aborted during transfer.")
                    code = (
                        "provider_timeout"
                        if isinstance(e, requests.exceptions.Timeout)
                        else "provider_connection_failed"
                    )
                    raise LLMConnectionError(
                        self._safe_error_text(e) or code,
                        code=code,
                    ) from e

                logger.warning(
                    f"LLM stream error at start (attempt {attempt + 1}/{self.retries + 1})."
                )
                last_error = e
                attempt += 1
                continue

        if isinstance(last_error, LLMRequestError):
            raise last_error
        code = (
            "provider_timeout"
            if isinstance(last_error, requests.exceptions.Timeout)
            else "provider_connection_failed"
        )
        raise LLMConnectionError(
            self._safe_error_text(last_error) or code,
            code=code,
        ) from last_error

    def _count_tokens(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Call an optional OpenAI-compatible token-count endpoint once.

        These endpoints are a preflight diagnostic, not a generation.  They
        deliberately do not consume the generation retry budget.  A missing
        endpoint is distinguishable from a broken count request so managed
        Local AI can fail closed while custom hosts may continue normally.
        """
        try:
            response = self._post(path, payload, retries=0)
        except Exception as exc:
            raise LLMTokenCountError("Tokenzählung konnte nicht ausgeführt werden") from exc

        if response.status_code in {404, 405}:
            raise LLMTokenCountUnsupportedError(
                "Tokenzählung wird von diesem Host nicht unterstützt"
            )
        try:
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise LLMTokenCountError("Tokenzählung lieferte keine gültige Antwort") from exc
        if not isinstance(data, dict):
            raise LLMTokenCountError("Tokenzählung lieferte kein Objekt")
        return data

    def count_chat_input_tokens(
        self,
        messages: list[dict[str, Any]],
        *,
        model_name: str | None = None,
    ) -> int:
        """Return exact input tokens for the final chat messages and template."""
        payload: dict[str, Any] = {
            "model": model_name or self.model_name,
            "messages": messages,
        }
        if self.enable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": True}
        data = self._count_tokens("/v1/chat/completions/input_tokens", payload)
        token_count = data.get("input_tokens", data.get("tokens"))
        if isinstance(token_count, bool) or not isinstance(token_count, int) or token_count < 0:
            raise LLMTokenCountError("Tokenzählung enthielt keine gültige Eingabetokenzahl")
        return token_count

    def tokenize(self, content: str) -> int:
        """Return the exact count for plain content as reported by the host."""
        data = self._count_tokens("/tokenize", {"content": content})
        tokens = data.get("tokens")
        if not isinstance(tokens, list):
            raise LLMTokenCountError("Tokenisierung enthielt keine Tokenliste")
        return len(tokens)

    def get_model_info(self) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "host": self.host,
            "provider": "openai-compatible",
        }

    def health_check(self) -> bool:
        """Check whether the OpenAI-compatible endpoint is reachable."""

        try:
            # A health check is a short reachability probe, not model validation.
            # Reachability polling is not model work and must not postpone the
            # managed server's idle/sleep transition.
            response = self._get_without_activity(
                "/v1/models",
                timeout=self.health_timeout,
                retries=self.health_retries,
            )
            response.raise_for_status()
            # The endpoint may return an empty OpenAI-compatible ``data`` list.
            return True
        except Exception as exc:  # pragma: no cover - defensive
            raise LLMHealthCheckError("OpenAI-compatible host health check failed.") from exc

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        timeout: float | tuple[float, float] | None = None,
        retries: int | None = None,
    ) -> Response:
        with self._request_activity():
            return self._post_without_activity(path, payload, timeout, retries)

    def _post_without_activity(
        self,
        path: str,
        payload: dict[str, Any],
        timeout: float | tuple[float, float] | None = None,
        retries: int | None = None,
    ) -> Response:
        """Send a POST request with bounded retries."""
        import time

        import requests
        from loguru import logger

        url = f"{self.host}{path}"
        last_error = None
        effective_timeout = self.request_timeout if timeout is None else timeout
        effective_retries = self.retries if retries is None else max(0, int(retries))

        for attempt in range(effective_retries + 1):
            try:
                if attempt > 0:
                    wait_time = self.retry_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"LLM request failed. Retrying {attempt}/{effective_retries} in {wait_time:.1f}s..."
                    )
                    time.sleep(wait_time)

                resp = self.session.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=effective_timeout,
                    allow_redirects=False,
                )
                return resp

            except (
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.RequestException,
            ) as e:
                logger.warning(
                    f"LLM request error (attempt {attempt + 1}/{effective_retries + 1})."
                )
                last_error = e

        code = (
            "provider_timeout"
            if isinstance(last_error, requests.exceptions.Timeout)
            else "provider_connection_failed"
        )
        raise LLMConnectionError(
            self._safe_error_text(last_error) or code,
            code=code,
        ) from last_error

    def _get(
        self,
        path: str,
        timeout: float | tuple[float, float] | None = None,
        retries: int | None = None,
    ) -> Response:
        with self._request_activity():
            return self._get_without_activity(path, timeout, retries)

    def _get_without_activity(
        self,
        path: str,
        timeout: float | tuple[float, float] | None = None,
        retries: int | None = None,
    ) -> Response:
        """Send a GET request with bounded retries."""
        import time

        import requests
        from loguru import logger

        url = f"{self.host}{path}"
        last_error = None
        effective_timeout = self.request_timeout if timeout is None else timeout
        effective_retries = self.retries if retries is None else max(0, int(retries))

        for attempt in range(effective_retries + 1):
            try:
                if attempt > 0:
                    wait_time = self.retry_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"LLM request failed. Retrying {attempt}/{effective_retries} in {wait_time:.1f}s..."
                    )
                    time.sleep(wait_time)

                resp = self.session.get(
                    url,
                    headers=self._headers(),
                    timeout=effective_timeout,
                    allow_redirects=False,
                )
                return resp

            except (
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.RequestException,
            ) as e:
                logger.warning(
                    f"LLM request error (attempt {attempt + 1}/{effective_retries + 1})."
                )
                last_error = e

        code = (
            "provider_timeout"
            if isinstance(last_error, requests.exceptions.Timeout)
            else "provider_connection_failed"
        )
        raise LLMConnectionError(
            self._safe_error_text(last_error) or code,
            code=code,
        ) from last_error
