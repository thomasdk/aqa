"""Tests for src/service/api.py — Discussion API endpoints.

Tests the discussion-related FastAPI endpoints using a mocked AppContext
so no real LLM or storage is needed.
"""

import asyncio
import hashlib
import json
import queue
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api_server import app
from src.config.settings import LOCAL_AI_HOST_LABEL, _local_ai_host
from src.local_ai.manager import LocalAIStateError, LocalAIStatus
from src.prompts.session_types import default_session_inputs
from src.service.api_schemas import AgentConfigModel
from src.service.discussion import (
    AgentResponse,
    DiscussionMessage,
    DiscussionState,
    ProviderRebindRequiredError,
    ProviderRebindTargetChangedError,
    SynthesisResponse,
)
from src.service.discussion_storage import SessionDeletionRollbackError
from src.service.routers.discussions import (
    _managed_local_ai_preflight,
    _managed_request_owner,
    _stream_callbacks,
    _stream_response,
)
from src.service.token_estimator import TOKENIZER_NAME, estimate_tokens
from tests.router_test_support import override_context


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.discussion = MagicMock()
    ctx.discussion.synthesis_config = None
    ctx.discussion.resolve_continuation_configuration.side_effect = lambda agents, **_kwargs: (
        deepcopy(agents),
        None,
    )
    ctx.settings = MagicMock()
    ctx.llm_manager = MagicMock()
    return ctx


def _sse_events(content: str) -> list[dict]:
    """Parse SSE ``data:`` events from a raw response body."""
    events: list[dict] = []
    for part in content.split("\n\n"):
        for line in part.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def test_failed_structured_synthesis_emits_error_event_without_raw_error():
    event_queue: queue.Queue[dict] = queue.Queue()
    callbacks = _stream_callbacks(event_queue, threading.Event())

    callbacks["on_synthesis_complete"](
        SynthesisResponse(
            message_id="synthesis-1",
            text="",
            round_number=1,
            is_complete=False,
            status="failed",
            error_code="synthesis_no_usable_contributions",
        )
    )

    assert event_queue.get_nowait() == {
        "type": "synthesis_error",
        "message_id": "synthesis-1",
        "round_number": 1,
        "message": "",
        "text": "",
        "status": "failed",
        "error_code": "synthesis_no_usable_contributions",
        "error_params": {},
    }


def test_managed_preflight_includes_enabled_synthesis_configuration():
    context = SimpleNamespace(
        settings=SimpleNamespace(
            known_llm_hosts={
                "Integrated AI": {
                    "kind": "local_ai",
                    "url": "http://127.0.0.1:11435",
                    "model": "gemma-4-E2B-it",
                }
            }
        )
    )
    manager = MagicMock()
    manager.inventory.return_value = [{"model_id": "gemma-4-e2b", "installed": True}]
    manager.status.return_value = LocalAIStatus(
        state="running",
        model_id="gemma-4-e2b",
    )
    synthesis = SimpleNamespace(
        enabled=True,
        api_host="http://127.0.0.1:11435",
        llm_id="gemma-4-E2B-it",
    )

    assert _managed_local_ai_preflight(context, [synthesis], manager) == "gemma-4-e2b"


def test_managed_preflight_rejects_continuation_synthesis_model_mismatch():
    context = SimpleNamespace(
        settings=SimpleNamespace(
            known_llm_hosts={
                "Integrated AI": {
                    "kind": "local_ai",
                    "url": "http://127.0.0.1:11435",
                    "model": "gemma-4-E2B-it",
                }
            }
        )
    )
    manager = MagicMock()
    manager.inventory.return_value = [
        {"model_id": "gemma-4-e2b", "installed": True},
        {"model_id": "gemma-4-e4b", "installed": True},
    ]
    manager.status.return_value = LocalAIStatus(
        state="running",
        model_id="gemma-4-e4b",
    )
    synthesis = SimpleNamespace(
        enabled=True,
        api_host="http://127.0.0.1:11435",
        llm_id="gemma-4-E2B-it",
    )

    with pytest.raises(HTTPException) as exc_info:
        _managed_local_ai_preflight(context, [synthesis], manager)

    assert getattr(exc_info.value, "status_code", None) == 409
    assert exc_info.value.error_code == "local_ai_wrong_model_running"


def test_managed_preflight_ignores_disabled_synthesis():
    context = SimpleNamespace(
        settings=SimpleNamespace(
            known_llm_hosts={
                "Integrated AI": {
                    "kind": "local_ai",
                    "url": "http://127.0.0.1:11435",
                    "model": "gemma-4-E2B-it",
                }
            }
        )
    )
    manager = MagicMock()
    manager.inventory.return_value = []
    manager.status.return_value = LocalAIStatus(state="stopped")
    synthesis = SimpleNamespace(
        enabled=False,
        api_host="http://127.0.0.1:11435",
        llm_id="gemma-4-E2B-it",
    )

    assert _managed_local_ai_preflight(context, [synthesis], manager) is None
    release = _managed_request_owner(manager, None)
    release()
    manager.mark_request_active.assert_not_called()
    manager.mark_request_idle.assert_not_called()


def test_managed_request_owner_releases_exactly_once_on_duplicate_terminal_callbacks():
    manager = MagicMock()
    release = _managed_request_owner(manager, "gemma-4-e2b")
    callbacks = _stream_callbacks(queue.Queue(), threading.Event(), release)

    callbacks["on_all_complete"]()
    callbacks["on_unexpected_error"]()
    release()

    manager.mark_request_active.assert_called_once_with("gemma-4-e2b")
    manager.mark_request_idle.assert_called_once_with()


@pytest.mark.parametrize("failure", ["runtime stopped", "model switched"])
def test_managed_request_owner_rejects_lifecycle_race_without_false_ownership(failure):
    manager = MagicMock()
    manager.mark_request_active.side_effect = LocalAIStateError(
        failure,
        code="state_conflict",
    )

    with pytest.raises(HTTPException) as exc_info:
        _managed_request_owner(manager, "gemma-4-e2b")

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "state_conflict"
    manager.mark_request_active.assert_called_once_with("gemma-4-e2b")
    manager.mark_request_idle.assert_not_called()


def test_continue_preflights_exact_resolved_rebind_before_mutation(client, mock_context):
    rebound_synthesis = SimpleNamespace(
        enabled=True,
        api_host="http://127.0.0.1:11435",
        llm_id="gemma-4-E2B-it",
    )
    mock_context.discussion.resolve_continuation_configuration.side_effect = None
    mock_context.discussion.resolve_continuation_configuration.return_value = (
        [],
        rebound_synthesis,
    )
    rejection = HTTPException(status_code=409, detail="runtime changed")
    rejection.error_code = "state_conflict"
    rejection.error_params = {}

    with (
        override_context(app, mock_context),
        patch(
            "src.service.routers.discussions._managed_local_ai_preflight",
            return_value="gemma-4-e2b",
        ) as preflight,
        patch(
            "src.service.routers.discussions._managed_request_owner",
            side_effect=rejection,
        ),
    ):
        response = client.post(
            "/api/discussions/continue",
            json={
                "user_input": "Continue",
                "agents": [],
                "provider_rebind": {
                    "configuration_id": "Integrated AI",
                    "model_id": "gemma-4-E2B-it",
                },
            },
        )

    assert response.status_code == 409
    resolved_configurations = preflight.call_args.args[1]
    assert resolved_configurations == [rebound_synthesis]
    mock_context.discussion.continue_discussion.assert_not_called()


def test_stream_disconnect_cancels_owned_generation():
    disconnected = MagicMock()
    response = _stream_response(
        queue.Queue(),
        threading.Event(),
        [{"type": "discussion_started"}],
        on_disconnect=disconnected,
    )
    iterator = response.body_iterator

    async def consume_then_disconnect():
        first = await anext(iterator)
        await iterator.aclose()
        return first

    assert asyncio.run(consume_then_disconnect()).startswith("data: ")
    disconnected.assert_called_once_with()


def test_next_round_configuration_endpoint_is_atomic_and_secret_free(client, mock_context):
    mock_context.discussion.update_next_round_configuration.return_value = "updated"
    payload = {
        "file_id": "session-1",
        "agents": [
            {
                "name": "Perspective 1",
                "client_id": "stable-client",
                "prompt_id": "precision",
                "color": "#123456",
                "temperature": 0.4,
                "llm_id": "model-a",
                "api_host": "https://host.example/v1",
                "host_configuration_id": "host-a",
                "max_tokens": 1024,
                "enabled": True,
                "perspective_number": 1,
            },
            {
                "name": "Unused stable slot",
                "client_id": "disabled-client",
                "prompt_id": None,
                "color": "#654321",
                "temperature": None,
                "llm_id": None,
                "api_host": None,
                "host_configuration_id": None,
                "max_tokens": None,
                "enabled": False,
                "perspective_number": 2,
            },
        ],
        "synthesis": {
            "enabled": False,
            "api_host": None,
            "llm_id": None,
            "host_configuration_id": None,
            "temperature": None,
        },
    }
    with override_context(app, mock_context):
        response = client.put("/api/discussions/next-round-configuration", json=payload)

    assert response.status_code == 200
    assert response.json() == {"agent_count": 2}
    agents = mock_context.discussion.update_next_round_configuration.call_args.args[1]
    assert agents[0].prompt_id == "precision"
    assert agents[0].api_key is None
    assert agents[1].prompt_id is None
    assert agents[1].enabled is False

    payload["agents"][0]["api_key"] = "must-not-cross-boundary"
    with override_context(app, mock_context):
        rejected = client.put("/api/discussions/next-round-configuration", json=payload)
    assert rejected.status_code == 422


