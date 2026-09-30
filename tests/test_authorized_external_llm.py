"""Deterministic tests for the secret-safe authorized live-host controls."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
import requests

from tests.authorized_external_llm import (
    AuthorizedExternalBudgetError,
    AuthorizedExternalConfigurationError,
    BudgetedSession,
    RemoteBudget,
    _LeasedResponse,
    load_authorized_external_budget,
    load_authorized_external_config,
)


def _write_config(path: Path, **overrides: object) -> None:
    payload = {
        "endpoint_url": "https://provider.example/v1",
        "api_key": "test-only-secret",
        "model": "test-model",
        **overrides,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_budget(
    path: Path,
    *,
    requests_used: int = 0,
    completions_used: int = 0,
    output_limit: int | None = 256,
) -> None:
    path.write_text(
        json.dumps(
            {
                "requests_used": requests_used,
                "completion_requests_used": completions_used,
                "first_request_at": None,
                "current_window_started_at": None,
                "last_request_at": None,
                "limits": {
                    "requests": 120,
                    "completion_requests": 40,
                    "elapsed_minutes": 45,
                    "input_tokens_per_completion": 4096,
                    "output_tokens_per_completion": output_limit,
                },
            }
        ),
        encoding="utf-8",
    )


def test_config_requires_exact_nonempty_fields_and_safe_endpoint(tmp_path: Path) -> None:
    config_path = tmp_path / "authorized.json"
    _write_config(config_path)
    config = load_authorized_external_config(config_path)
    assert config.api_base == "https://provider.example"
    assert config.model == "test-model"

    _write_config(config_path, extra="not-authorized")
    with pytest.raises(AuthorizedExternalConfigurationError, match="fields_invalid"):
        load_authorized_external_config(config_path)

    _write_config(config_path, endpoint_url="https://name:secret@provider.example/v1")
    with pytest.raises(AuthorizedExternalConfigurationError, match="endpoint_invalid"):
        load_authorized_external_config(config_path)


def test_config_requires_an_explicit_path_or_environment_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AQA_AUTHORIZED_EXTERNAL_CONFIG", raising=False)
    with pytest.raises(AuthorizedExternalConfigurationError, match="config_unavailable"):
        load_authorized_external_config()

    config_path = tmp_path / "authorized.json"
    _write_config(config_path)
    monkeypatch.setenv("AQA_AUTHORIZED_EXTERNAL_CONFIG", str(config_path))
    assert load_authorized_external_config().model == "test-model"

    explicit_path = tmp_path / "explicit.json"
    _write_config(explicit_path, model="explicit-model")
    assert load_authorized_external_config(explicit_path).model == "explicit-model"


def test_neutral_budget_template_preserves_cumulative_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AQA_AUTHORIZED_EXTERNAL_BUDGET", raising=False)
    with pytest.raises(AuthorizedExternalBudgetError, match="budget_unavailable"):
        load_authorized_external_budget()

    template = Path(__file__).parent / "fixtures" / "authorized_external_budget.json"
    pristine = template.read_text(encoding="utf-8")
    assert set(json.loads(pristine)) == {"schema_version", "limits"}
    budget_path = tmp_path / "budget.json"
    budget_path.write_text(pristine, encoding="utf-8")
    monkeypatch.setenv("AQA_AUTHORIZED_EXTERNAL_BUDGET", str(budget_path))
    load_authorized_external_budget().reserve(completion=True, input_tokens=100)
    load_authorized_external_budget().reserve(completion=True, input_tokens=100)

    state = json.loads(budget_path.read_text(encoding="utf-8"))
    assert state["requests_used"] == 2
    assert state["completion_requests_used"] == 2
    assert state["current_window_started_at"] == state["first_request_at"]
    assert template.read_text(encoding="utf-8") == pristine

    explicit_path = tmp_path / "explicit-budget.json"
    explicit_path.write_text(pristine, encoding="utf-8")
    load_authorized_external_budget(explicit_path).reserve(completion=False)
    assert json.loads(explicit_path.read_text(encoding="utf-8"))["requests_used"] == 1
    assert json.loads(budget_path.read_text(encoding="utf-8"))["requests_used"] == 2


def test_budget_reserves_before_traffic_and_never_stores_payload(tmp_path: Path) -> None:
    budget_path = tmp_path / "budget.json"
    _write_budget(budget_path)
    budget = RemoteBudget(budget_path)

    budget.reserve(completion=True, input_tokens=100, output_tokens=64)

    state = json.loads(budget_path.read_text(encoding="utf-8"))
    assert state["requests_used"] == 1
    assert state["completion_requests_used"] == 1
    assert "payload" not in state


@pytest.mark.parametrize(
    ("input_tokens", "output_tokens", "code"),
    [
        (4097, 64, "input_limit"),
        (100, 0, "output_limit"),
        (100, 257, "output_limit"),
    ],
)
def test_budget_rejects_completion_bounds_before_counting(
    tmp_path: Path, input_tokens: int, output_tokens: int, code: str
) -> None:
    budget_path = tmp_path / "budget.json"
    _write_budget(budget_path)
    with pytest.raises(AuthorizedExternalBudgetError, match=code):
        RemoteBudget(budget_path).reserve(
            completion=True,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    assert json.loads(budget_path.read_text(encoding="utf-8"))["requests_used"] == 0


def test_budget_accepts_omitted_output_limit_only_when_authorized(tmp_path: Path) -> None:
    budget_path = tmp_path / "budget.json"
    _write_budget(budget_path)
    with pytest.raises(AuthorizedExternalBudgetError, match="output_limit_missing"):
        RemoteBudget(budget_path).reserve(completion=True, input_tokens=100)

    _write_budget(budget_path, output_limit=None)
    RemoteBudget(budget_path).reserve(completion=True, input_tokens=100)
    assert json.loads(budget_path.read_text(encoding="utf-8"))["requests_used"] == 1


def test_session_rejects_other_origins_redirects_and_unbounded_completions(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "authorized.json"
    budget_path = tmp_path / "budget.json"
    _write_config(config_path)
    _write_budget(budget_path)
    session = BudgetedSession(
        load_authorized_external_config(config_path),
        RemoteBudget(budget_path),
    )

    with pytest.raises(AuthorizedExternalConfigurationError, match="origin"):
        session._lease("GET", "https://other.example/v1/models", {"allow_redirects": False})
    with pytest.raises(AuthorizedExternalConfigurationError, match="redirect"):
        session._lease("GET", "https://provider.example/v1/models", {})
    with (
        pytest.raises(AuthorizedExternalBudgetError, match="output_limit_missing"),
        session._lease(
            "POST",
            "https://provider.example/v1/chat/completions",
            {
                "allow_redirects": False,
                "json": {"messages": [{"role": "user", "content": "hello"}]},
            },
        ),
    ):
        pass


def test_session_allows_unbounded_completion_only_with_unlimited_budget(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "authorized.json"
    budget_path = tmp_path / "budget.json"
    _write_config(config_path)
    _write_budget(budget_path, output_limit=None)
    session = BudgetedSession(
        load_authorized_external_config(config_path),
        RemoteBudget(budget_path),
    )

    with session._lease(
        "POST",
        "https://provider.example/v1/chat/completions",
        {
            "allow_redirects": False,
            "json": {"messages": [{"role": "user", "content": "hello"}]},
        },
    ):
        pass

    assert json.loads(budget_path.read_text(encoding="utf-8"))["requests_used"] == 1


def test_session_keeps_original_conservative_input_byte_ceiling(tmp_path: Path) -> None:
    config_path = tmp_path / "authorized.json"
    budget_path = tmp_path / "budget.json"
    _write_config(config_path)
    _write_budget(budget_path, output_limit=None)
    session = BudgetedSession(
        load_authorized_external_config(config_path),
        RemoteBudget(budget_path),
    )

    with (
        pytest.raises(AuthorizedExternalBudgetError, match="input_limit"),
        session._lease(
            "POST",
            "https://provider.example/v1/chat/completions",
            {
                "allow_redirects": False,
                "json": {"messages": [{"role": "user", "content": "a" * 10_000}]},
            },
        ),
    ):
        pass
    assert json.loads(budget_path.read_text(encoding="utf-8"))["requests_used"] == 0


def test_stream_deadline_closes_response_and_releases_lease() -> None:
    class FakeResponse:
        def __init__(self) -> None:
            self.closed = False

        def iter_lines(self, *args: object, **kwargs: object):
            yield b"data: {}"

        def close(self) -> None:
            self.closed = True

    released: list[object] = []
    response = FakeResponse()
    leased = _LeasedResponse(
        response,  # type: ignore[arg-type]
        lambda *args: released.append(object()),
        time.monotonic() - 1,
    )

    with pytest.raises(requests.Timeout, match="window_elapsed"):
        next(leased.iter_lines())
    assert response.closed is True
    assert len(released) == 1


def test_session_holds_concurrency_lease_for_the_network_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "authorized.json"
    budget_path = tmp_path / "budget.json"
    _write_config(config_path)
    _write_budget(budget_path)
    session = BudgetedSession(
        load_authorized_external_config(config_path),
        RemoteBudget(budget_path),
    )
    entered = threading.Event()
    release = threading.Event()
    first_done = threading.Event()

    def blocked_request(*args: object, **kwargs: object) -> object:
        entered.set()
        assert release.wait(timeout=5)
        return object()

    monkeypatch.setattr("requests.Session.request", blocked_request)

    def first_request() -> None:
        session.get("https://provider.example/v1/models", allow_redirects=False)
        first_done.set()

    worker = threading.Thread(target=first_request)
    worker.start()
    assert entered.wait(timeout=5)
    with pytest.raises(AuthorizedExternalBudgetError, match="concurrency"):
        session.get("https://provider.example/v1/models", allow_redirects=False)
    release.set()
    worker.join(timeout=5)
    assert first_done.is_set()
    assert json.loads(budget_path.read_text(encoding="utf-8"))["requests_used"] == 1
