"""Focused contracts for the non-participant round synthesis."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from unittest.mock import MagicMock

import pytest

from src.llm.errors import LLMRequestError
from src.prompts.storage import PromptRepository
from src.service.api_schemas import StartDiscussionRequest, UpdateSynthesisRequest
from src.service.discussion import (
    AgentConfig,
    DiscussionService,
    MaterialContext,
    SynthesisConfig,
    TargetLanguageRequiredError,
)
from src.service.discussion_storage import (
    StoredDiscussion,
    StoredMessage,
    StoredRound,
    StoredSynthesisConfig,
)


def _service(tmp_path: Path) -> tuple[DiscussionService, MagicMock]:
    settings = MagicMock()
    settings.prompt_library_path = Path("data/prompts")
    settings.known_llm_hosts = {}
    manager = MagicMock()
    llm = MagicMock()
    llm.host = "https://example.invalid/v1"
    llm.model_name = "synthesis-test"
    llm.count_chat_input_tokens.side_effect = RuntimeError("counting unavailable")
    manager.get_llm.return_value = llm
    service = DiscussionService(
        settings=settings,
        llm_manager=manager,
        prompt_repo=PromptRepository(base_path=Path("data/prompts")),
        storage_dir=tmp_path / "sessions",
    )
    definition = service.session_type_repo.get("exploration")
    assert definition is not None
    service._material_context = MaterialContext(
        material_type="document",
        session_type="exploration",
        target_language="English",
        session_input_values={item.key: "" for item in definition.session_inputs},
        session_inputs=list(definition.session_inputs),
    )
    return service, llm


def test_synthesis_uses_only_current_round_and_never_enters_agent_context(tmp_path: Path):
    service, llm = _service(tmp_path)
    requests: list[dict] = []

    def stream(**kwargs):
        requests.append(kwargs)
        if len(requests) == 1:
            yield "The contribution identifies a practical tension."
        else:
            yield "- **Shared finding:** The round identifies a practical tension."

    llm.generate_stream.side_effect = stream
    service.state.round_number = 1
    service._synthesis_config = SynthesisConfig(
        enabled=True,
        host_configuration_id="Synthesis Test",
        api_host="https://example.invalid/v1",
        llm_id="synthesis-test",
        temperature=None,
    )
    syntheses = []
    service.run_discussion(
        material="SOURCE MATERIAL MUST NEVER REACH THE SYNTHESIS",
        question="What matters in this case?",
        agents=[
            AgentConfig(
                name="Evidence reader",
                prompt_id="precision",
                perspective_number=3,
                api_host="https://example.invalid/v1",
                llm_id="synthesis-test",
            )
        ],
        material_context=MaterialContext(target_language="English"),
        on_synthesis_complete=lambda response: (
            service.state.add_synthesis_response(response),
            syntheses.append(response),
        ),
    )

    assert len(requests) == 2
    synthesis_request = requests[1]
    assert "SOURCE MATERIAL MUST NEVER REACH THE SYNTHESIS" not in synthesis_request["prompt"]
    assert "What matters in this case?" in synthesis_request["prompt"]
    assert "[Perspective 3]" in synthesis_request["prompt"]
    assert "Precision" not in synthesis_request["prompt"]
    assert "Round synthesis" not in requests[0]["system_prompt"]
    assert requests[0]["system_prompt"].count("FINAL RESPONSE LANGUAGE REQUIREMENT") == 1
    assert "FINAL RESPONSE LANGUAGE REQUIREMENT" not in requests[0]["prompt"]
    assert requests[0]["prompt"].endswith(
        "=== CURRENT RESPONSE LANGUAGE REMINDER ===\nWrite all prose in English."
    )
    assert synthesis_request["system_prompt"].count("FINAL RESPONSE LANGUAGE REQUIREMENT") == 1
    assert "FINAL RESPONSE LANGUAGE REQUIREMENT" not in synthesis_request["prompt"]
    assert synthesis_request["prompt"].endswith(
        "=== CURRENT RESPONSE LANGUAGE REMINDER ===\nWrite all prose in English."
    )
    assert synthesis_request["prompt"].count("CURRENT RESPONSE LANGUAGE REMINDER") == 1
    assert synthesis_request["temperature"] is None
    assert syntheses[0].text.startswith("- **Shared finding:**")
    assert service.state.messages[-1].role == "synthesis"
    assert service.state.messages[-1].include_in_agent_context is False
    assert syntheses[0].text not in service.state.get_discussion_for_agents()


def test_system_prompt_uses_stable_perspective_number_after_reordering(tmp_path: Path):
    service, _llm = _service(tmp_path)

    prompt = service.build_system_prompt(
        "precision",
        agent_config=AgentConfig(name="Precision", prompt_id="precision", perspective_number=3),
        agent_index=0,
        total_agents=2,
    )

    assert "You are `Perspective 3`." in (prompt or "")
    assert "of 2" not in (prompt or "")


def test_synthesis_system_prompt_ends_with_language_requirement(tmp_path: Path):
    service, _llm = _service(tmp_path)
    service._material_context = MaterialContext(target_language="German")

    prompt = service.build_synthesis_system_prompt()

    assert "Write all synthesis prose and every category lead-in in German." in prompt
    assert "SHARED_FINDING, DIFFERENCE, QUALIFICATION, or OPEN_QUESTION" in prompt
    assert "do not output their internal IDs" in prompt
    assert prompt.endswith("and do not output their internal IDs.")
    assert "same physical line" in prompt
    assert "Translate the meaning of the selected internal category type" in prompt
    assert "**Shared finding:**" not in prompt
    assert "**Difference:**" not in prompt
    assert "source-specific concepts or terms" not in prompt
    assert "one pair of parentheses" in prompt
    assert "(`Z0002`, `Z0010`) or (`Z0014-Z0016`)" in prompt
    assert "Never write adjacent citation groups" in prompt


def test_synthesis_system_prompt_requires_target_language(tmp_path: Path):
    service, _llm = _service(tmp_path)
    service._material_context = None

    with pytest.raises(TargetLanguageRequiredError):
        service.build_synthesis_system_prompt()


def test_disabled_synthesis_makes_no_second_provider_request(tmp_path: Path):
    service, llm = _service(tmp_path)
    llm.generate_stream.side_effect = lambda **_kwargs: iter(["Contribution"])
    service._synthesis_config = SynthesisConfig(
        enabled=False,
        api_host="https://example.invalid/v1",
        llm_id="synthesis-test",
        temperature=None,
    )
    service.run_discussion(
        material="Material",
        question="Question",
        agents=[
            AgentConfig(
                name="Evidence reader",
                prompt_id="precision",
                api_host="https://example.invalid/v1",
                llm_id="synthesis-test",
            )
        ],
        material_context=MaterialContext(target_language="English"),
    )
    assert llm.generate_stream.call_count == 1


def test_mixed_round_synthesizes_only_successful_nonempty_contributions(tmp_path: Path):
    service, llm = _service(tmp_path)
    service.settings.known_llm_hosts = {
        "Synthesis Test": {
            "url": "https://example.invalid/v1",
            "model": "synthesis-test",
            "models": ["synthesis-test"],
        }
    }
    service._synthesis_config = SynthesisConfig(
        enabled=True,
        host_configuration_id="Synthesis Test",
        api_host="https://example.invalid/v1",
        llm_id="synthesis-test",
    )
    prompts: list[str] = []

    def stream(**kwargs):
        prompts.append(kwargs["prompt"])
        if len(prompts) == 1:
            raise LLMRequestError("HTTP 402: insufficient credits", code="provider_credit_required")
        if len(prompts) == 2:
            yield "Successful contribution"
        else:
            yield "- **Shared finding:** One contribution succeeded."

    llm.generate_stream.side_effect = stream

    responses = service.run_discussion(
        material="Material",
        question="Question",
        agents=[
            AgentConfig(
                name="Failed",
                client_id="failed",
                prompt_id="precision",
                perspective_number=1,
                api_host="https://example.invalid/v1",
                llm_id="synthesis-test",
                host_configuration_id="Synthesis Test",
            ),
            AgentConfig(
                name="Successful",
                client_id="successful",
                prompt_id="precision",
                perspective_number=2,
                api_host="https://example.invalid/v1",
                llm_id="synthesis-test",
                host_configuration_id="Synthesis Test",
            ),
        ],
        material_context=MaterialContext(target_language="English"),
    )

    assert [response.status for response in responses] == ["failed", "completed"]
    assert responses[0].error_code == "provider_credit_required"
    assert responses[0].error_params == {"host": "Synthesis Test"}
    assert len(prompts) == 3
    assert "Successful contribution" in prompts[-1]
    assert "insufficient credits" not in prompts[-1]


def test_all_failed_round_skips_synthesis_provider_request(tmp_path: Path):
    service, llm = _service(tmp_path)
    service._synthesis_config = SynthesisConfig(
        enabled=True,
        api_host="https://example.invalid/v1",
        llm_id="synthesis-test",
    )
    llm.generate_stream.side_effect = LLMRequestError(
        "HTTP 503: provider unavailable", code="provider_unavailable"
    )
    syntheses = []

    responses = service.run_discussion(
        material="Material",
        question="Question",
        agents=[
            AgentConfig(
                name="One",
                client_id="one",
                prompt_id="precision",
                perspective_number=1,
                api_host="https://example.invalid/v1",
                llm_id="synthesis-test",
            ),
            AgentConfig(
                name="Two",
                client_id="two",
                prompt_id="precision",
                perspective_number=2,
                api_host="https://example.invalid/v1",
                llm_id="synthesis-test",
            ),
        ],
        material_context=MaterialContext(target_language="English"),
        on_synthesis_complete=syntheses.append,
    )

    assert [response.status for response in responses] == ["failed", "failed"]
    assert llm.generate_stream.call_count == 2
    assert len(syntheses) == 1
    assert syntheses[0].status == "failed"
    assert syntheses[0].text == ""
    assert syntheses[0].error_code == "synthesis_no_usable_contributions"


def test_whitespace_only_synthesis_is_a_provider_failure(tmp_path: Path):
    service, llm = _service(tmp_path)
    service._synthesis_config = SynthesisConfig(
        enabled=True,
        api_host="https://example.invalid/v1",
        llm_id="synthesis-test",
    )
    llm.generate_stream.side_effect = [iter(["Contribution"]), iter(["  \n"])]
    syntheses = []

    service.run_discussion(
        material="Material",
        question="Question",
        agents=[
            AgentConfig(
                name="One",
                client_id="one",
                prompt_id="precision",
                perspective_number=1,
                api_host="https://example.invalid/v1",
                llm_id="synthesis-test",
            )
        ],
        material_context=MaterialContext(target_language="English"),
        on_synthesis_complete=syntheses.append,
    )

    assert syntheses[0].status == "failed"
    assert syntheses[0].text == "  \n"
    assert syntheses[0].error_code == "provider_empty_response"


def test_synthesis_settings_persist_and_cannot_change_while_running(tmp_path: Path):
    service, _ = _service(tmp_path)
    service._current_stored = service.storage.create_new("Synthesis settings")
    session_file_id = service.current_session_file_id()
    assert session_file_id is not None
    configured = SynthesisConfig(
        enabled=True,
        api_host="https://example.invalid/v1",
        llm_id="synthesis-test",
        temperature=0.0,
    )

    assert service.update_synthesis_config(configured) is True
    assert service.synthesis_config == configured
    assert service._current_stored.synthesis.temperature == 0.0

    assert (
        service.update_synthesis_config_for_session("different-session", configured)
        == "session_mismatch"
    )
    assert service.update_synthesis_config_for_session(session_file_id, configured) == "updated"

    service._generation_running = True
    assert (
        service.update_synthesis_config(
            SynthesisConfig(enabled=False, api_host=None, llm_id=None, temperature=None)
        )
        is False
    )
    assert service.synthesis_config == configured
    assert (
        service.update_synthesis_config_for_session(session_file_id, configured)
        == "generation_active"
    )


def test_partial_synthesis_transport_failure_is_retained(tmp_path: Path):
    service, llm = _service(tmp_path)
    synthesis_config = SynthesisConfig(
        enabled=True,
        api_host="https://example.invalid/v1",
        llm_id="synthesis-test",
    )

    def contribution(**_kwargs):
        yield "Complete contribution"

    def broken_synthesis(**_kwargs):
        yield "- **Shared finding:** Partial synthesis"
        raise LLMRequestError(
            "The provider stream ended before a terminal event.",
            code="provider_stream_incomplete",
        )

    llm.generate_stream.side_effect = [contribution(), broken_synthesis()]
    syntheses = []
    done = Event()
    service.start_new_discussion(
        material="Material",
        question="Question",
        agents=[
            AgentConfig(
                name="One",
                client_id="one",
                prompt_id="precision",
                perspective_number=1,
                api_host="https://example.invalid/v1",
                llm_id="synthesis-test",
            )
        ],
        material_context=MaterialContext(target_language="English"),
        synthesis_config=synthesis_config,
        on_synthesis_complete=syntheses.append,
        on_all_complete=done.set,
    )

    assert done.wait(timeout=5)
    assert llm.generate_stream.call_count == 2
    assert len(syntheses) == 1
    synthesis = syntheses[0]
    assert synthesis.text == "- **Shared finding:** Partial synthesis"
    assert synthesis.is_complete is False
    assert synthesis.status == "failed"
    assert synthesis.error_code == "provider_stream_incomplete"
    assert service.state.round_status == "failed"
    assert service.state.messages[-1].content == "- **Shared finding:** Partial synthesis"
    assert service.state.messages[-1].status == "failed"

    file_id = service.current_session_file_id()
    assert file_id is not None
    stored = service.storage.load(file_id)
    assert stored is not None
    assert stored.rounds[-1].status == "failed"
    stored_synthesis = stored.rounds[-1].messages[-1]
    assert stored_synthesis.role == "synthesis"
    assert stored_synthesis.content == "- **Shared finding:** Partial synthesis"
    assert stored_synthesis.status == "failed"
    assert stored_synthesis.error_code == "provider_stream_incomplete"

    assert service.open_session(file_id) is True
    reopened = service.state.messages[-1]
    assert reopened.role == "synthesis"
    assert reopened.content == "- **Shared finding:** Partial synthesis"
    assert reopened.status == "failed"
    assert reopened.error_code == "provider_stream_incomplete"


def test_start_request_requires_a_complete_synthesis_config():
    with pytest.raises(ValueError, match="synthesis"):
        StartDiscussionRequest.model_validate({"agents": []})

    complete_config = {
        "enabled": True,
        "api_host": None,
        "llm_id": None,
        "temperature": None,
    }
    for missing_field in ("api_host", "llm_id", "temperature"):
        payload = dict(complete_config)
        payload.pop(missing_field)
        with pytest.raises(ValueError, match=missing_field):
            StartDiscussionRequest.model_validate({"agents": [], "synthesis": payload})

    with pytest.raises(ValueError, match="file_id"):
        UpdateSynthesisRequest.model_validate({"synthesis": complete_config})


def test_enabled_synthesis_closes_an_empty_initial_round(tmp_path: Path):
    service, llm = _service(tmp_path)
    completed = []
    service.state.round_number = 1
    service._synthesis_config = SynthesisConfig(
        enabled=True,
        host_configuration_id="Synthesis Test",
        api_host="https://example.invalid/v1",
        llm_id="synthesis-test",
        temperature=None,
    )

    service.run_discussion(
        material="Material",
        question="Question",
        agents=[],
        material_context=MaterialContext(target_language="English"),
        on_synthesis_complete=lambda response: completed.append(response),
    )

    assert llm.generate_stream.call_count == 0
    assert len(completed) == 1
    assert completed[0].round_number == 1
    assert completed[0].error_code == "synthesis_no_usable_contributions"
    assert completed[0].text == ""
    assert completed[0].status == "failed"
    assert completed[0].is_complete is False


def test_enabled_synthesis_closes_an_empty_follow_up_round(tmp_path: Path):
    service, llm = _service(tmp_path)
    service.settings.known_llm_hosts = {
        "Synthesis Test": {
            "url": "https://example.invalid/v1",
            "model": "synthesis-test",
            "models": ["synthesis-test"],
        }
    }
    service._current_stored = service.storage.create_new("Empty follow-up")
    service.state.round_number = 1
    service._material_context = MaterialContext(target_language="English")
    service._synthesis_config = SynthesisConfig(
        enabled=True,
        host_configuration_id="Synthesis Test",
        api_host="https://example.invalid/v1",
        llm_id="synthesis-test",
        temperature=None,
        host_label="Synthesis Test",
    )
    completed = []
    all_complete = Event()

    user_message = service.continue_discussion(
        "What should we check next?",
        agents=[],
        on_synthesis_complete=lambda response: completed.append(response),
        on_all_complete=all_complete.set,
    )

    assert user_message is not None
    assert all_complete.wait(timeout=2)
    assert service.state.round_number == 2
    assert llm.generate_stream.call_count == 0
    assert len(completed) == 1
    assert completed[0].round_number == 2
    assert completed[0].error_code == "synthesis_no_usable_contributions"
    assert completed[0].status == "failed"
    assert service.state.messages[-1].role == "synthesis"
    assert service.state.messages[-1].status == "failed"
    assert service.state.round_status == "failed"
    assert service.state.messages[-1].include_in_agent_context is False


def test_markdown_export_keeps_synthesis_separate_from_agent_headers():
    discussion = StoredDiscussion(
        id="synthesis-export",
        created="2026-07-30T12:00:00",
        updated="2026-07-30T12:00:00",
        title="Synthesis export",
        material="Material",
        initial_question="Question",
        synthesis=StoredSynthesisConfig(True, "host", "model", None),
        rounds=[
            StoredRound(
                round_number=1,
                messages=[
                    StoredMessage("agent", "agent", "Agent contribution", agent_name="Reader"),
                    StoredMessage("synthesis", "synthesis", "- Synthesized contribution"),
                ],
            )
        ],
    )

    exported = discussion.to_markdown("en")
    assert "#### 🎭 Reader" in exported
    assert "#### ✦ Synthesis" in exported
    assert "#### 🎭 None" not in exported