def test_material_token_estimate_uses_the_bundled_tokenizer(client):
    material = "Erste Aussage. Zweite Aussage.\n\nUnpunktierte Zeile"
    numbered_material = "Z0001: Erste Aussage. Zweite Aussage.\n\nZ0002: Unpunktierte Zeile"
    response = client.post(
        "/api/material/token-estimate",
        json={"material": material, "material_type": "document"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "approximate_tokens": estimate_tokens(numbered_material),
        "tokenizer": TOKENIZER_NAME,
    }


def test_material_preview_numbers_only_nonblank_physical_lines(client):
    response = client.post(
        "/api/material/with-line-numbers",
        json={"material": "Erste Aussage. Zweite Aussage.\n\nDritte Aussage!\n"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "material": "Z0001: Erste Aussage. Zweite Aussage.\n\nZ0002: Dritte Aussage!"
    }


def test_context_estimate_is_read_only_and_returns_budget_facts(client, mock_context):
    mock_context.discussion.estimate_start_context_budget.return_value = {
        "known": True,
        "estimated_input_tokens": 123,
        "available_input_tokens": 4096,
        "context_window_tokens": 8192,
        "reserved_output_tokens": 4096,
        "overflow": False,
    }
    payload = {
        "material": "Material",
        "agents": [
            {
                "name": "Perspective 1",
                "client_id": "client-1",
                "prompt_id": "role",
                "api_host": "https://configured.example/v1",
                "api_key": "must-not-be-returned",
                "llm_id": "model",
                "perspective_number": 1,
                "enabled": True,
            }
        ],
        "material_context": {
            "material_type": "document",
            "session_type": "exploration",
            "target_language": "English",
            "input_values": {
                "research_material_context": "",
                "main_input": "Question",
                "additional_instructions": "",
            },
        },
        "synthesis": {
            "enabled": False,
            "api_host": None,
            "llm_id": None,
            "temperature": None,
        },
        "sequential_mode": False,
    }
    with override_context(app, mock_context):
        response = client.post("/api/discussions/context-estimate", json=payload)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "known": True,
        "estimated_input_tokens": 123,
        "available_input_tokens": 4096,
        "context_window_tokens": 8192,
        "reserved_output_tokens": 4096,
        "overflow": False,
    }
    mock_context.discussion.estimate_start_context_budget.assert_called_once()


def test_context_estimate_unknown_is_safe_and_validation_failure_has_no_detail(
    client, mock_context
):
    mock_context.discussion.estimate_start_context_budget.return_value = {
        "known": False,
        "estimated_input_tokens": None,
        "available_input_tokens": None,
        "context_window_tokens": None,
        "reserved_output_tokens": 4096,
        "overflow": False,
    }
    payload = {
        "material": "Material",
        "agents": [],
        "material_context": {
            "material_type": "document",
            "session_type": "exploration",
            "target_language": "English",
            "input_values": {
                "research_material_context": "",
                "main_input": "Question",
                "additional_instructions": "",
            },
        },
        "synthesis": {
            "enabled": True,
            "api_host": "https://configured.example/v1",
            "llm_id": "model",
            "temperature": None,
        },
    }
    with override_context(app, mock_context):
        response = client.post("/api/discussions/context-estimate", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["known"] is False
    assert response.json()["available_input_tokens"] is None
    mock_context.llm_manager.get_llm.assert_not_called()

    mock_context.discussion.estimate_start_context_budget.side_effect = ValueError(
        "private validation detail"
    )
    with override_context(app, mock_context):
        invalid = client.post("/api/discussions/context-estimate", json=payload)
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "Invalid discussion configuration"
    assert "private validation detail" not in invalid.text


class TestDiscussionMetadata:
    def test_list_perspectives(self, client, mock_context):
        mock_context.discussion.get_available_perspectives.return_value = [
            ("p1", "Perspective 1"),
            ("p2", "Perspective 2"),
        ]
        with override_context(app, mock_context):
            resp = client.get("/api/discussions/perspectives")
        assert resp.status_code == 200
        assert resp.json() == [
            {"id": "p1", "label": "Perspective 1", "description": None},
            {"id": "p2", "label": "Perspective 2", "description": None},
        ]

    def test_list_session_types(self, client, mock_context):
        mock_context.discussion.get_available_session_types.return_value = [
            ("st1", "Session Type 1"),
        ]
        with override_context(app, mock_context):
            resp = client.get("/api/discussions/session-types")
        assert resp.status_code == 200
        assert resp.json() == [
            {
                "key": "st1",
                "label": "Session Type 1",
                "description": None,
                "inputs": [],
            }
        ]

    def test_get_default_agents(self, client, mock_context):
        mock_context.discussion.get_default_agent_prompt_ids.return_value = ["agent1"]
        with override_context(app, mock_context):
            resp = client.get(
                "/api/discussions/defaults/agents",
                params={"session_type": "test"},
            )
        assert resp.status_code == 200
        assert resp.json() == ["agent1"]

    def test_removed_interpretation_defaults_route_returns_404(self, client):
        resp = client.get(
            "/api/discussions/defaults/interpretation",
            params={"session_type": "exploration"},
        )
        assert resp.status_code == 404

    def test_removed_collection_context_template_route_returns_404(self, client):
        resp = client.get("/api/defaults/collection-context")
        assert resp.status_code == 404

    def test_default_material_uses_exact_shipped_selection_and_document_type(
        self, client, mock_context
    ):
        source_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "prompt_defaults"
            / "European Union (2020) The New Leipzig Charter. The Transform.md"
        )
        source_bytes = source_path.read_bytes()
        assert hashlib.sha256(source_bytes.rstrip(b"\n")).hexdigest() == (
            "f16404526af1175c873c175138e713383779436315009dabdd16ed97df241e5c"
        )
        mock_context.settings.prompt_defaults_path = source_path.parent

        with override_context(app, mock_context):
            resp = client.get("/api/defaults/material")

        assert resp.status_code == 200
        assert resp.json() == {
            "material": source_path.read_text(encoding="utf-8"),
            "material_type": "document",
        }

    def test_default_material_read_error_preserves_document_type(
        self, client, mock_context, tmp_path
    ):
        example_path = tmp_path / "European Union (2020) The New Leipzig Charter. The Transform.md"
        example_path.write_text("placeholder", encoding="utf-8")
        mock_context.settings.prompt_defaults_path = tmp_path

        with (
            override_context(app, mock_context),
            patch(
                "src.service.routers.defaults.Path.read_text",
                side_effect=UnicodeError("bad encoding"),
            ),
        ):
            resp = client.get("/api/defaults/material")

        assert resp.status_code == 200
        assert resp.json() == {"material": "", "material_type": "document"}


class TestDiscussionSSE:
    def test_start_emits_moderator_message_before_eager_worker_events(self, client, mock_context):
        mock_context.discussion.current_session_file_id.return_value = "session-1"
        mock_context.discussion.current_session_title.return_value = (
            "2026-07-14 00:49 Material excerpt"
        )

        def fake_start(**kwargs):
            kwargs["on_agent_start"](
                AgentResponse(
                    message_id="agent-1",
                    agent_index=0,
                    agent_name="A",
                    theory_label="T",
                    color="#fff",
                    text="",
                )
            )
            kwargs["on_all_complete"]()
            return DiscussionMessage(
                id="moderator-1",
                role="user",
                content="Test question?",
                round_number=1,
            )

        mock_context.discussion.start_new_discussion = fake_start
        mock_context.settings.save_user_settings.side_effect = OSError("read-only settings")

        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/start",
                json={
                    "material": "Material",
                    "agents": [],
                    "title": "",
                    "material_context": {
                        "material_type": "document",
                        "session_type": "exploration",
                        "target_language": "English",
                        "input_values": {
                            "research_material_context": "",
                            "main_input": "Test question?",
                            "additional_instructions": "",
                        },
                    },
                    "synthesis": {
                        "enabled": False,
                        "api_host": None,
                        "llm_id": None,
                        "temperature": None,
                    },
                    "sequential_mode": False,
                },
            )
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert ct.startswith("text/event-stream") or "event-stream" in ct

        events = _sse_events(resp.content.decode())
        assert len(events) >= 1
        assert events[0] == {
            "type": "discussion_started",
            "file_id": "session-1",
            "title": "2026-07-14 00:49 Material excerpt",
        }
        assert events[1] == {
            "type": "user_message",
            "message_id": "moderator-1",
            "content": "Test question?",
            "round_number": 1,
        }
        assert events[2]["type"] == "agent_start"
        assert events[-1] == {"type": "all_complete"}
        assert mock_context.settings.last_active_discussion_id == "session-1"
        mock_context.settings.save_user_settings.assert_called_once_with()

    def test_agent_complete_includes_provider_usage(self, client, mock_context):
        mock_context.discussion.current_session_file_id.return_value = "session-1"
        mock_context.discussion.current_session_title.return_value = "Titel"

        def fake_start(**kwargs):
            response = AgentResponse(
                message_id="m1",
                agent_index=0,
                agent_name="A",
                client_id="a1",
                theory_label="T",
                color="#fff",
                text="",
                perspective_number=1,
            )
            kwargs["on_agent_start"](response)
            kwargs["on_agent_complete"](
                AgentResponse(
                    **{
                        **response.__dict__,
                        "is_complete": True,
                        "usage_available": True,
                        "prompt_tokens": 19,
                        "completion_tokens": 5,
                        "total_tokens": 24,
                        "error": "context_limit_exceeded",
                        "error_code": "context_limit_exceeded",
                        "error_params": {
                            "input_tokens": 43_166,
                            "available_input_tokens": 28_672,
                            "context_tokens": 32_768,
                            "reserved_output_tokens": 4_096,
                        },
                    }
                )
            )
            kwargs["on_all_complete"]()

        mock_context.discussion.start_new_discussion = fake_start
        with override_context(app, mock_context):
            response = client.post(
                "/api/discussions/start",
                json={
                    "material": "Material",
                    "agents": [],
                    "material_context": {
                        "material_type": "document",
                        "session_type": "exploration",
                        "target_language": "German",
                        "input_values": {
                            "research_material_context": "",
                            "main_input": "Testfrage",
                            "additional_instructions": "",
                        },
                    },
                    "synthesis": {
                        "enabled": False,
                        "api_host": None,
                        "llm_id": None,
                        "temperature": None,
                    },
                    "sequential_mode": False,
                },
            )

        events = _sse_events(response.content.decode())
        types = [event["type"] for event in events]
        assert "context_usage" not in types
        complete = next(event for event in events if event["type"] == "agent_complete")
        assert complete["client_id"] == "a1"
        assert complete["prompt_tokens"] == 19
        assert complete["completion_tokens"] == 5
        assert complete["total_tokens"] == 24
        assert complete["error_code"] == "context_limit_exceeded"
        assert complete["error_params"] == {
            "input_tokens": 43_166,
            "available_input_tokens": 28_672,
            "context_tokens": 32_768,
            "reserved_output_tokens": 4_096,
        }
        assert "Material" not in str(complete["error_params"])

    def test_start_rejects_blank_required_main_input(self, client, mock_context):

        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/start",
                json={
                    "material": "Material",
                    "agents": [],
                    "synthesis": {
                        "enabled": False,
                        "api_host": None,
                        "llm_id": None,
                        "temperature": None,
                    },
                    "material_context": {
                        "material_type": "document",
                        "session_type": "critique",
                        "target_language": "German",
                        "input_values": {
                            "research_material_context": "",
                            "main_input": "   ",
                            "additional_instructions": "",
                        },
                    },
                },
            )

        assert resp.status_code == 422
        assert resp.json()["error"] == {
            "code": "session_input_required",
            "params": {"session_type": "critique", "input_key": "main_input"},
        }
        mock_context.discussion.start_new_discussion.assert_not_called()

    @pytest.mark.parametrize("target_language", ["", "   "])
    def test_start_rejects_missing_or_blank_target_language(
        self, client, mock_context, target_language
    ):
        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/start",
                json={
                    "material": "Material",
                    "agents": [],
                    "material_context": {
                        "material_type": "document",
                        "session_type": "exploration",
                        "target_language": target_language,
                        "input_values": {
                            "research_material_context": "",
                            "main_input": "Question",
                            "additional_instructions": "",
                        },
                    },
                    "synthesis": {
                        "enabled": False,
                        "api_host": None,
                        "llm_id": None,
                        "temperature": None,
                    },
                },
            )

        assert resp.status_code == 422
        mock_context.discussion.start_new_discussion.assert_not_called()

    @pytest.mark.parametrize("material", ["", "   \n\t"])
    def test_start_rejects_missing_or_blank_material(self, client, mock_context, material):
        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/start",
                json={
                    "material": material,
                    "agents": [],
                    "material_context": {
                        "material_type": "document",
                        "session_type": "exploration",
                        "target_language": "English",
                        "input_values": {
                            "research_material_context": "",
                            "main_input": "Question",
                            "additional_instructions": "",
                        },
                    },
                    "synthesis": {
                        "enabled": False,
                        "api_host": None,
                        "llm_id": None,
                        "temperature": None,
                    },
                },
            )

        assert resp.status_code == 422
        assert resp.json()["error"] == {"code": "material_required", "params": {}}
        mock_context.discussion.start_new_discussion.assert_not_called()

    def test_start_cancelled_run_ends_with_all_complete_no_error(self, client, mock_context):
        mock_context.discussion.current_session_file_id.return_value = "session-2"
        mock_context.discussion.current_session_title.return_value = "Abgebrochene Diskussion"

        def fake_start(**kwargs):
            # Simulate a cancelled/collaborative run that never calls
            # ``on_agent_complete`` but still invokes the completion callback.
            kwargs["on_all_complete"]()

        mock_context.discussion.start_new_discussion = fake_start

        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/start",
                json={
                    "material": "Material",
                    "agents": [],
                    "title": "",
                    "material_context": {
                        "material_type": "document",
                        "session_type": "exploration",
                        "target_language": "English",
                        "input_values": {
                            "research_material_context": "",
                            "main_input": "Test question?",
                            "additional_instructions": "",
                        },
                    },
                    "synthesis": {
                        "enabled": False,
                        "api_host": None,
                        "llm_id": None,
                        "temperature": None,
                    },
                    "sequential_mode": False,
                },
            )
        assert resp.status_code == 200

        events = _sse_events(resp.content.decode())
        assert len(events) >= 1
        assert events[-1] == {"type": "all_complete"}
        assert all(event.get("type") != "error" for event in events)

    def test_start_unexpected_worker_error_emits_one_safe_terminal_event(
        self, client, mock_context
    ):
        def fake_start(**kwargs):
            kwargs["on_unexpected_error"]()

        mock_context.discussion.start_new_discussion = fake_start
        mock_context.discussion.current_session_file_id.return_value = "session-1"
        mock_context.discussion.current_session_title.return_value = "Interrupted discussion"

        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/start",
                json={
                    "material": "Material",
                    "agents": [],
                    "material_context": {
                        "material_type": "document",
                        "session_type": "exploration",
                        "target_language": "English",
                        "input_values": {
                            "research_material_context": "",
                            "main_input": "Test question?",
                            "additional_instructions": "",
                        },
                    },
                    "synthesis": {
                        "enabled": False,
                        "api_host": None,
                        "llm_id": None,
                        "temperature": None,
                    },
                    "sequential_mode": False,
                },
            )

        events = _sse_events(resp.content.decode())
        assert events[-1] == {
            "type": "error",
            "message": "Discussion generation was interrupted.",
            "error_code": "discussion_generation_interrupted",
            "error_params": {},
        }
        assert all(event.get("type") != "all_complete" for event in events)

    def test_continue_no_active_discussion(self, client, mock_context):
        mock_context.discussion.continue_discussion.return_value = None

        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/continue",
                json={
                    "user_input": "Tell me more",
                    "agents": [],
                    "focus_segment": None,
                    "sequential_mode": False,
                },
            )
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert ct.startswith("text/event-stream") or "event-stream" in ct

        events = _sse_events(resp.content.decode())
        assert len(events) == 1
        assert events[0] == {
            "type": "error",
            "message": "No active discussion",
            "error_code": "no_active_discussion",
            "error_params": {},
        }

    def test_continue_reports_stable_provider_rebind_error(self, client, mock_context):
        mock_context.discussion.continue_discussion.side_effect = ProviderRebindRequiredError(2)

        with override_context(app, mock_context):
            response = client.post(
                "/api/discussions/continue",
                json={"user_input": "Continue", "agents": []},
            )

        assert response.status_code == 409
        assert response.json()["error"] == {
            "code": "provider_rebind_required",
            "params": {"count": 2},
        }

    def test_continue_reports_stale_rebind_target_without_contact_details(
        self, client, mock_context
    ):
        mock_context.discussion.continue_discussion.side_effect = ProviderRebindTargetChangedError()

        with override_context(app, mock_context):
            response = client.post(
                "/api/discussions/continue",
                json={
                    "user_input": "Continue",
                    "agents": [],
                    "provider_rebind": {
                        "configuration_id": "Replacement",
                        "model_id": "model",
                    },
                },
            )

        assert response.status_code == 409
        assert response.json()["error"] == {
            "code": "provider_rebind_target_changed",
            "params": {},
        }

    @pytest.mark.parametrize(
        "endpoint,payload",
        [
            (
                "/api/discussions/start",
                {
                    "material": "Material",
                    "agents": [],
                    "material_context": {
                        "material_type": "document",
                        "session_type": "exploration",
                        "target_language": "English",
                        "input_values": {
                            "research_material_context": "",
                            "main_input": "Question",
                            "additional_instructions": "",
                        },
                    },
                    "synthesis": {
                        "enabled": False,
                        "api_host": None,
                        "llm_id": None,
                        "temperature": None,
                    },
                },
            ),
            (
                "/api/discussions/continue",
                {"user_input": "Weiter", "agents": []},
            ),
            (
                "/api/discussions/agents",
                {"agents": []},
            ),
        ],
    )
    @pytest.mark.parametrize(
        "invalid_agent",
        [
            {"name": "A", "unexpected": "ignored before"},
            {"name": "A", "temperature": -0.1},
            {"name": "A", "temperature": 2.1},
            {"name": "A", "temperature": "0.7"},
            {"name": "A", "temperature": True},
            {"name": "A", "max_tokens": 0},
            {"name": "A", "max_tokens": -1},
            {"name": "A", "max_tokens": "1024"},
            {"name": "A", "max_tokens": True},
        ],
    )
    def test_agent_validation_rejects_invalid_nested_values(
        self, client, mock_context, endpoint, payload, invalid_agent
    ):
        payload = {
            **payload,
            "agents": [{"client_id": "agent-1", "perspective_number": 1, **invalid_agent}],
        }

        with override_context(app, mock_context):
            response = (
                client.put(endpoint, json=payload)
                if endpoint == "/api/discussions/agents"
                else client.post(endpoint, json=payload)
            )

        assert response.status_code == 422
        mock_context.discussion.start_new_discussion.assert_not_called()
        mock_context.discussion.continue_discussion.assert_not_called()
        mock_context.discussion.update_current_agents.assert_not_called()

    def test_agent_validation_accepts_numeric_boundaries(self):
        low = AgentConfigModel(
            name="A", client_id="a", perspective_number=1, temperature=0.0, max_tokens=1
        )
        high = AgentConfigModel(
            name="B", client_id="b", perspective_number=2, temperature=2.0, max_tokens=None
        )

        assert low.temperature == 0.0
        assert low.max_tokens == 1
        assert high.temperature == 2.0
        assert high.max_tokens is None

    @pytest.mark.parametrize("value", [None, 0, -1, True, "1"])
    def test_agent_validation_requires_positive_perspective_number(self, value):
        with pytest.raises(ValidationError):
            AgentConfigModel.model_validate(
                {"name": "A", "client_id": "agent-1", "perspective_number": value}
            )

    def test_start_accepts_omitted_temperature(self, client, mock_context):
        captured: dict = {}

        def fake_start(**kwargs):
            captured["agents"] = kwargs.get("agents")
            kwargs["on_all_complete"]()

        mock_context.discussion.current_session_file_id.return_value = "session-x"
        mock_context.discussion.current_session_title.return_value = "Titel"
        mock_context.discussion.start_new_discussion = fake_start

        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/start",
                json={
                    "material": "Material",
                    # No ``temperature`` on the agent — must NOT 422
                    "agents": [
                        {
                            "name": "A1",
                            "client_id": "c1",
                            "prompt_id": "sys_theory",
                            "color": "#abc",
                            # "temperature" key intentionally absent
                            "llm_id": "m",
                            "api_host": "http://h",
                            "max_tokens": 1024,
                            "perspective_number": 1,
                        }
                    ],
                    "title": "",
                    "material_context": {
                        "material_type": "document",
                        "session_type": "exploration",
                        "target_language": "English",
                        "input_values": {
                            "research_material_context": "",
                            "main_input": "Test question?",
                            "additional_instructions": "",
                        },
                    },
                    "synthesis": {
                        "enabled": False,
                        "api_host": None,
                        "llm_id": None,
                        "temperature": None,
                    },
                    "sequential_mode": False,
                },
            )
        assert resp.status_code == 200
        passed = captured["agents"]
        assert passed is not None and len(passed) == 1
        assert passed[0].temperature is None

    def test_start_accepts_explicit_null_temperature(self, client, mock_context):
        captured: dict = {}

        def fake_start(**kwargs):
            captured["agents"] = kwargs.get("agents")
            kwargs["on_all_complete"]()

        mock_context.discussion.current_session_file_id.return_value = "session-x"
        mock_context.discussion.current_session_title.return_value = "Titel"
        mock_context.discussion.start_new_discussion = fake_start

        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/start",
                json={
                    "material": "Material",
                    "agents": [
                        {
                            "name": "A1",
                            "client_id": "c1",
                            "prompt_id": "sys_theory",
                            "color": "#abc",
                            "temperature": None,
                            "llm_id": "m",
                            "api_host": "http://h",
                            "max_tokens": 1024,
                            "perspective_number": 1,
                        }
                    ],
                    "title": "",
                    "material_context": {
                        "material_type": "document",
                        "session_type": "exploration",
                        "target_language": "English",
                        "input_values": {
                            "research_material_context": "",
                            "main_input": "Test question?",
                            "additional_instructions": "",
                        },
                    },
                    "synthesis": {
                        "enabled": False,
                        "api_host": None,
                        "llm_id": None,
                        "temperature": None,
                    },
                    "sequential_mode": False,
                },
            )
        assert resp.status_code == 200
        passed = captured["agents"]
        assert passed is not None and len(passed) == 1
        assert passed[0].temperature is None

    def test_continue_accepts_omitted_temperature(self, client, mock_context):
        captured: dict = {}

        def fake_continue(**kwargs):
            captured["agents"] = kwargs.get("agents")
            kwargs["on_all_complete"]()

        mock_context.discussion.continue_discussion = fake_continue

        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/continue",
                json={
                    "user_input": "Weiter?",
                    "agents": [
                        {
                            "name": "A1",
                            "client_id": "c1",
                            "prompt_id": "sys_theory",
                            "color": "#abc",
                            "llm_id": "m",
                            "api_host": "http://h",
                            "max_tokens": 1024,
                            "perspective_number": 1,
                        }
                    ],
                    "sequential_mode": False,
                },
            )
        assert resp.status_code == 200
        passed = captured["agents"]
        assert passed is not None and len(passed) == 1
        assert passed[0].temperature is None

    def test_continue_accepts_explicit_null_temperature(self, client, mock_context):
        captured: dict = {}

        def fake_continue(**kwargs):
            captured["agents"] = kwargs.get("agents")
            kwargs["on_all_complete"]()

        mock_context.discussion.continue_discussion = fake_continue

        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/continue",
                json={
                    "user_input": "Weiter?",
                    "agents": [
                        {
                            "name": "A1",
                            "client_id": "c1",
                            "prompt_id": "sys_theory",
                            "color": "#abc",
                            "temperature": None,
                            "llm_id": "m",
                            "api_host": "http://h",
                            "max_tokens": 1024,
                            "perspective_number": 1,
                        }
                    ],
                    "sequential_mode": False,
                },
            )
        assert resp.status_code == 200
        passed = captured["agents"]
        assert passed is not None and len(passed) == 1
        assert passed[0].temperature is None


