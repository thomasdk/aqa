"""Deterministic, loopback-only provider fault modes for product E2E tests."""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from tests.product_e2e_server import (
    EXPLICIT_OVERRIDE_MODEL_ID,
    MODEL_ID,
    PROVIDER_MODE_HEADER,
    SUSTAINED_STREAM_CHUNKS,
    _provider_state,
    _stream_events,
    provider,
)


def _client() -> TestClient:
    return TestClient(provider, raise_server_exceptions=False)


def _reset_provider_state() -> None:
    state = _provider_state()
    state.model_list_calls = 0
    state.delayed_started.clear()
    state.delayed_release.clear()


def test_provider_fault_modes_are_loopback_and_do_not_need_secrets() -> None:
    client = _client()
    for mode in ("normal", "empty_completion", "missing_usage", "malformed_usage", "tiny_context"):
        response = client.post(
            "/v1/chat/completions",
            headers={PROVIDER_MODE_HEADER: mode},
            json={"model": MODEL_ID, "messages": [{"role": "user", "content": "fixture"}]},
        )
        assert response.status_code == 200
        assert response.request.url.host == "testserver"
        assert "api_key" not in response.text.lower()


def test_provider_matrix_modes_have_distinct_failure_and_payload_contracts() -> None:
    client = _client()
    failed = client.post(
        "/v1/chat/completions",
        headers={PROVIDER_MODE_HEADER: "fail_before_output"},
        json={},
    )
    assert failed.status_code == 503
    assert failed.json()["error"] == {
        "message": "deterministic provider failure before output",
        "type": "server_error",
    }

    partial = client.post(
        "/v1/chat/completions",
        headers={PROVIDER_MODE_HEADER: "fail_after_partial_output"},
        json={},
    )
    assert partial.status_code == 200
    assert b"Deterministic " in partial.content
    assert (
        b'"error":{"message":"deterministic provider failure after partial output"'
        in partial.content
    )
    assert b"[DONE]" not in partial.content

    empty = client.post(
        "/v1/chat/completions",
        headers={PROVIDER_MODE_HEADER: "empty_completion"},
        json={},
    )
    assert b'"completion_tokens":0' in empty.content

    missing = client.post(
        "/v1/chat/completions",
        headers={PROVIDER_MODE_HEADER: "missing_usage"},
        json={},
    )
    assert b'"usage"' not in missing.content

    malformed = client.post(
        "/v1/chat/completions",
        headers={PROVIDER_MODE_HEADER: "malformed_usage"},
        json={},
    )
    assert b'"prompt_tokens":"bad"' in malformed.content


def test_provider_delayed_writes_use_an_explicit_event_barrier() -> None:
    _reset_provider_state()
    state = _provider_state()
    client = _client()
    result: dict[str, object] = {}

    def request() -> None:
        result["response"] = client.post(
            "/v1/chat/completions",
            headers={PROVIDER_MODE_HEADER: "delayed_writes"},
            json={},
        )

    thread = threading.Thread(target=request)
    thread.start()
    assert state.delayed_started.wait(timeout=2)
    assert thread.is_alive()
    state.delayed_release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    response = result["response"]
    assert isinstance(response, type(client.get("/v1/models")))
    assert response.status_code == 200
    assert b"analysis." in response.content


def test_sustained_generation_emits_a_deterministic_markdown_load(monkeypatch) -> None:
    delays: list[float] = []
    monkeypatch.setattr("tests.product_e2e_server.time.sleep", delays.append)

    events = list(_stream_events("sustained_generation", slow=False))

    chunks = [event for event in events if "Evidence " in event]
    assert len(chunks) == SUSTAINED_STREAM_CHUNKS
    assert len(delays) == SUSTAINED_STREAM_CHUNKS
    assert chunks[0].startswith('data: {"choices": [{"delta": {"content": "\\n- Evidence 1:')
    assert f"Evidence {SUSTAINED_STREAM_CHUNKS}:" in chunks[-1]
    assert events[-1] == "data: [DONE]\n\n"


def test_provider_model_list_and_auth_modes_are_deterministic() -> None:
    _reset_provider_state()
    client = _client()
    first = client.get("/v1/models", headers={PROVIDER_MODE_HEADER: "changing_model_list"})
    second = client.get("/v1/models", headers={PROVIDER_MODE_HEADER: "changing_model_list"})
    assert first.json()["data"][0]["id"] == MODEL_ID
    assert first.json()["data"][1]["id"] == EXPLICIT_OVERRIDE_MODEL_ID
    assert second.json()["data"][0]["id"] == f"{MODEL_ID}-changed"

    tiny = client.get("/v1/models", headers={PROVIDER_MODE_HEADER: "tiny_context"})
    assert tiny.json()["data"][0]["context_length"] == 16

    auth = client.get("/v1/models", headers={PROVIDER_MODE_HEADER: "auth_failure"})
    assert auth.status_code == 401
    assert "secret" not in auth.text.lower()


def test_missing_token_count_endpoint_is_explicitly_unsupported() -> None:
    response = _client().post("/v1/chat/completions/input_tokens", json={})
    assert response.status_code == 404