class TestDiscussionState:
    def test_export_uses_public_current_session_title(self, client, mock_context):
        mock_context.discussion.get_markdown.return_value = "# Export"
        mock_context.discussion.current_session_title.return_value = "Export Titel"

        with override_context(app, mock_context):
            resp = client.get("/api/discussions/export")

        assert resp.status_code == 200
        assert 'filename="Export-Titel.md"' in resp.headers["content-disposition"]
        mock_context.discussion.get_markdown.assert_called_once_with(locale="de")
        mock_context.discussion.current_session_title.assert_called_once()

    def test_export_forwards_english_locale(self, client, mock_context):
        mock_context.discussion.get_markdown.return_value = "# Export"
        mock_context.discussion.current_session_title.return_value = "Export title"

        with override_context(app, mock_context):
            resp = client.get("/api/discussions/export?locale=en")

        assert resp.status_code == 200
        mock_context.discussion.get_markdown.assert_called_once_with(locale="en")

    def test_export_uses_safe_requested_download_filename(self, client, mock_context):
        mock_context.discussion.get_markdown.return_value = "# Export"
        mock_context.discussion.current_session_title.return_value = "Export title"

        with override_context(app, mock_context):
            resp = client.get(
                "/api/discussions/export?locale=en&download_filename="
                "2026-09-04_16-13_AQA_bauen-im-bestand.md"
            )

        assert resp.status_code == 200
        assert (
            'filename="2026-09-04_16-13_AQA_bauen-im-bestand.md"'
            in resp.headers["content-disposition"]
        )

    def test_export_ignores_unsafe_requested_download_filename(self, client, mock_context):
        mock_context.discussion.get_markdown.return_value = "# Export"
        mock_context.discussion.current_session_title.return_value = "Export title"

        with override_context(app, mock_context):
            resp = client.get(
                "/api/discussions/export?locale=en&download_filename=../../settings.json"
            )

        assert resp.status_code == 200
        assert 'filename="Export-title.md"' in resp.headers["content-disposition"]

    def test_export_rejects_unsupported_locale(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.get("/api/discussions/export?locale=fr")

        assert resp.status_code == 422
        mock_context.discussion.get_markdown.assert_not_called()

    def test_get_state(self, client, mock_context):
        state = DiscussionState()
        state.material = "some material"
        state.initial_question = "some question"
        state.round_number = 2
        state.messages = [
            DiscussionMessage(id="m1", role="user", content="hello"),
            DiscussionMessage(
                id="m2",
                role="agent",
                content="world",
                agent_name="Agent1",
                theory_label="Label",
                color="#333",
                agent_index=0,
                round_number=1,
                note="nice",
            ),
        ]

        mock_context.discussion.state = state
        mock_context.discussion.has_active_discussion = True

        with override_context(app, mock_context):
            resp = client.get("/api/discussions/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["material"] == "some material"
        assert data["initial_question"] == "some question"
        assert data["round_number"] == 2
        assert data["has_active_discussion"] is True
        assert len(data["messages"]) == 2
        assert data["messages"][0]["id"] == "m1"
        assert data["messages"][1]["id"] == "m2"
        assert data["messages"][1]["agent_name"] == "Agent1"
        assert data["messages"][1]["note"] == "nice"

    def test_get_state_treats_failed_status_as_error_without_raw_message(
        self, client, mock_context
    ):
        state = DiscussionState()
        state.messages = [
            DiscussionMessage(
                id="m1",
                role="agent",
                content="",
                status="failed",
                error_code="provider_empty_response",
            )
        ]
        mock_context.discussion.state = state
        mock_context.discussion.has_active_discussion = False

        with override_context(app, mock_context):
            response = client.get("/api/discussions/state")

        assert response.status_code == 200
        assert response.json()["has_errors"] is True

    def test_cancel_generation_true(self, client, mock_context):
        mock_context.discussion.cancel_active_generation.return_value = True
        with override_context(app, mock_context):
            resp = client.post("/api/discussions/cancel")
        assert resp.status_code == 200
        assert resp.json() == {"status": "cancelling"}
        mock_context.discussion.cancel_active_generation.assert_called_once()

    def test_cancel_generation_false(self, client, mock_context):
        mock_context.discussion.cancel_active_generation.return_value = False
        with override_context(app, mock_context):
            resp = client.post("/api/discussions/cancel")
        assert resp.status_code == 200
        assert resp.json() == {"status": "idle"}
        mock_context.discussion.cancel_active_generation.assert_called_once()

    def test_reset(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.post("/api/discussions/reset")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        mock_context.discussion.cancel_active_generation.assert_called_once()
        mock_context.discussion.reset_discussion.assert_called_once()
        # Cancel must be invoked before reset.
        assert mock_context.discussion.method_calls[0][0] == "cancel_active_generation"

    def test_reset_preserves_discussion_when_cancellation_save_fails(self, client, mock_context):
        mock_context.discussion.cancel_active_generation.side_effect = RuntimeError("save failed")

        with override_context(app, mock_context), pytest.raises(RuntimeError, match="save failed"):
            client.post("/api/discussions/reset")

        mock_context.discussion.cancel_active_generation.assert_called_once()
        mock_context.discussion.reset_discussion.assert_not_called()


class TestDiscussionNotes:
    def test_set_note_no_message(self, client, mock_context):
        mock_context.discussion.set_message_note.return_value = False
        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/messages/nonexistent/note",
                json={"note": "test note"},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Message not found"

    def test_set_note_success(self, client, mock_context):
        mock_context.discussion.set_message_note.return_value = True
        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/messages/existing/note",
                json={"note": "my note"},
            )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        mock_context.discussion.set_message_note.assert_called_with("existing", "my note", False)

    def test_set_note_can_opt_into_agent_context(self, client, mock_context):
        mock_context.discussion.set_message_note.return_value = True
        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/messages/existing/note",
                json={"note": "my note", "include_note_in_agent_context": True},
            )
        assert resp.status_code == 200
        mock_context.discussion.set_message_note.assert_called_with("existing", "my note", True)

    def test_delete_note_no_message(self, client, mock_context):
        mock_context.discussion.clear_message_note.return_value = False
        with override_context(app, mock_context):
            resp = client.delete("/api/discussions/messages/nonexistent/note")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Message not found"

    def test_delete_note_success(self, client, mock_context):
        mock_context.discussion.clear_message_note.return_value = True
        with override_context(app, mock_context):
            resp = client.delete("/api/discussions/messages/existing/note")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        mock_context.discussion.clear_message_note.assert_called_with("existing")


class TestHosts:
    def test_get_hosts(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Local": {
                "url": "http://localhost:1234",
                "api_key": "",
                "model": "gpt-3",
            },
            "Remote": {
                "url": "http://remote:1234",
                "api_key": "secret",
                "model": "gpt-4",
            },
        }
        with override_context(app, mock_context):
            resp = client.get("/api/hosts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["label"] == "Local"
        assert data[0]["has_api_key"] is False
        assert data[1]["label"] == "Remote"
        assert data[1]["has_api_key"] is True

    def test_get_hosts_redacts_api_key(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Remote": {"url": "http://r:1", "api_key": "topsecret", "model": "m"},
        }
        with override_context(app, mock_context):
            resp = client.get("/api/hosts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        # The key value must not be present, and the field name must not exist
        assert "api_key" not in data[0]
        assert "topsecret" not in resp.text

    def test_get_hosts_returns_models_and_managed_kind(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Managed": {
                "url": "http://127.0.0.1:8080",
                "api_key": "",
                "model": "preferred",
                "models": ["preferred", "alternate"],
                "kind": "local_ai",
            },
        }
        with override_context(app, mock_context):
            resp = client.get("/api/hosts")
        assert resp.status_code == 200
        assert resp.json() == [
            {
                "configuration_id": "Managed",
                "label": "Managed",
                "url": "http://127.0.0.1:8080",
                "model": "preferred",
                "models": ["preferred", "alternate"],
                "kind": "local_ai",
                "has_api_key": False,
                "is_favorite": False,
                "model_context_tokens": {},
                "context_tokens": None,
            }
        ]

    def test_get_hosts_separates_managed_configuration_id_from_display_label(
        self, client, mock_context
    ):
        mock_context.settings.known_llm_hosts = {
            LOCAL_AI_HOST_LABEL: _local_ai_host(),
        }

        with override_context(app, mock_context):
            response = client.get("/api/hosts")

        assert response.status_code == 200
        assert response.json()[0]["configuration_id"] == LOCAL_AI_HOST_LABEL
        assert response.json()[0]["label"] == "Integrierte KI"

    def test_host_key_route_is_not_exposed(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Only": {"url": "http://h:1", "api_key": "k", "model": "m"},
        }
        with override_context(app, mock_context):
            resp = client.get("/api/hosts/0/key")
        assert resp.status_code == 404
        assert "k" not in resp.text

    def test_host_list_does_not_enable_cross_origin_reads(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Remote": {"url": "http://r:1", "api_key": "topsecret", "model": "m"},
        }
        with override_context(app, mock_context):
            resp = client.get("/api/hosts", headers={"Origin": "https://untrusted.example"})
        assert resp.status_code == 200
        assert "access-control-allow-origin" not in resp.headers
        assert "topsecret" not in resp.text

    def test_get_models_for_host(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Local": {
                "url": "http://localhost:1234",
                "api_key": "",
                "model": " gpt-3 ",
                "models": ["gpt-3", "gpt-3-small", "gpt-3"],
            },
        }
        mock_context.llm_manager._list_available_model_ids.return_value = [
            "live-model",
            "live-model-small",
        ]
        with override_context(app, mock_context):
            resp = client.get("/api/hosts/0/models")
        assert resp.status_code == 200
        assert resp.json() == {"models": ["live-model", "live-model-small"]}
        mock_context.llm_manager._list_available_model_ids.assert_called_once_with(
            host="http://localhost:1234",
            api_key=None,
            timeout=5,
        )

    def test_get_models_host_not_found(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {"Only": {"url": "", "api_key": "", "model": ""}}
        with override_context(app, mock_context):
            resp = client.get("/api/hosts/999/models")
        assert resp.status_code == 404

    def test_get_models_sanitizes_provider_failure(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Only": {
                "url": "https://provider.example/v1",
                "api_key": "stored-secret",
                "model": "m",
            }
        }
        mock_context.llm_manager._list_available_model_ids.side_effect = RuntimeError(
            "Authorization: Bearer stored-secret"
        )

        with override_context(app, mock_context):
            response = client.get("/api/hosts/0/models")

        assert response.status_code == 502
        assert response.json()["error"] == {
            "code": "host_models_unavailable",
            "params": {},
        }
        assert "stored-secret" not in response.text

    def test_create_host_success(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {}
        with override_context(app, mock_context):
            resp = client.post(
                "/api/hosts",
                json={
                    "label": "My Host",
                    "url": "http://my-host:1234",
                    "model": "gpt-4",
                    "api_key": "sk-abc",
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["label"] == "My Host"
        assert data["url"] == "http://my-host:1234"
        assert data["model"] == "gpt-4"
        assert data["has_api_key"] is True
        assert "My Host" in mock_context.settings.known_llm_hosts
        assert mock_context.settings.known_llm_hosts["My Host"]["api_key"] == "sk-abc"

    @pytest.mark.parametrize("method,path", [("post", "/api/hosts"), ("put", "/api/hosts/0")])
    def test_host_write_rejects_whitespace_only_model(self, client, mock_context, method, path):
        mock_context.settings.known_llm_hosts = {
            "Existing": {
                "url": "https://provider.example/v1",
                "api_key": "",
                "model": "existing-model",
                "models": ["existing-model"],
            }
        }
        payload = (
            {"label": "New", "url": "https://provider.example/v1", "model": "   "}
            if method == "post"
            else {"model": "   "}
        )

        with override_context(app, mock_context):
            response = getattr(client, method)(path, json=payload)

        assert response.status_code == 422
        mock_context.settings.save_user_settings.assert_not_called()

    def test_create_host_no_api_key(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {}
        with override_context(app, mock_context):
            resp = client.post(
                "/api/hosts",
                json={
                    "label": "No Key",
                    "url": "https://secure-host:8080",
                    "model": "gpt-3",
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["has_api_key"] is False
        assert mock_context.settings.known_llm_hosts["No Key"]["api_key"] == ""

    def test_create_host_persists_context_limits_by_selected_model(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {}
        with override_context(app, mock_context):
            response = client.post(
                "/api/hosts",
                json={
                    "label": "Limited",
                    "url": "https://limited.example/v1",
                    "model": "small",
                    "models": ["small", "large"],
                    "model_context_tokens": {"small": 32_768, "large": 131_072},
                },
            )
        assert response.status_code == 201
        assert response.json()["model_context_tokens"] == {"small": 32_768, "large": 131_072}
        assert mock_context.settings.known_llm_hosts["Limited"]["model_context_tokens"] == {
            "small": 32_768,
            "large": 131_072,
        }

    def test_create_host_rejects_limit_for_unknown_model(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {}
        with override_context(app, mock_context):
            response = client.post(
                "/api/hosts",
                json={
                    "label": "Invalid limit",
                    "url": "https://limited.example/v1",
                    "model": "small",
                    "model_context_tokens": {"other": 32_768},
                },
            )
        assert response.status_code == 422

    def test_create_host_duplicate_label(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Existing": {"url": "", "api_key": "", "model": ""}
        }
        with override_context(app, mock_context):
            resp = client.post(
                "/api/hosts",
                json={
                    "label": "Existing",
                    "url": "http://host:1234",
                    "model": "m",
                },
            )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_create_host_invalid_url(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {}
        with override_context(app, mock_context):
            resp = client.post(
                "/api/hosts",
                json={
                    "label": "Bad URL",
                    "url": "ftp://bad",
                    "model": "m",
                },
            )
        assert resp.status_code == 422
        assert resp.json() == {
            "detail": "Enter a valid URL beginning with http:// or https://.",
            "error": {"code": "host_url_invalid", "params": {}},
        }

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://host.example",
            "host.example",
            "http://",
            "http:///v1",
            "http://host.example:bad-port",
            "http://[",
        ],
    )
    def test_create_host_rejects_malformed_url_with_stable_error(self, client, mock_context, url):
        mock_context.settings.known_llm_hosts = {}
        with override_context(app, mock_context):
            response = client.post(
                "/api/hosts",
                json={"label": "Bad URL", "url": url, "model": "m"},
            )

        assert response.status_code == 422
        assert response.json()["error"] == {"code": "host_url_invalid", "params": {}}
        mock_context.settings.save_user_settings.assert_not_called()

    def test_create_host_trims_a_valid_url(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {}
        with override_context(app, mock_context):
            response = client.post(
                "/api/hosts",
                json={
                    "label": "Trimmed URL",
                    "url": "  https://127.0.0.1:8080/v1  ",
                    "model": "m",
                },
            )

        assert response.status_code == 201
        assert response.json()["url"] == "https://127.0.0.1:8080/v1"
        assert mock_context.settings.known_llm_hosts["Trimmed URL"]["url"] == (
            "https://127.0.0.1:8080/v1"
        )

    def test_create_host_trims_label_and_rejects_embedded_url_credentials(
        self, client, mock_context
    ):
        mock_context.settings.known_llm_hosts = {}
        with override_context(app, mock_context):
            created = client.post(
                "/api/hosts",
                json={"label": "  Provider  ", "url": "https://host.example/v1", "model": "m"},
            )
            rejected = client.post(
                "/api/hosts",
                json={
                    "label": "Unsafe",
                    "url": "https://user:secret@host.example/v1",
                    "model": "m",
                },
            )

        assert created.status_code == 201
        assert created.json()["configuration_id"] == "Provider"
        assert "Provider" in mock_context.settings.known_llm_hosts
        assert rejected.status_code == 422
        assert rejected.json()["error"] == {"code": "host_url_invalid", "params": {}}
        assert "secret" not in rejected.text

    def test_create_host_restores_catalog_when_save_fails(self, client, mock_context):
        original = {
            "Existing": {
                "url": "https://existing.example/v1",
                "api_key": "",
                "model": "m",
                "models": ["m"],
                "is_favorite": True,
            }
        }
        mock_context.settings.known_llm_hosts = deepcopy(original)
        mock_context.settings.save_user_settings.side_effect = OSError("private disk detail")

        with override_context(app, mock_context):
            response = client.post(
                "/api/hosts",
                json={
                    "label": "New",
                    "url": "https://new.example/v1",
                    "model": "new",
                    "is_favorite": True,
                },
            )

        assert response.status_code == 500
        assert response.json()["error"] == {
            "code": "host_create_persistence_failed",
            "params": {},
        }
        assert "private disk detail" not in response.text
        assert mock_context.settings.known_llm_hosts == original

    # PUT /api/hosts/{index}
    def test_update_host_all_fields(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Old Label": {"url": "http://old:1234", "api_key": "", "model": "old-model"},
        }
        with override_context(app, mock_context):
            resp = client.put(
                "/api/hosts/0",
                json={
                    "configuration_id": "Old Label",
                    "label": "New Label",
                    "url": "http://new:5678",
                    "model": "new-model",
                    "api_key": "new-key",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "New Label"
        assert data["url"] == "http://new:5678"
        assert data["model"] == "new-model"
        assert data["has_api_key"] is True
        # The replaced key is absent.
        assert "Old Label" not in mock_context.settings.known_llm_hosts
        assert "New Label" in mock_context.settings.known_llm_hosts

    def test_update_host_partial(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Test": {"url": "http://old:1234", "api_key": "secret", "model": "old-model"},
        }
        with override_context(app, mock_context):
            resp = client.put(
                "/api/hosts/0",
                json={"configuration_id": "Test", "model": "new-model"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "Test"
        assert data["url"] == "http://old:1234"
        assert data["model"] == "new-model"
        assert data["has_api_key"] is True

    def test_create_and_update_trim_custom_model_ids(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {}
        with override_context(app, mock_context):
            created = client.post(
                "/api/hosts",
                json={
                    "label": "Custom",
                    "url": "https://provider.example/v1",
                    "model": "  @preset/custom-fast  ",
                },
            )
        assert created.status_code == 201
        assert created.json()["model"] == "@preset/custom-fast"
        assert mock_context.settings.known_llm_hosts["Custom"]["model"] == "@preset/custom-fast"

        with override_context(app, mock_context):
            updated = client.put(
                "/api/hosts/0",
                json={"configuration_id": "Custom", "model": "  deployment-alias  "},
            )
        assert updated.status_code == 200
        assert updated.json()["model"] == "deployment-alias"
        assert mock_context.settings.known_llm_hosts["Custom"]["models"][:2] == [
            "deployment-alias",
            "@preset/custom-fast",
        ]

    @pytest.mark.parametrize("url", ["https://", "host.example", "http://[::1"])
    def test_update_host_rejects_malformed_url_with_stable_error(self, client, mock_context, url):
        mock_context.settings.known_llm_hosts = {
            "Existing": {"url": "http://localhost:1234", "api_key": "", "model": "m"},
        }
        with override_context(app, mock_context):
            response = client.put("/api/hosts/0", json={"configuration_id": "Existing", "url": url})

        assert response.status_code == 422
        assert response.json()["error"] == {"code": "host_url_invalid", "params": {}}
        assert mock_context.settings.known_llm_hosts["Existing"]["url"] == "http://localhost:1234"
        mock_context.settings.save_user_settings.assert_not_called()

    def test_update_host_trims_a_valid_url(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Existing": {"url": "http://localhost:1234", "api_key": "", "model": "m"},
        }
        with override_context(app, mock_context):
            response = client.put(
                "/api/hosts/0",
                json={"configuration_id": "Existing", "url": " https://[::1]:8080/v1 "},
            )

        assert response.status_code == 200
        assert response.json()["url"] == "https://[::1]:8080/v1"

    def test_update_managed_local_ai_rejects_technical_fields(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Lokale KI": {
                "url": "http://127.0.0.1:8080",
                "api_key": "",
                "model": "gemma-4-E2B-it",
                "models": ["gemma-4-E2B-it", "gemma-4-E4B-it", "gemma-4-12B-it"],
                "kind": "local_ai",
            },
        }
        with override_context(app, mock_context):
            response = client.put(
                "/api/hosts/0",
                json={"configuration_id": "Lokale KI", "model": "other"},
            )
        assert response.status_code == 422
        assert mock_context.settings.known_llm_hosts["Lokale KI"]["model"] == "gemma-4-E2B-it"

    def test_update_host_clear_api_key(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Test": {"url": "http://h:1234", "api_key": "secret", "model": "m"},
        }
        with override_context(app, mock_context):
            resp = client.put("/api/hosts/0", json={"configuration_id": "Test", "api_key": None})
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_api_key"] is False
        assert mock_context.settings.known_llm_hosts["Test"]["api_key"] == ""

    def test_update_host_label_collision(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "First": {"url": "http://a:1", "api_key": "", "model": "m"},
            "Second": {"url": "http://b:2", "api_key": "", "model": "m"},
        }
        with override_context(app, mock_context):
            resp = client.put(
                "/api/hosts/0",
                json={"configuration_id": "First", "label": "Second"},
            )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_update_host_not_found(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {"Only": {"url": "", "api_key": "", "model": ""}}
        with override_context(app, mock_context):
            resp = client.put("/api/hosts/999", json={"configuration_id": "Only", "model": "x"})
        assert resp.status_code == 404

    def test_update_host_rejects_stale_index_identity_before_mutation(self, client, mock_context):
        original = {
            "Replacement": {
                "url": "https://replacement.example/v1",
                "api_key": "replacement-secret",
                "model": "replacement-model",
            },
            "Expected": {
                "url": "https://expected.example/v1",
                "api_key": "expected-secret",
                "model": "expected-model",
            },
        }
        mock_context.settings.known_llm_hosts = deepcopy(original)

        with override_context(app, mock_context):
            response = client.put(
                "/api/hosts/0",
                json={"configuration_id": "Expected", "model": "changed"},
            )

        assert response.status_code == 409
        assert response.json()["error"] == {"code": "host_catalog_changed", "params": {}}
        assert "replacement-secret" not in response.text
        assert "expected-secret" not in response.text
        assert mock_context.settings.known_llm_hosts == original
        mock_context.settings.save_user_settings.assert_not_called()

    def test_delete_host_success(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "A": {"url": "http://a:1", "api_key": "private", "model": "m"},
            "B": {"url": "http://b:2", "api_key": "", "model": "m"},
        }
        mock_context.discussion.sessions_referencing_host.return_value = []
        with override_context(app, mock_context):
            preview = client.post("/api/hosts/delete-preview", json={"label": "A"})
            resp = client.post(
                "/api/hosts/delete",
                json={"label": "A", "revision": preview.json()["revision"]},
            )
        assert resp.status_code == 200
        assert resp.json() == {"deleted": True, "label": "A", "credential_removed": True}
        assert "private" not in preview.text
        assert "A" not in mock_context.settings.known_llm_hosts
        assert "B" in mock_context.settings.known_llm_hosts

    def test_delete_preview_reports_secret_free_dependencies(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "A": {
                "url": "http://a:1",
                "api_key": "private",
                "model": "m",
                "models": ["m"],
                "is_favorite": True,
            },
            "B": {"url": "http://b:2", "api_key": "", "model": "m", "models": ["m"]},
        }
        mock_context.discussion.sessions_referencing_host.return_value = [
            {"file_id": "saved-one", "title": "Saved One"}
        ]
        with override_context(app, mock_context):
            response = client.post("/api/hosts/delete-preview", json={"label": "A"})

        assert response.status_code == 200
        assert response.json()["is_preferred"] is True
        assert response.json()["credential_will_be_removed"] is True
        assert response.json()["saved_sessions"] == [{"file_id": "saved-one", "title": "Saved One"}]
        mock_context.discussion.sessions_referencing_host.assert_called_once_with("A", "http://a:1")
        assert "private" not in response.text

    def test_provider_provenance_returns_only_safe_authoritative_fields(self, client, mock_context):
        mock_context.discussion.round_provider_provenance_snapshot.return_value = [
            {
                "round_number": 2,
                "providers": [
                    {
                        "kind": "perspective",
                        "client_id": "agent-1",
                        "prompt_id": "precision",
                        "prompt_label": "Precision",
                        "perspective_number": 1,
                        "temperature": 0.4,
                        "host_configuration_id": "Replacement",
                        "host_label": "Replacement",
                        "api_host": "https://replacement.example/v1",
                        "model_id": "replacement-model",
                    }
                ],
            }
        ]

        with override_context(app, mock_context):
            response = client.get("/api/discussions/provider-provenance")

        assert response.status_code == 200
        assert response.json() == [
            {
                "round_number": 2,
                "providers": [
                    {
                        "kind": "perspective",
                        "client_id": "agent-1",
                        "prompt_id": "precision",
                        "prompt_label": "Precision",
                        "perspective_number": 1,
                        "temperature": 0.4,
                        "host_configuration_id": "Replacement",
                        "host_label": "Replacement",
                        "api_host": "https://replacement.example/v1",
                        "model_id": "replacement-model",
                    }
                ],
            }
        ]
        assert "api_key" not in response.text

    def test_delete_host_rejects_changed_preflight(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "A": {"url": "http://a:1", "api_key": "", "model": "m", "models": ["m"]},
            "B": {"url": "http://b:2", "api_key": "", "model": "m", "models": ["m"]},
        }
        mock_context.discussion.sessions_referencing_host.return_value = []
        with override_context(app, mock_context):
            preview = client.post("/api/hosts/delete-preview", json={"label": "A"})
            mock_context.settings.known_llm_hosts["A"]["model"] = "changed"
            mock_context.settings.known_llm_hosts["A"]["models"] = ["changed"]
            response = client.post(
                "/api/hosts/delete",
                json={"label": "A", "revision": preview.json()["revision"]},
            )

        assert response.status_code == 409
        assert response.json()["error"] == {"code": "host_catalog_changed", "params": {}}
        assert "A" in mock_context.settings.known_llm_hosts

    def test_delete_host_rejects_nonempty_credential_replacement(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "A": {"url": "http://a:1", "api_key": "first-secret", "model": "m"},
            "B": {"url": "http://b:2", "api_key": "", "model": "m"},
        }
        mock_context.discussion.sessions_referencing_host.return_value = []
        with override_context(app, mock_context):
            preview = client.post("/api/hosts/delete-preview", json={"label": "A"})
            mock_context.settings.known_llm_hosts["A"]["api_key"] = "replacement-secret"
            response = client.post(
                "/api/hosts/delete",
                json={"label": "A", "revision": preview.json()["revision"]},
            )

        assert response.status_code == 409
        assert "first-secret" not in preview.text
        assert "replacement-secret" not in response.text
        assert "A" in mock_context.settings.known_llm_hosts

    def test_delete_host_restores_memory_when_save_fails(self, client, mock_context):
        original = {
            "A": {"url": "http://a:1", "api_key": "private", "model": "m", "models": ["m"]},
            "B": {"url": "http://b:2", "api_key": "", "model": "m", "models": ["m"]},
        }
        mock_context.settings.known_llm_hosts = original
        mock_context.discussion.sessions_referencing_host.return_value = []
        with override_context(app, mock_context):
            preview = client.post("/api/hosts/delete-preview", json={"label": "A"})
            mock_context.settings.save_user_settings.side_effect = OSError("disk refused")
            response = client.post(
                "/api/hosts/delete",
                json={"label": "A", "revision": preview.json()["revision"]},
            )

        assert response.status_code == 500
        assert response.json()["error"] == {
            "code": "host_delete_persistence_failed",
            "params": {},
        }
        assert mock_context.settings.known_llm_hosts == {
            "A": {"url": "http://a:1", "api_key": "private", "model": "m", "models": ["m"]},
            "B": {"url": "http://b:2", "api_key": "", "model": "m", "models": ["m"]},
        }

    def test_delete_host_last_refused(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Only": {"url": "", "api_key": "", "model": ""},
        }
        with override_context(app, mock_context):
            resp = client.post("/api/hosts/delete-preview", json={"label": "Only"})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "host_delete_last_configuration"

    def test_delete_host_not_found(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {"A": {"url": "", "api_key": "", "model": ""}}
        with override_context(app, mock_context):
            resp = client.post("/api/hosts/delete-preview", json={"label": "Missing"})
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "host_not_found"

    # POST /api/hosts/{index}/test
    def test_test_host_success(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Test": {"url": "http://host:1234", "api_key": "key", "model": "m"},
        }
        mock_context.llm_manager.check_connection.return_value = None
        mock_context.llm_manager._list_available_model_ids.return_value = [
            "live-model",
            "live-small",
        ]
        with override_context(app, mock_context):
            resp = client.post(
                "/api/hosts/0/test",
                json={"configuration_id": "Test", "url": "http://host:1234"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["code"] == "connection_established"
        assert data["models"] == ["live-model", "live-small"]
        assert data["message"] == "Connection established"
        mock_context.llm_manager._list_available_model_ids.assert_called_once_with(
            host="http://host:1234", api_key="key", timeout=5
        )

    def test_test_host_no_models(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Test": {"url": "http://host:1234", "api_key": "", "model": "m"},
        }
        mock_context.llm_manager.check_connection.return_value = None
        with override_context(app, mock_context):
            resp = client.post(
                "/api/hosts/0/test",
                json={"configuration_id": "Test", "url": "http://host:1234"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["code"] == "connection_established"
        assert data["models"] == []
        assert data["message"] == "Connection established"

    def test_test_host_error(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Test": {"url": "http://host:1234", "api_key": "", "model": "m"},
        }
        mock_context.llm_manager.check_connection.side_effect = ConnectionError(
            "Connection refused"
        )
        with override_context(app, mock_context):
            resp = client.post(
                "/api/hosts/0/test",
                json={"configuration_id": "Test", "url": "http://host:1234"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["code"] == "connection_failed"
        assert data["message"] == "Connection failed"

    def test_test_host_not_found(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {"A": {"url": "", "api_key": "", "model": ""}}
        with override_context(app, mock_context):
            resp = client.post(
                "/api/hosts/999/test",
                json={"configuration_id": "A", "url": "http://host:1"},
            )
        assert resp.status_code == 404

    def test_test_host_rejects_stale_index_identity_before_using_credentials(
        self, client, mock_context
    ):
        mock_context.settings.known_llm_hosts = {
            "Replacement": {
                "url": "https://replacement.example/v1",
                "api_key": "replacement-secret",
                "model": "replacement-model",
            },
            "Expected": {
                "url": "https://expected.example/v1",
                "api_key": "expected-secret",
                "model": "expected-model",
            },
        }

        with override_context(app, mock_context):
            response = client.post(
                "/api/hosts/0/test",
                json={
                    "configuration_id": "Expected",
                    "url": "https://expected.example/v1",
                },
            )

        assert response.status_code == 409
        assert response.json()["error"] == {"code": "host_catalog_changed", "params": {}}
        assert "replacement-secret" not in response.text
        assert "expected-secret" not in response.text
        mock_context.llm_manager.check_connection.assert_not_called()
        mock_context.llm_manager._list_available_model_ids.assert_not_called()

    def test_test_draft_host_returns_models_without_mutating_settings(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Existing": {"url": "http://saved", "api_key": "stored-secret", "model": "saved-model"}
        }
        mock_context.llm_manager.check_connection.return_value = None
        mock_context.llm_manager._list_available_model_ids.return_value = [
            "live-model",
            "live-small",
        ]
        with override_context(app, mock_context):
            resp = client.post(
                "/api/hosts/test-connection",
                json={"url": "https://draft.example/v1", "api_key": "draft-secret"},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "ok": True,
            "code": "connection_established",
            "message": "Connection established",
            "models": ["live-model", "live-small"],
        }
        mock_context.llm_manager.check_connection.assert_called_once_with(
            host="https://draft.example/v1", api_key="draft-secret", timeout=5
        )
        mock_context.llm_manager._list_available_model_ids.assert_called_once_with(
            host="https://draft.example/v1", api_key="draft-secret", timeout=5
        )
        assert mock_context.settings.known_llm_hosts == {
            "Existing": {"url": "http://saved", "api_key": "stored-secret", "model": "saved-model"}
        }
        mock_context.settings.save_user_settings.assert_not_called()

    def test_test_draft_host_failure_does_not_echo_secret(self, client, mock_context):
        mock_context.llm_manager.check_connection.side_effect = ConnectionError(
            "Authorization: Bearer draft-secret refused"
        )
        with override_context(app, mock_context):
            resp = client.post(
                "/api/hosts/test-connection",
                json={"url": "http://draft.example", "api_key": "draft-secret"},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "ok": False,
            "code": "connection_failed",
            "message": "Connection failed",
            "models": [],
        }
        assert "draft-secret" not in resp.text

    def test_test_draft_host_rejects_non_http_url(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.post(
                "/api/hosts/test-connection",
                json={"url": "ftp://draft.example", "api_key": "draft-secret"},
            )
        assert resp.status_code == 422
        assert resp.json()["error"] == {"code": "host_url_invalid", "params": {}}
        mock_context.llm_manager.check_connection.assert_not_called()

    @pytest.mark.parametrize("url", ["http://", "https:///v1", "draft.example"])
    def test_test_draft_host_rejects_malformed_urls_with_stable_error(
        self, client, mock_context, url
    ):
        with override_context(app, mock_context):
            response = client.post("/api/hosts/test-connection", json={"url": url})

        assert response.status_code == 422
        assert response.json()["error"] == {"code": "host_url_invalid", "params": {}}
        mock_context.llm_manager.check_connection.assert_not_called()

    def test_test_draft_host_trims_a_valid_url(self, client, mock_context):
        mock_context.llm_manager.check_connection.return_value = None
        mock_context.llm_manager._list_available_model_ids.return_value = []
        with override_context(app, mock_context):
            response = client.post(
                "/api/hosts/test-connection",
                json={"url": " http://localhost:1234/v1 "},
            )

        assert response.status_code == 200
        mock_context.llm_manager.check_connection.assert_called_once_with(
            host="http://localhost:1234/v1", api_key=None, timeout=5
        )


class TestHostTask2:
    def test_create_host_returns_models_and_kind_without_api_key(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {}
        with override_context(app, mock_context):
            resp = client.post(
                "/api/hosts",
                json={
                    "label": "My Host",
                    "url": "http://my-host:1234",
                    "model": "gpt-4",
                    "models": ["gpt-4", "gpt-3", "gpt-4"],
                    "kind": "custom",
                    "api_key": "sk-abc",
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["models"] == ["gpt-4", "gpt-3"]
        assert data["kind"] == "custom"
        assert "api_key" not in data
        assert mock_context.settings.known_llm_hosts["My Host"]["models"] == [
            "gpt-4",
            "gpt-3",
        ]

    def test_create_and_update_reject_unknown_fields(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Host": {"url": "http://host:1", "api_key": "secret", "model": "m"},
        }
        with override_context(app, mock_context):
            create = client.post(
                "/api/hosts",
                json={
                    "label": "New",
                    "url": "http://new:1",
                    "model": "m",
                    "unexpected": True,
                },
            )
            update = client.put("/api/hosts/0", json={"unexpected": True})
        assert create.status_code == 422
        assert update.status_code == 422

    def test_update_models_and_clear_vs_omit_api_key(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Host": {
                "url": "http://host:1",
                "api_key": "secret",
                "model": "old",
                "models": ["old"],
                "kind": "custom",
            },
        }
        with override_context(app, mock_context):
            keep = client.put(
                "/api/hosts/0",
                json={"configuration_id": "Host", "models": ["new", "fallback"]},
            )
        assert keep.status_code == 200
        assert keep.json()["models"] == ["old", "new", "fallback"]
        assert keep.json()["has_api_key"] is True
        assert "api_key" not in keep.json()
        assert mock_context.settings.known_llm_hosts["Host"]["api_key"] == "secret"

        with override_context(app, mock_context):
            clear = client.put("/api/hosts/0", json={"configuration_id": "Host", "api_key": ""})
        assert clear.status_code == 200
        assert clear.json()["has_api_key"] is False
        assert mock_context.settings.known_llm_hosts["Host"]["api_key"] == ""

    def test_test_refresh_merges_success_and_failure_keeps_stored_models(
        self, client, mock_context
    ):
        mock_context.settings.known_llm_hosts = {
            "Host": {
                "url": "http://host:1",
                "api_key": "",
                "model": "stored",
                "models": ["stored", "saved"],
            },
        }
        mock_context.llm_manager.check_connection.return_value = None
        mock_context.llm_manager._list_available_model_ids.return_value = ["live"]
        with override_context(app, mock_context):
            success = client.post(
                "/api/hosts/0/test",
                json={"configuration_id": "Host", "url": "http://host:1"},
            )
        assert success.status_code == 200
        assert success.json()["models"] == ["live"]
        assert mock_context.settings.known_llm_hosts["Host"]["models"] == [
            "stored",
            "saved",
        ]

        mock_context.llm_manager.check_connection.side_effect = ConnectionError("offline")
        with override_context(app, mock_context):
            failure = client.post(
                "/api/hosts/0/test",
                json={"configuration_id": "Host", "url": "http://host:1"},
            )
        assert failure.status_code == 200
        assert failure.json()["ok"] is False
        assert mock_context.settings.known_llm_hosts["Host"]["models"] == [
            "stored",
            "saved",
        ]

    def test_edit_host_test_does_not_forward_stored_key_to_changed_url(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Host": {
                "url": "http://saved:1",
                "api_key": "stored-secret",
                "model": "stored",
            },
        }
        mock_context.llm_manager.check_connection.return_value = None
        mock_context.llm_manager._list_available_model_ids.return_value = ["draft-model"]

        with override_context(app, mock_context):
            response = client.post(
                "/api/hosts/0/test",
                json={
                    "configuration_id": "Host",
                    "url": "https://draft.example/v1",
                    "api_key": "",
                },
            )

        assert response.status_code == 200
        assert response.json()["models"] == ["draft-model"]
        mock_context.llm_manager.check_connection.assert_called_once_with(
            host="https://draft.example/v1",
            api_key=None,
            timeout=5,
        )
        mock_context.llm_manager._list_available_model_ids.assert_called_once_with(
            host="https://draft.example/v1",
            api_key=None,
            timeout=5,
        )
        assert mock_context.settings.known_llm_hosts["Host"] == {
            "url": "http://saved:1",
            "api_key": "stored-secret",
            "model": "stored",
        }

    def test_edit_host_test_reuses_stored_key_only_for_saved_url(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Host": {
                "url": "https://saved.example/v1",
                "api_key": "stored-secret",
                "model": "stored",
            },
        }
        mock_context.llm_manager.check_connection.return_value = None
        mock_context.llm_manager._list_available_model_ids.return_value = []

        with override_context(app, mock_context):
            response = client.post(
                "/api/hosts/0/test",
                json={
                    "configuration_id": "Host",
                    "url": " https://saved.example/v1 ",
                    "api_key": "",
                },
            )

        assert response.status_code == 200
        mock_context.llm_manager.check_connection.assert_called_once_with(
            host="https://saved.example/v1",
            api_key="stored-secret",
            timeout=5,
        )

    def test_create_host_with_is_favorite_clears_others(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Existing": {"url": "http://a:1", "api_key": "", "model": "m", "is_favorite": True},
        }
        with override_context(app, mock_context):
            resp = client.post(
                "/api/hosts",
                json={
                    "label": "Fav",
                    "url": "http://fav:1",
                    "model": "x",
                    "is_favorite": True,
                },
            )
        assert resp.status_code == 201
        assert resp.json()["is_favorite"] is True
        assert mock_context.settings.known_llm_hosts["Existing"].get("is_favorite") is None
        stored = mock_context.settings.known_llm_hosts["Fav"]
        assert stored["is_favorite"] is True
        assert stored["model"] == stored["models"][0]

    def test_host_crud_cannot_create_another_managed_local_ai_entry(self, client, mock_context):
        with override_context(app, mock_context):
            response = client.post(
                "/api/hosts",
                json={
                    "label": "Not integrated",
                    "url": "http://provider:1",
                    "model": "model",
                    "kind": "local_ai",
                },
            )

        assert response.status_code == 422
        mock_context.settings.save_user_settings.assert_not_called()

    def test_list_hosts_includes_is_favorite_never_api_key(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "A": {"url": "http://a:1", "api_key": "secret", "model": "m"},
            "B": {"url": "http://b:1", "api_key": "", "model": "m", "is_favorite": True},
        }
        with override_context(app, mock_context):
            resp = client.get("/api/hosts")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["is_favorite"] is False
        assert data[1]["is_favorite"] is True
        for host in data:
            assert "api_key" not in host
            assert host["model"] == host["models"][0]

    def test_update_host_is_favorite_clears_others(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "A": {"url": "http://a:1", "api_key": "", "model": "m", "is_favorite": True},
            "B": {"url": "http://b:1", "api_key": "", "model": "m"},
        }
        with override_context(app, mock_context):
            resp = client.put(
                "/api/hosts/1",
                json={"configuration_id": "B", "is_favorite": True},
            )
        assert resp.status_code == 200
        assert resp.json()["is_favorite"] is True
        assert mock_context.settings.known_llm_hosts["A"].get("is_favorite") is None
        assert mock_context.settings.known_llm_hosts["B"]["is_favorite"] is True

    def test_update_host_restores_preference_when_save_fails(self, client, mock_context):
        original = {
            "A": {
                "url": "http://a:1",
                "api_key": "",
                "model": "m",
                "models": ["m"],
                "is_favorite": True,
            },
            "B": {"url": "http://b:1", "api_key": "", "model": "m", "models": ["m"]},
        }
        mock_context.settings.known_llm_hosts = deepcopy(original)
        mock_context.settings.save_user_settings.side_effect = OSError("disk refused")

        with override_context(app, mock_context):
            response = client.put(
                "/api/hosts/1",
                json={"configuration_id": "B", "is_favorite": True},
            )

        assert response.status_code == 500
        assert response.json()["error"] == {
            "code": "host_update_persistence_failed",
            "params": {},
        }
        assert mock_context.settings.known_llm_hosts == original

    def test_reset_managed_local_ai_restores_factory_host(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Lokale KI": {
                "url": "http://127.0.0.1:8080",
                "api_key": "",
                "model": "gemma-4-E4B-it",
                "models": ["gemma-4-E4B-it", "gemma-4-E2B-it", "gemma-4-12B-it"],
                "kind": "local_ai",
                "is_favorite": True,
            },
            "External": {
                "url": "https://provider.example/v1",
                "api_key": "",
                "model": "external-model",
                "is_favorite": True,
            },
        }
        with override_context(app, mock_context):
            response = client.post("/api/hosts/0/reset-managed-local-ai")

        assert response.status_code == 200
        assert "api_key" not in response.json()
        assert mock_context.settings.known_llm_hosts["Lokale KI"] == {
            "url": "http://127.0.0.1:8080",
            "api_key": "",
            "model": "gemma-4-E2B-it",
            "models": ["gemma-4-E2B-it", "gemma-4-E4B-it", "gemma-4-12B-it"],
            "kind": "local_ai",
        }
        assert mock_context.settings.known_llm_hosts["External"]["is_favorite"] is True
        mock_context.settings.save_user_settings.assert_called_once()

    def test_reset_managed_local_ai_refuses_custom_same_label(self, client, mock_context):
        custom_host = {
            "url": "https://custom.example/v1",
            "api_key": "custom-secret",
            "model": "custom-model",
            "models": ["custom-model"],
        }
        mock_context.settings.known_llm_hosts = {"Lokale KI": dict(custom_host)}
        with override_context(app, mock_context):
            response = client.post("/api/hosts/0/reset-managed-local-ai")

        assert response.status_code == 409
        assert mock_context.settings.known_llm_hosts["Lokale KI"] == custom_host
        mock_context.settings.save_user_settings.assert_not_called()

    def test_reset_managed_local_ai_restores_catalog_when_save_fails(self, client, mock_context):
        original = {
            "Lokale KI": {
                "url": "http://127.0.0.1:8080",
                "api_key": "",
                "model": "gemma-4-E4B-it",
                "models": ["gemma-4-E4B-it", "gemma-4-E2B-it", "gemma-4-12B-it"],
                "kind": "local_ai",
            },
            "External": {
                "url": "https://provider.example/v1",
                "api_key": "",
                "model": "external",
            },
        }
        mock_context.settings.known_llm_hosts = deepcopy(original)
        mock_context.settings.save_user_settings.side_effect = OSError("private disk detail")

        with override_context(app, mock_context):
            response = client.post("/api/hosts/0/reset-managed-local-ai")

        assert response.status_code == 500
        assert response.json()["error"] == {
            "code": "host_reset_persistence_failed",
            "params": {},
        }
        assert "private disk detail" not in response.text
        assert mock_context.settings.known_llm_hosts == original

    def test_local_ai_start_preserves_managed_e4b_preference_without_global_favorite(
        self, client, mock_context
    ):
        mock_context.settings.known_llm_hosts = {
            "Lokale KI": {
                "url": "http://127.0.0.1:8080",
                "api_key": "",
                "model": "gemma-4-E4B-it",
                "models": ["gemma-4-E4B-it", "gemma-4-E2B-it", "gemma-4-12B-it"],
                "kind": "local_ai",
                "is_favorite": True,
            },
        }
        manager = MagicMock()
        manager.start.side_effect = [
            LocalAIStatus(
                state="running",
                model_id="gemma-4-e4b",
                model_name="gemma-4-E4B-it",
                host="http://127.0.0.1:8080",
                port=8080,
            ),
            LocalAIStatus(
                state="running",
                model_id="gemma-4-e2b",
                model_name="gemma-4-E2B-it",
                host="http://127.0.0.1:8080",
                port=8080,
            ),
        ]
        app.state.local_ai_manager = manager

        with override_context(app, mock_context):
            first = client.post("/api/local-ai/start", json={"model_id": "gemma-4-e4b"})
            second = client.post("/api/local-ai/start", json={"model_id": "gemma-4-e2b"})

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert mock_context.settings.known_llm_hosts["Lokale KI"] == {
            "url": "http://127.0.0.1:8080",
            "api_key": "",
            "model": "gemma-4-E4B-it",
            "models": ["gemma-4-E4B-it", "gemma-4-E2B-it", "gemma-4-12B-it"],
            "kind": "local_ai",
        }

    def test_local_ai_does_not_overwrite_reserved_non_managed_host(self, client, mock_context):
        mock_context.settings.known_llm_hosts = {
            "Lokale KI": {
                "url": "https://provider.example/v1",
                "api_key": "secret",
                "model": "provider-model",
            },
        }
        manager = MagicMock()
        manager.start.return_value = LocalAIStatus(
            state="running",
            model_id="gemma-4-e2b",
            model_name="gemma-4-E2B-it",
            host="http://127.0.0.1:8080",
            port=8080,
        )
        app.state.local_ai_manager = manager
        with override_context(app, mock_context):
            resp = client.post("/api/local-ai/start", json={"model_id": "gemma-4-e2b"})
        assert resp.status_code == 409
        assert mock_context.settings.known_llm_hosts["Lokale KI"]["api_key"] == "secret"


#
# The typed sessions API has a safe current-schema
# contract that:
#  - Never leaks api_key, absolute paths, or raw internal IDs.
#  - Uses Pydantic DTOs (request rename forbids extra fields).
#  - 404 on unknown id, 422 on unsafe id, 422 on blank title.
#  - Reveal launches the OS file manager without shell interpolation.
class TestSessionsList:
    def test_list_returns_only_canonical_keys(self, client, mock_context):
        mock_context.discussion.list_sessions.return_value = [
            {
                "file_id": "abc-2025-01-01",
                "title": "Diskussion 1",
                "created": "2025-01-01T00:00:00",
                "updated": "2025-01-01T00:00:00",
                "session_type": "exploration",
                "round_count": 2,
                # Unsupported aliases must not leak:
                "filename": "abc-2025-01-01",
                "filepath": "/var/data/abc.json",
                "id": "uuid-1",
            }
        ]
        # Mark the current file_id as the one currently open:
        mock_context.storage = MagicMock()

        mock_context.discussion.current_session_file_id.return_value = "abc-2025-01-01"
        with override_context(app, mock_context):
            resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        item = data[0]
        # Canonical keys present
        for key in (
            "file_id",
            "title",
            "created",
            "updated",
            "session_type",
            "round_count",
            "is_open",
        ):
            assert key in item, f"missing canonical key: {key}"
        assert item["file_id"] == "abc-2025-01-01"
        assert item["title"] == "Diskussion 1"
        assert item["session_type"] == "exploration"
        assert item["round_count"] == 2
        assert item["is_open"] is True
        # Banned keys must not leak
        for banned in ("filepath", "filename", "id", "material", "messages", "api_key", "path"):
            assert banned not in item, f"banned key leaked: {banned}"
        assert "/var/data" not in resp.text

    def test_list_is_open_false_when_not_current(self, client, mock_context):
        mock_context.discussion.list_sessions.return_value = [
            {
                "file_id": "x",
                "title": "T",
                "created": "",
                "updated": "",
                "session_type": "exploration",
                "round_count": 1,
            }
        ]
        mock_context.discussion.current_session_file_id.return_value = None
        with override_context(app, mock_context):
            resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert resp.json()[0]["is_open"] is False

    def test_list_includes_is_favorite_and_still_redacts_banned_keys(self, client, mock_context):
        mock_context.discussion.list_sessions.return_value = [
            {
                "file_id": "abc",
                "title": "Favorisiert",
                "created": "2025-01-01T00:00:00",
                "updated": "2025-02-01T00:00:00",
                "session_type": "critique",
                "round_count": 1,
                "is_favorite": True,
                # Unsupported aliases must not leak:
                "filename": "abc",
                "filepath": "/var/data/abc.json",
                "id": "uuid-1",
            },
            {
                "file_id": "def",
                "title": "Nicht favorisiert",
                "created": "2025-01-02T00:00:00",
                "updated": "2025-02-02T00:00:00",
                "session_type": "exploration",
                "round_count": 0,
                "is_favorite": False,
                "filename": "def",
                "filepath": "/var/data/def.json",
                "id": "uuid-2",
            },
        ]
        mock_context.discussion.current_session_file_id.return_value = None
        with override_context(app, mock_context):
            resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["is_favorite"] is True
        assert data[1]["is_favorite"] is False
        assert data[0]["session_type"] == "critique"
        assert data[1]["session_type"] == "exploration"
        # Banned keys must not leak into the response
        for item in data:
            for banned in (
                "filepath",
                "filename",
                "id",
                "material",
                "messages",
                "api_key",
                "path",
            ):
                assert banned not in item, f"banned key leaked: {banned}"
        # And no raw path appears in the raw text
        assert "/var/data" not in resp.text
        # ``is_open`` is still part of the contract
        assert "is_open" in data[0]
        assert "is_open" in data[1]


class TestSessionOpen:
    def _make_snapshot(self, with_api_key=False):
        # The real service NEVER includes ``api_key``; we optionally
        # Inject a credential to verify the API boundary filters it out.
        agent_payload: dict = {
            "name": "A1",
            "client_id": "c1",
            "prompt_id": "sys_theory",
            "color": "#abc",
            "temperature": 0.7,
            "llm_id": "m",
            "api_host": "http://h",
            "max_tokens": 1024,
            "perspective_number": 1,
        }
        if with_api_key:
            agent_payload["api_key"] = "MUST-NOT-LEAK"
        return {
            "file_id": "abc",
            "title": "Title",
            "material": "Material",
            "initial_question": "Question?",
            "messages": [
                {
                    "id": "m1",
                    "role": "user",
                    "content": "hi",
                    "round_number": 1,
                    "agent_name": None,
                    "theory_label": None,
                    "color": None,
                    "agent_index": None,
                    "perspective_number": None,
                    "note": "",
                    "include_note_in_agent_context": False,
                    "error": None,
                },
                {
                    "id": "m2",
                    "role": "agent",
                    "content": "answer",
                    "round_number": 1,
                    "agent_name": "A1",
                    "theory_label": "TL",
                    "color": "#abc",
                    "agent_index": 0,
                    "perspective_number": 1,
                    "client_id": "c1",
                    "note": "n",
                    "include_note_in_agent_context": False,
                    "error": None,
                },
            ],
            "material_context": {
                "material_type": "document",
                "session_type": "exploration",
                "target_language": "English",
                "input_values": {
                    "research_material_context": "cc",
                    "main_input": "ip",
                    "additional_instructions": "pi",
                },
                "input_definitions": [
                    item.model_dump(mode="json") for item in default_session_inputs()
                ],
                "include_unchanged_research_material_context_in_prompt": True,
            },
            "agents": [agent_payload],
            "synthesis": {"enabled": False, "api_host": None, "llm_id": None, "temperature": None},
            "sequential_mode": True,
            "round_number": 1,
            "has_active_discussion": True,
        }

    def test_open_unknown_returns_404(self, client, mock_context):
        mock_context.discussion.snapshot_open_session.return_value = None
        with override_context(app, mock_context):
            resp = client.post("/api/sessions/nope/open")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Session not found"

    def test_open_unsafe_id_returns_422(self, client, mock_context):
        mock_context.discussion.snapshot_open_session.side_effect = ValueError("unsafe file_id")
        # Note: ``%2F`` (decoded to ``/``) would not match the route
        # segment, so we exercise the unsafe-id path with a value that
        # *will* be URL-routed but still trips the service's
        # ``resolve_file_id`` safety check — a leading dot.
        with override_context(app, mock_context):
            resp = client.post("/api/sessions/.dotdot/open")
        assert resp.status_code == 422
        assert "unsafe" in resp.json()["detail"].lower()

    def test_open_returns_complete_safe_snapshot(self, client, mock_context):
        snapshot = self._make_snapshot()
        mock_context.discussion.snapshot_open_session.return_value = snapshot
        mock_context.settings.save_user_settings.side_effect = OSError("read-only settings")
        with override_context(app, mock_context):
            resp = client.post("/api/sessions/abc/open")
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_id"] == "abc"
        assert data["title"] == "Title"
        assert data["material"] == "Material"
        assert data["initial_question"] == "Question?"
        assert data["sequential_mode"] is True
        assert data["round_number"] == 1
        assert data["has_active_discussion"] is True
        assert mock_context.settings.last_active_discussion_id == "abc"
        mock_context.settings.save_user_settings.assert_called_once_with()
        # Material context
        assert data["material_context"]["material_type"] == "document"
        assert data["material_context"]["input_values"]["research_material_context"] == "cc"
        assert (
            data["material_context"]["include_unchanged_research_material_context_in_prompt"]
            is True
        )
        # Messages with all serializable fields
        assert len(data["messages"]) == 2
        agent_msg = data["messages"][1]
        for k in (
            "id",
            "role",
            "content",
            "round_number",
            "agent_name",
            "theory_label",
            "color",
            "agent_index",
            "note",
            "error",
            "client_id",
        ):
            assert k in agent_msg, f"missing message field: {k}"
        assert agent_msg["agent_name"] == "A1"
        # Agents must NEVER contain api_key
        assert len(data["agents"]) == 1
        assert "api_key" not in data["agents"][0]
        for k in (
            "name",
            "client_id",
            "prompt_id",
            "color",
            "temperature",
            "llm_id",
            "api_host",
            "max_tokens",
        ):
            assert k in data["agents"][0], f"missing agent field: {k}"
        # Banned top-level keys
        for banned in ("path", "filepath", "filename", "id"):
            assert banned not in data, f"banned key leaked: {banned}"

    def test_open_snapshot_carries_safe_client_id(self, client, mock_context):
        snapshot = self._make_snapshot()
        # The fixture already populates ``client_id`` on the agent
        # roster; mirror it on the persisted agent message so the
        # frontend can join on it.
        snapshot["messages"][1]["client_id"] = "c1"
        mock_context.discussion.snapshot_open_session.return_value = snapshot
        with override_context(app, mock_context):
            resp = client.post("/api/sessions/abc/open")
        assert resp.status_code == 200
        data = resp.json()

        # The terminal agent message carries the safe client_id.
        agent_msg = data["messages"][1]
        assert agent_msg["client_id"] == "c1"
        # The user message in the same snapshot is allowed to have
        # ``client_id == null`` (the model is ``Optional[str] = None``);
        # the contract only requires the field to be present, not
        # to carry a non-null value for non-agent messages.
        assert "client_id" in data["messages"][0]
        assert data["messages"][0]["client_id"] is None

        # No credentials or paths leak alongside the new field.
        for banned in ("path", "filepath", "filename", "id", "api_key"):
            assert banned not in data
        assert "api_key" not in data["agents"][0]

    def test_open_preserves_null_agent_temperature_override(self, client, mock_context):
        snapshot = self._make_snapshot()
        snapshot["agents"][0]["temperature"] = None
        mock_context.discussion.snapshot_open_session.return_value = snapshot

        with override_context(app, mock_context):
            resp = client.post("/api/sessions/abc/open")

        assert resp.status_code == 200, resp.text
        assert resp.json()["agents"][0]["temperature"] is None

    def test_open_redacts_api_key_even_if_service_returns_one(self, client, mock_context):
        snapshot = self._make_snapshot(with_api_key=True)
        mock_context.discussion.snapshot_open_session.return_value = snapshot
        with override_context(app, mock_context):
            resp = client.post("/api/sessions/abc/open")
        assert resp.status_code == 200
        body = resp.text
        assert "MUST-NOT-LEAK" not in body
        assert "api_key" not in resp.json()["agents"][0]


class TestSessionPatch:
    def test_patch_renames_returns_summary(self, client, mock_context):
        mock_context.discussion.rename_session.return_value = True
        # Service returns a refreshed summary after rename:
        mock_context.discussion.list_sessions.return_value = [
            {
                "file_id": "abc",
                "title": "New Title",
                "created": "2025-01-01T00:00:00",
                "updated": "2025-02-01T00:00:00",
                "session_type": "critique",
                "round_count": 3,
            }
        ]
        mock_context.discussion.current_session_file_id.return_value = "abc"
        with override_context(app, mock_context):
            resp = client.patch("/api/sessions/abc", json={"title": "  New Title  "})
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_id"] == "abc"
        assert data["title"] == "New Title"
        assert data["session_type"] == "critique"
        assert data["round_count"] == 3
        assert data["is_open"] is True
        # The service must have been called with the *trimmed* title
        mock_context.discussion.rename_session.assert_called_once_with("abc", "New Title")

    def test_patch_blank_title_returns_422(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.patch("/api/sessions/abc", json={"title": "   "})
        assert resp.status_code == 422
        # Service must NOT be called for invalid titles
        mock_context.discussion.rename_session.assert_not_called()

    def test_patch_empty_title_returns_422(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.patch("/api/sessions/abc", json={"title": ""})
        assert resp.status_code == 422
        mock_context.discussion.rename_session.assert_not_called()

    def test_patch_unknown_returns_404(self, client, mock_context):
        mock_context.discussion.rename_session.return_value = False
        with override_context(app, mock_context):
            resp = client.patch("/api/sessions/missing", json={"title": "X"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Session not found"

    def test_patch_unsafe_id_returns_422(self, client, mock_context):
        mock_context.discussion.rename_session.side_effect = ValueError("unsafe file_id")
        with override_context(app, mock_context):
            resp = client.patch("/api/sessions/.unsafe", json={"title": "X"})
        assert resp.status_code == 422

    def test_patch_rejects_extra_fields(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.patch(
                "/api/sessions/abc",
                json={"title": "X", "secret": "leak"},
            )
        assert resp.status_code == 422
        mock_context.discussion.rename_session.assert_not_called()


class TestSessionFavoritePut:
    def test_put_returns_refetched_summary(self, client, mock_context):
        mock_context.discussion.set_session_favorite.return_value = True
        mock_context.discussion.list_sessions.return_value = [
            {
                "file_id": "abc",
                "title": "Title",
                "created": "2025-01-01T00:00:00",
                "updated": "2025-02-01T00:00:00",
                "session_type": "critique",
                "round_count": 3,
                "is_favorite": True,
            }
        ]
        mock_context.discussion.current_session_file_id.return_value = "abc"
        with override_context(app, mock_context):
            resp = client.put("/api/sessions/abc/favorite", json={"is_favorite": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_id"] == "abc"
        assert data["is_favorite"] is True
        assert data["title"] == "Title"
        assert data["session_type"] == "critique"
        assert data["is_open"] is True
        assert data["round_count"] == 3
        # Service must be called with the file_id and the boolean
        mock_context.discussion.set_session_favorite.assert_called_once_with("abc", True)
        # Banned keys must not appear
        for banned in ("filepath", "filename", "id", "material", "messages", "api_key", "path"):
            assert banned not in data, f"banned key leaked: {banned}"

    def test_put_can_unset_favorite(self, client, mock_context):
        mock_context.discussion.set_session_favorite.return_value = True
        mock_context.discussion.list_sessions.return_value = [
            {
                "file_id": "abc",
                "title": "T",
                "created": "2025-01-01T00:00:00",
                "updated": "2025-02-01T00:00:00",
                "session_type": "exploration",
                "round_count": 0,
                "is_favorite": False,
            }
        ]
        mock_context.discussion.current_session_file_id.return_value = None
        with override_context(app, mock_context):
            resp = client.put("/api/sessions/abc/favorite", json={"is_favorite": False})
        assert resp.status_code == 200
        assert resp.json()["is_favorite"] is False
        mock_context.discussion.set_session_favorite.assert_called_once_with("abc", False)

    def test_put_unknown_returns_404(self, client, mock_context):
        mock_context.discussion.set_session_favorite.return_value = False
        with override_context(app, mock_context):
            resp = client.put("/api/sessions/missing/favorite", json={"is_favorite": True})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Session not found"

    def test_put_unsafe_id_returns_422(self, client, mock_context):
        mock_context.discussion.set_session_favorite.side_effect = ValueError("unsafe file_id")
        with override_context(app, mock_context):
            resp = client.put(
                "/api/sessions/.unsafe/favorite",
                json={"is_favorite": True},
            )
        assert resp.status_code == 422

    def test_put_missing_field_returns_422(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.put("/api/sessions/abc/favorite", json={})
        assert resp.status_code == 422
        mock_context.discussion.set_session_favorite.assert_not_called()

    def test_put_wrong_type_returns_422(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.put(
                "/api/sessions/abc/favorite",
                json={"is_favorite": [1, 2]},
            )
        assert resp.status_code == 422
        mock_context.discussion.set_session_favorite.assert_not_called()

    def test_put_rejects_extra_fields(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.put(
                "/api/sessions/abc/favorite",
                json={"is_favorite": True, "secret": "leak"},
            )
        assert resp.status_code == 422
        mock_context.discussion.set_session_favorite.assert_not_called()

    def test_put_rejects_non_json_body(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.put(
                "/api/sessions/abc/favorite",
                content="not json",
                headers={"content-type": "application/json"},
            )
        assert resp.status_code == 422
        mock_context.discussion.set_session_favorite.assert_not_called()


class TestSessionReveal:
    def test_reveal_unknown_returns_404(self, client, mock_context):
        mock_context.discussion.session_path_for_reveal.return_value = None
        with override_context(app, mock_context):
            resp = client.post("/api/sessions/missing/reveal")
        assert resp.status_code == 404

    def test_reveal_unsafe_id_returns_422(self, client, mock_context):
        mock_context.discussion.session_path_for_reveal.side_effect = ValueError("unsafe file_id")
        with override_context(app, mock_context):
            resp = client.post("/api/sessions/.unsafe/reveal")
        assert resp.status_code == 422

    def test_reveal_invokes_subprocess_with_arg_list(self, client, mock_context):
        from pathlib import Path

        mock_context.discussion.session_path_for_reveal.return_value = Path("/tmp/a/abc.json")
        with (
            override_context(app, mock_context),
            patch("src.service.routers.sessions.subprocess.run") as run_mock,
            patch("src.service.routers.sessions.sys") as sys_mock,
        ):
            sys_mock.platform = "darwin"
            resp = client.post("/api/sessions/abc/reveal")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        run_mock.assert_called_once()
        # Must be a list, not a shell string
        args, kwargs = run_mock.call_args
        assert isinstance(args[0], list), "subprocess.run must use argv list"
        assert kwargs.get("shell", False) is False
        # macOS reveal = ['open', '-R', <path>]
        assert args[0][0] == "open"
        assert args[0][1] == "-R"
        assert args[0][2] == "/tmp/a/abc.json"
        assert "timeout" in kwargs

    def test_reveal_response_does_not_leak_path(self, client, mock_context):
        from pathlib import Path

        mock_context.discussion.session_path_for_reveal.return_value = Path("/var/secret/abc.json")
        with (
            override_context(app, mock_context),
            patch("src.service.routers.sessions.subprocess.run"),
            patch("src.service.routers.sessions.sys") as sys_mock,
        ):
            sys_mock.platform = "darwin"
            resp = client.post("/api/sessions/abc/reveal")
        assert resp.status_code == 200
        body = resp.text
        # No raw filesystem path should ever appear in the response
        assert "/var/secret" not in body
        assert "abc.json" not in body
        assert resp.json() == {"status": "ok"}


class TestSessionDelete:
    def test_delete_returns_was_open_flag(self, client, mock_context):
        mock_context.settings.last_active_discussion_id = "abc"
        mock_context.discussion.delete_session.return_value = {
            "deleted": True,
            "deleted_ids": ["abc"],
            "was_active": True,
        }
        with override_context(app, mock_context):
            resp = client.delete("/api/sessions/abc")
        assert resp.status_code == 200
        # was_active from the service maps to was_open in the API.
        assert resp.json() == {
            "deleted": True,
            "deleted_ids": ["abc"],
            "deleted_count": 1,
            "was_open": True,
        }
        assert mock_context.settings.last_active_discussion_id is None
        mock_context.settings.save_user_settings.assert_called_once_with()

    def test_delete_not_active_reports_was_open_false(self, client, mock_context):
        mock_context.discussion.delete_session.return_value = {
            "deleted": True,
            "deleted_ids": ["abc"],
            "was_active": False,
        }
        with override_context(app, mock_context):
            resp = client.delete("/api/sessions/abc")
        assert resp.status_code == 200
        assert resp.json() == {
            "deleted": True,
            "deleted_ids": ["abc"],
            "deleted_count": 1,
            "was_open": False,
        }

    def test_delete_unknown_returns_404(self, client, mock_context):
        mock_context.discussion.delete_session.return_value = {
            "deleted": False,
            "deleted_ids": [],
            "was_active": False,
        }
        with override_context(app, mock_context):
            resp = client.delete("/api/sessions/missing")
        assert resp.status_code == 404

    def test_delete_unsafe_id_returns_422(self, client, mock_context):
        mock_context.discussion.delete_session.side_effect = ValueError("unsafe file_id")
        with override_context(app, mock_context):
            resp = client.delete("/api/sessions/.unsafe")
        assert resp.status_code == 422


class TestSessionBulkDelete:
    @pytest.mark.parametrize("mode", ["all", "except_favorites"])
    def test_bulk_delete_returns_count_and_open_flag(self, client, mock_context, mode):
        mock_context.discussion.delete_sessions.return_value = {
            "deleted_count": 3,
            "deleted_ids": ["a", "b", "c"],
            "was_active": True,
        }
        with override_context(app, mock_context):
            resp = client.post(
                "/api/sessions/bulk-delete",
                json={"mode": mode, "expected_file_ids": ["a", "b", "c"]},
            )

        assert resp.status_code == 200
        assert resp.json() == {
            "deleted_count": 3,
            "deleted_ids": ["a", "b", "c"],
            "was_open": True,
        }
        mock_context.discussion.delete_sessions.assert_called_once_with(mode, ["a", "b", "c"])

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"mode": "favorites_only"},
            {"mode": "all", "expected_file_ids": [], "extra": True},
            {"mode": 1},
        ],
    )
    def test_bulk_delete_rejects_invalid_payloads(self, client, mock_context, payload):
        with override_context(app, mock_context):
            resp = client.post("/api/sessions/bulk-delete", json=payload)

        assert resp.status_code == 422
        mock_context.discussion.delete_sessions.assert_not_called()

    def test_bulk_delete_returns_stable_conflict_before_mutation(self, client, mock_context):
        mock_context.discussion.delete_sessions.side_effect = ValueError("session_catalog_changed")
        with override_context(app, mock_context):
            resp = client.post(
                "/api/sessions/bulk-delete",
                json={"mode": "all", "expected_file_ids": ["opaque-id"]},
            )

        assert resp.status_code == 409
        assert resp.json()["error"] == {"code": "session_catalog_changed", "params": {}}

    def test_committed_bulk_delete_does_not_depend_on_catalogue_refresh(self, client, mock_context):
        mock_context.settings.last_active_discussion_id = "deleted-id"
        mock_context.discussion.delete_sessions.return_value = {
            "deleted_count": 1,
            "deleted_ids": ["deleted-id"],
            "was_active": False,
        }
        mock_context.discussion.list_sessions.side_effect = OSError("injected refresh failure")
        with override_context(app, mock_context):
            resp = client.post(
                "/api/sessions/bulk-delete",
                json={"mode": "all", "expected_file_ids": ["deleted-id"]},
            )

        assert resp.status_code == 200
        assert resp.json()["deleted_ids"] == ["deleted-id"]
        mock_context.discussion.list_sessions.assert_not_called()
        assert mock_context.settings.last_active_discussion_id is None

    def test_bulk_delete_bounds_incomplete_rollback_response(self, client, mock_context):
        mock_context.discussion.delete_sessions.side_effect = SessionDeletionRollbackError(
            ["deleted-id"], ["retained-id"]
        )
        with override_context(app, mock_context):
            resp = client.post(
                "/api/sessions/bulk-delete",
                json={
                    "mode": "all",
                    "expected_file_ids": ["deleted-id", "retained-id"],
                },
            )

        assert resp.status_code == 500
        assert resp.json()["error"] == {
            "code": "session_deletion_inconsistent",
            "params": {
                "deleted_ids": ["deleted-id"],
                "retained_ids": ["retained-id"],
                "deleted_count": 1,
                "retained_count": 1,
                "was_open": False,
            },
        }


class TestRemovedRoutes:
    def test_saved_route_removed(self, client):
        resp = client.get("/api/discussions/saved")
        assert resp.status_code == 404

    def test_load_route_removed(self, client):
        resp = client.post("/api/discussions/load/abc")
        assert resp.status_code == 404


# Discussion roster and per-message context-inclusion mutations.
#
# Strict, extra=forbid PUT surface backed by
# ``DiscussionService.update_current_agents`` and
# ``DiscussionService.set_message_context_inclusion``.
class TestUpdateDiscussionAgentsPut:
    def test_put_accepts_enabled_false(self, client, mock_context):
        captured: dict = {}
        mock_context.discussion.update_current_agents.side_effect = lambda agents: (
            captured.update({"agents": agents}) or True
        )

        with override_context(app, mock_context):
            resp = client.put(
                "/api/discussions/agents",
                json={
                    "agents": [
                        {
                            "name": "A1",
                            "client_id": "agent-1",
                            "prompt_id": "sys_theory",
                            "color": "#000",
                            "enabled": False,
                            "perspective_number": 1,
                        },
                    ],
                },
            )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"agent_count": 1}
        # The single agent was forwarded as ``enabled=False``.
        assert captured["agents"][0].enabled is False

    def test_put_accepts_omitted_enabled(self, client, mock_context):
        captured: dict = {}
        mock_context.discussion.update_current_agents.side_effect = lambda agents: (
            captured.update({"agents": agents}) or True
        )

        with override_context(app, mock_context):
            resp = client.put(
                "/api/discussions/agents",
                json={
                    "agents": [
                        {
                            "name": "A1",
                            "client_id": "agent-1",
                            "prompt_id": "sys_theory",
                            "color": "#000",
                            "perspective_number": 1,
                        },
                        {
                            "name": "A2",
                            "client_id": "agent-2",
                            "prompt_id": "sys_theory",
                            "color": "#111",
                            "enabled": True,
                            "perspective_number": 2,
                        },
                    ],
                },
            )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"agent_count": 2}
        assert [a.enabled for a in captured["agents"]] == [True, True]

    def test_put_forwards_full_roster_in_order(self, client, mock_context):
        captured: dict = {}
        mock_context.discussion.update_current_agents.side_effect = lambda agents: (
            captured.update({"agents": agents}) or True
        )

        names = ["Zeta", "Alpha", "Mike", "Bravo"]
        body = {
            "agents": [
                {
                    "name": name,
                    "client_id": f"agent-{index}",
                    "prompt_id": "sys_theory",
                    "color": "#abc",
                    "perspective_number": index,
                }
                for index, name in enumerate(names, start=1)
            ],
        }

        with override_context(app, mock_context):
            resp = client.put("/api/discussions/agents", json=body)
        assert resp.status_code == 200
        assert resp.json() == {"agent_count": 4}
        forwarded = [a.name for a in captured["agents"]]
        assert forwarded == names

    def test_put_returns_404_when_no_active_discussion(self, client, mock_context):
        mock_context.discussion.update_current_agents.return_value = False
        with override_context(app, mock_context):
            resp = client.put(
                "/api/discussions/agents",
                json={"agents": []},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "No active discussion"

    def test_put_rejects_extra_fields(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.put(
                "/api/discussions/agents",
                json={
                    "agents": [],
                    "secret": "leak",
                },
            )
        assert resp.status_code == 422
        mock_context.discussion.update_current_agents.assert_not_called()

    def test_put_rejects_missing_agents_field(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.put(
                "/api/discussions/agents",
                json={},
            )
        assert resp.status_code == 422
        mock_context.discussion.update_current_agents.assert_not_called()


class TestMessageContextInclusionPut:
    def test_put_accepts_true(self, client, mock_context):
        mock_context.discussion.set_message_context_inclusion.return_value = "updated"
        with override_context(app, mock_context):
            resp = client.put(
                "/api/discussions/messages/abc/context-inclusion",
                json={"include_in_agent_context": True},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True}
        mock_context.discussion.set_message_context_inclusion.assert_called_once_with("abc", True)

    def test_put_accepts_false(self, client, mock_context):
        mock_context.discussion.set_message_context_inclusion.return_value = "updated"
        with override_context(app, mock_context):
            resp = client.put(
                "/api/discussions/messages/abc/context-inclusion",
                json={"include_in_agent_context": False},
            )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        mock_context.discussion.set_message_context_inclusion.assert_called_once_with("abc", False)

    def test_put_returns_404_when_not_found(self, client, mock_context):
        mock_context.discussion.set_message_context_inclusion.return_value = "not_found"
        with override_context(app, mock_context):
            resp = client.put(
                "/api/discussions/messages/missing/context-inclusion",
                json={"include_in_agent_context": False},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Message not found"

    def test_put_returns_409_when_locked(self, client, mock_context):
        mock_context.discussion.set_message_context_inclusion.return_value = "locked"
        with override_context(app, mock_context):
            resp = client.put(
                "/api/discussions/messages/old/context-inclusion",
                json={"include_in_agent_context": False},
            )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        # Preserve the localized HTTP-detail contract.
        assert isinstance(detail, str) and detail.strip()
        # Defence-in-depth: the locked detail must reference the
        # closed-round context so the frontend can render the
        # user-friendly explanation.
        assert "Runde" in detail or "abgeschlossen" in detail

    def test_put_rejects_extra_fields(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.put(
                "/api/discussions/messages/abc/context-inclusion",
                json={
                    "include_in_agent_context": False,
                    "secret": "leak",
                },
            )
        assert resp.status_code == 422
        mock_context.discussion.set_message_context_inclusion.assert_not_called()

    def test_put_rejects_missing_field(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.put(
                "/api/discussions/messages/abc/context-inclusion",
                json={},
            )
        assert resp.status_code == 422
        mock_context.discussion.set_message_context_inclusion.assert_not_called()

    def test_put_rejects_wrong_type(self, client, mock_context):
        with override_context(app, mock_context):
            resp = client.put(
                "/api/discussions/messages/abc/context-inclusion",
                json={"include_in_agent_context": [1, 2]},
            )
        assert resp.status_code == 422
        mock_context.discussion.set_message_context_inclusion.assert_not_called()


# GET /api/discussions/state — must surface include_in_agent_context
class TestGetStateIncludesContextInclusion:
    def _seed(self, mock_context, *, with_excluded: bool):
        state = DiscussionState()
        state.material = "M"
        state.initial_question = "Q?"
        state.round_number = 2
        state.messages = [
            DiscussionMessage(
                id="m1",
                role="user",
                content="kept",
                round_number=1,
            ),
            DiscussionMessage(
                id="m2",
                role="user",
                content="excluded",
                round_number=2,
                include_in_agent_context=not with_excluded,
            ),
        ]
        mock_context.discussion.state = state
        mock_context.discussion.has_active_discussion = True

    def test_get_state_includes_flag_kept(self, client, mock_context):
        self._seed(mock_context, with_excluded=False)
        with override_context(app, mock_context):
            resp = client.get("/api/discussions/state")
        assert resp.status_code == 200
        msgs = resp.json()["messages"]
        by_id = {m["id"]: m for m in msgs}
        assert by_id["m1"]["include_in_agent_context"] is True
        assert by_id["m2"]["include_in_agent_context"] is True

    def test_get_state_includes_flag_excluded(self, client, mock_context):
        self._seed(mock_context, with_excluded=True)
        with override_context(app, mock_context):
            resp = client.get("/api/discussions/state")
        assert resp.status_code == 200
        msgs = resp.json()["messages"]
        by_id = {m["id"]: m for m in msgs}
        assert by_id["m1"]["include_in_agent_context"] is True
        assert by_id["m2"]["include_in_agent_context"] is False


# Current service snapshots must round-trip through the response DTOs
# (OpenSessionResponse / MessageSnapshotModel / AgentSnapshotModel) with
# ``extra=forbid`` while retaining the current ``enabled`` and
# ``include_in_agent_context`` fields.
class TestOpenSessionResponseValidatesRealDtoValues:
    def _real_snapshot(self):
        # Faithfully mirrors ``DiscussionService.snapshot_open_session``:
        # the service actually emits these exact keys, including the
        # booleans we just added to the response DTOs.
        return {
            "file_id": "abc",
            "title": "T",
            "material": "M",
            "initial_question": "Q?",
            "messages": [
                {
                    "id": "m1",
                    "role": "user",
                    "content": "kept",
                    "round_number": 1,
                    "agent_name": None,
                    "theory_label": None,
                    "color": None,
                    "agent_index": None,
                    "perspective_number": None,
                    "note": "",
                    "include_note_in_agent_context": False,
                    "error": None,
                    "include_in_agent_context": True,
                },
                {
                    "id": "m2",
                    "role": "agent",
                    "content": "excluded",
                    "round_number": 1,
                    "agent_name": "A",
                    "theory_label": "T",
                    "color": "#fff",
                    "agent_index": 0,
                    "perspective_number": 1,
                    "client_id": "c-on",
                    "note": "n",
                    "include_note_in_agent_context": False,
                    "error": None,
                    "include_in_agent_context": False,
                },
            ],
            "material_context": {
                "material_type": "document",
                "session_type": "exploration",
                "target_language": "English",
                "input_values": {
                    "research_material_context": "",
                    "main_input": "Q?",
                    "additional_instructions": "",
                },
                "input_definitions": [
                    item.model_dump(mode="json") for item in default_session_inputs()
                ],
                "include_unchanged_research_material_context_in_prompt": False,
            },
            # An agent that has been turned off in the editable
            # roster, with NO api_key leaked.  This is the exact
            # shape emitted by the service and accepted by the response DTOs.
            "agents": [
                {
                    "name": "On",
                    "client_id": "c-on",
                    "prompt_id": "sys_theory",
                    "color": "#000",
                    "temperature": None,
                    "llm_id": None,
                    "api_host": None,
                    "max_tokens": None,
                    "enabled": True,
                    "perspective_number": 1,
                },
                {
                    "name": "Off",
                    "client_id": "c-off",
                    "prompt_id": "sys_theory",
                    "color": "#111",
                    "temperature": 0.7,
                    "llm_id": "m",
                    "api_host": "http://h",
                    "max_tokens": 1024,
                    "enabled": False,
                    "perspective_number": 2,
                },
            ],
            "synthesis": {"enabled": False, "api_host": None, "llm_id": None, "temperature": None},
            "sequential_mode": True,
            "round_number": 1,
            "has_active_discussion": True,
            "round_provider_provenance": [
                {
                    "round_number": 1,
                    "providers": [
                        {
                            "kind": "perspective",
                            "client_id": "c-on",
                            "prompt_id": "sys_theory",
                            "prompt_label": "Systemtheorie",
                            "perspective_number": 1,
                            "temperature": 0.2,
                            "host_configuration_id": "stable-host-id",
                            "host_label": "Visible Host",
                            "api_host": "http://h",
                            "model_id": "m",
                        }
                    ],
                }
            ],
        }

    def test_real_snapshot_round_trips(self, client, mock_context):
        mock_context.discussion.snapshot_open_session.return_value = self._real_snapshot()
        with override_context(app, mock_context):
            resp = client.post("/api/sessions/abc/open")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # Crucial: the disabled agent must survive the round trip
        # *and* the excluded message must keep its flag.
        agents_by_name = {a["name"]: a for a in data["agents"]}
        assert agents_by_name["On"]["enabled"] is True
        assert agents_by_name["Off"]["enabled"] is False
        # No api_key may leak (defence-in-depth).
        assert "api_key" not in agents_by_name["On"]
        assert "api_key" not in agents_by_name["Off"]
        # Message-level inclusion flag survives the round trip.
        msgs_by_id = {m["id"]: m for m in data["messages"]}
        assert msgs_by_id["m1"]["include_in_agent_context"] is True
        assert msgs_by_id["m2"]["include_in_agent_context"] is False
        assert (
            data["round_provider_provenance"][0]["providers"][0]["host_configuration_id"]
            == "stable-host-id"
        )

    def test_real_snapshot_disabled_agent_is_accepted(self, client, mock_context):
        snap = self._real_snapshot()
        assert snap["agents"][1]["enabled"] is False
        mock_context.discussion.snapshot_open_session.return_value = snap
        with override_context(app, mock_context):
            resp = client.post("/api/sessions/abc/open")
        assert resp.status_code == 200, resp.text

    def test_real_snapshot_excluded_message_is_accepted(self, client, mock_context):
        snap = self._real_snapshot()
        assert snap["messages"][1]["include_in_agent_context"] is False
        mock_context.discussion.snapshot_open_session.return_value = snap
        with override_context(app, mock_context):
            resp = client.post("/api/sessions/abc/open")
        assert resp.status_code == 200, resp.text


# AgentConfigModel — accepts omitted ``enabled`` and ``enabled: false``
class TestStartAcceptsEnabledFlag:
    def _capture_agents(self, mock_context):
        captured: dict = {}
        mock_context.discussion.current_session_file_id.return_value = "s"
        mock_context.discussion.current_session_title.return_value = "T"

        def fake_start(**kwargs):
            captured["agents"] = kwargs.get("agents")
            kwargs["on_all_complete"]()

        mock_context.discussion.start_new_discussion = fake_start
        return captured

    def test_start_accepts_omitted_enabled(self, client, mock_context):
        captured = self._capture_agents(mock_context)
        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/start",
                json={
                    "material": "Material",
                    "agents": [
                        {
                            "name": "A1",
                            "client_id": "agent-1",
                            "prompt_id": "sys_theory",
                            "color": "#000",
                            "perspective_number": 1,
                        },
                    ],
                    "title": "",
                    "material_context": {
                        "material_type": "document",
                        "session_type": "exploration",
                        "target_language": "English",
                        "input_values": {
                            "research_material_context": "",
                            "main_input": "Q?",
                            "additional_instructions": "",
                        },
                    },
                    "synthesis": {
                        "enabled": False,
                        "api_host": None,
                        "llm_id": None,
                        "temperature": None,
                    },
                    "sequential_mode": False,
                },
            )
        assert resp.status_code == 200
        assert captured["agents"][0].enabled is True

    def test_start_accepts_enabled_false(self, client, mock_context):
        captured = self._capture_agents(mock_context)
        with override_context(app, mock_context):
            resp = client.post(
                "/api/discussions/start",
                json={
                    "material": "Material",
                    "agents": [
                        {
                            "name": "On",
                            "client_id": "agent-on",
                            "prompt_id": "sys_theory",
                            "color": "#000",
                            "perspective_number": 1,
                        },
                        {
                            "name": "Off",
                            "client_id": "agent-off",
                            "prompt_id": "sys_theory",
                            "color": "#111",
                            "enabled": False,
                            "perspective_number": 2,
                        },
                    ],
                    "title": "",
                    "material_context": {
                        "material_type": "document",
                        "session_type": "exploration",
                        "target_language": "English",
                        "input_values": {
                            "research_material_context": "",
                            "main_input": "Q?",
                            "additional_instructions": "",
                        },
                    },
                    "synthesis": {
                        "enabled": False,
                        "api_host": None,
                        "llm_id": None,
                        "temperature": None,
                    },
                    "sequential_mode": False,
                },
            )
        assert resp.status_code == 200
        assert [a.enabled for a in captured["agents"]] == [True, False]
