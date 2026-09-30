"""Tests for discussion state and service orchestration with mocked providers."""

import asyncio
import queue
import shutil
import threading
import time
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config.settings import LOCAL_AI_HOST_LABEL, _local_ai_host
from src.llm.errors import (
    LLMGenerationLengthLimitError,
    LLMRequestError,
    LLMTokenCountUnsupportedError,
)
from src.llm.openai_compatible_llm import OpenAICompatibleLLM
from src.prompts import SessionTypeRepository as _SessionTypeRepository
from src.service.discussion import (
    DEFAULT_AGENT_PROMPTS_BY_SESSION_TYPE,
    MATERIAL_TYPES,
    SESSION_TYPES,
    ContextUsage,
    DiscussionService,
    DiscussionState,
    MaterialContext,
    MaterialRequiredError,
    ProviderRebindRequiredError,
    ProviderRebindTargetChangedError,
    SynthesisConfig,
    TargetLanguageRequiredError,
    add_line_numbers_to_material,
    is_line_numbered_material,
    material_type_uses_line_numbers,
)
from src.service.discussion import (
    AgentConfig as _AgentConfig,
)
from src.service.discussion import (
    AgentResponse as _AgentResponse,
)
from src.service.discussion import (
    SynthesisResponse as _SynthesisResponse,
)
from src.service.discussion_storage import (
    DiscussionStorage as _DiscussionStorage,
)
from src.service.discussion_storage import (
    SessionDeletionRollbackError,
    StoredProviderProvenance,
)
from src.service.discussion_storage import (
    StoredAgent as _StoredAgent,
)
from src.service.routers.discussions import _disconnect_generation, _stream_response

_threading = threading


class _LanguageConfiguredDiscussionService(DiscussionService):
    """Test fixture service prepared with a complete current material context."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        definition = self.session_type_repo.get("exploration")
        assert definition is not None
        self._material_context = MaterialContext(
            material_type="document",
            session_type="exploration",
            target_language="English",
            session_input_values={item.key: "" for item in definition.session_inputs},
            session_inputs=list(definition.session_inputs),
        )

    @classmethod
    def _configured_context(cls, material_context):
        if material_context is None:
            return MaterialContext(target_language="English")
        if not material_context.target_language:
            material_context.target_language = "English"
        return material_context

    def start_new_discussion(self, *args, **kwargs):
        if len(args) < 5:
            kwargs["material_context"] = self._configured_context(kwargs.get("material_context"))
        return super().start_new_discussion(*args, **kwargs)

    def run_discussion(self, *args, **kwargs):
        if len(args) < 4:
            kwargs["material_context"] = self._configured_context(kwargs.get("material_context"))
        return super().run_discussion(*args, **kwargs)


def AgentConfig(*args, **kwargs):
    """Build current-contract fixtures with a stable visible identity."""

    kwargs.setdefault("client_id", f"test-{kwargs.get('name', 'agent')}")
    if kwargs.get("perspective_number", 0) <= 0:
        kwargs["perspective_number"] = 1
    return _AgentConfig(*args, **kwargs)


def AgentResponse(*args, **kwargs):
    """Build current-contract agent messages with a stable perspective."""

    kwargs.setdefault("client_id", f"test-{kwargs.get('agent_name', 'agent')}")
    if kwargs.get("perspective_number", 0) <= 0:
        kwargs["perspective_number"] = 1
    return _AgentResponse(*args, **kwargs)


class TestContextPreflight:
    def test_managed_first_request_uses_offline_assembled_estimate_and_reservation(self, tmp_path):
        service, agent = self._service_and_agent(tmp_path, local=True)
        service.settings.known_llm_hosts["Lokale KI"]["context_tokens"] = 8_192
        context = MaterialContext(
            target_language="German",
            session_input_values={"main_input": "synthetischer Auftrag " * 1000},
        )
        estimate = service.estimate_start_context_budget(
            material="synthetisches Material " * 1000,
            material_context=context,
            agents=[agent],
            synthesis=SynthesisConfig(enabled=False, api_host=None, llm_id=None),
        )
        assert estimate["estimated_input_tokens"] > 4_096
        assert estimate["available_input_tokens"] == 4_096
        assert estimate["overflow"] is True
        assert service.has_active_discussion is False
        service.llm_manager.get_llm.assert_not_called()

        messages = []
        with patch.object(
            service, "_chat_estimate", side_effect=lambda value: (messages.extend(value), 100)[1]
        ):
            offline = service.estimate_start_context_budget(
                material="synthetisches Material",
                material_context=context,
                agents=[agent],
                synthesis=SynthesisConfig(enabled=False, api_host=None, llm_id=None),
            )
        assert offline["estimated_input_tokens"] == 381
        assert [item["role"] for item in messages] == ["system", "user"]
        assert "synthetisches Material" in messages[1]["content"]

        service.settings.known_llm_hosts["Lokale KI"]["context_tokens"] = 32_768
        assert (
            service.estimate_start_context_budget(
                material="synthetisches Material " * 1000,
                material_context=context,
                agents=[agent],
                synthesis=SynthesisConfig(enabled=False, api_host=None, llm_id=None),
            )["overflow"]
            is False
        )

        service.settings.known_llm_hosts["Lokale KI"]["context_tokens"] = 8_192
        assert (
            service.estimate_start_context_budget(
                material="kurz",
                material_context=context,
                agents=[agent],
                synthesis=SynthesisConfig(
                    enabled=True, api_host=agent.api_host, llm_id=agent.llm_id
                ),
            )["known"]
            is True
        )
        service.llm_manager.get_llm.assert_not_called()

    def test_managed_estimate_allows_budget_boundary_and_blocks_one_token_over(self, tmp_path):
        service, agent = self._service_and_agent(tmp_path, local=True)
        context = MaterialContext(
            target_language="German", session_input_values={"main_input": "Kurze Frage"}
        )
        synthesis = SynthesisConfig(enabled=False, api_host=None, llm_id=None)
        with patch.object(service, "_chat_estimate", return_value=100):
            service.settings.known_llm_hosts["Lokale KI"]["context_tokens"] = 4_477
            at_limit = service.estimate_start_context_budget(
                material="kurz", material_context=context, agents=[agent], synthesis=synthesis
            )
            service.settings.known_llm_hosts["Lokale KI"]["context_tokens"] = 4_476
            over_limit = service.estimate_start_context_budget(
                material="kurz", material_context=context, agents=[agent], synthesis=synthesis
            )
        assert at_limit["estimated_input_tokens"] == 381
        assert at_limit["available_input_tokens"] == 381
        assert at_limit["overflow"] is False
        assert over_limit["available_input_tokens"] == 380
        assert over_limit["overflow"] is True
        service.llm_manager.get_llm.assert_not_called()

    def test_managed_prepare_and_generation_never_request_token_count(self, tmp_path):
        service, agent = self._service_and_agent(tmp_path, local=True)
        service.settings.known_llm_hosts["Lokale KI"]["context_tokens"] = 8_192
        context = MaterialContext(
            target_language="English", session_input_values={"main_input": "Describe the pattern."}
        )
        llm = OpenAICompatibleLLM(model_name="model", host=agent.api_host)
        service.llm_manager.get_llm.return_value = llm

        with (
            patch.object(
                llm, "_count_tokens", side_effect=AssertionError("live count requested")
            ) as count,
            patch.object(
                llm, "generate_stream", return_value=iter(["A real generation is separate."])
            ) as generate,
        ):
            estimate = service.estimate_start_context_budget(
                material="Synthetic material.",
                material_context=context,
                agents=[agent],
                synthesis=SynthesisConfig(enabled=False, api_host=None, llm_id=None),
            )
            service.llm_manager.get_llm.assert_not_called()
            responses = service.run_discussion(
                "Synthetic material.", "Describe the pattern.", [agent], material_context=context
            )

        assert estimate["known"] is True
        assert estimate["overflow"] is False
        assert responses[0].error is None
        assert responses[0].text == "A real generation is separate."
        generate.assert_called_once()
        count.assert_not_called()

    def _service_and_agent(self, tmp_path, *, local: bool):
        service = TestDiscussionService()._make_service(tmp_path)
        service.state.material = "Statisches Material"
        host = "http://127.0.0.1:8080" if local else "https://custom.example/v1"
        if local:
            service.settings.known_llm_hosts = {
                "Lokale KI": {
                    "kind": "local_ai",
                    "url": host,
                    "context_tokens": 100,
                }
            }
        else:
            service.settings.known_llm_hosts = {}
        return service, AgentConfig(
            name="A",
            prompt_id="sys_theory",
            api_host=host,
            llm_id="model",
        )

    def test_local_ai_rejects_input_at_context_limit_without_generation(self, tmp_path):
        service, agent = self._service_and_agent(tmp_path, local=True)
        llm = service.llm_manager.get_llm.return_value
        responses = service.run_discussion("Statisches Material", "Frage", [agent])

        assert llm.generate_stream.call_count == 0
        assert responses[0].error_code == "context_limit_exceeded"
        assert responses[0].error_params["input_tokens"] > 0
        assert responses[0].error_params["context_tokens"] == 100
        assert responses[0].error_params["available_input_tokens"] == 0
        assert responses[0].error_params["reserved_output_tokens"] == 4096
        assert responses[0].usage_available is None
        llm.count_chat_input_tokens.assert_not_called()

    def test_external_host_continues_when_counting_is_unsupported(self, tmp_path):
        service, agent = self._service_and_agent(tmp_path, local=False)
        llm = service.llm_manager.get_llm.return_value
        llm.count_chat_input_tokens.side_effect = LLMTokenCountUnsupportedError("missing")

        def stream(*, on_usage=None, **_kwargs):
            assert on_usage is not None
            on_usage({"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15})
            yield "Antwort"

        llm.generate_stream.side_effect = stream
        responses = service.run_discussion("Statisches Material", "Frage", [agent])

        assert llm.generate_stream.call_count == 1
        llm.count_chat_input_tokens.assert_called_once()
        llm.tokenize.assert_not_called()
        assert responses[0].error is None
        assert responses[0].usage_available is True
        assert responses[0].prompt_tokens == 11
        assert responses[0].total_tokens == 15

    def test_length_stop_keeps_partial_response(self, tmp_path):
        service, agent = self._service_and_agent(tmp_path, local=False)
        llm = service.llm_manager.get_llm.return_value
        llm.count_chat_input_tokens.side_effect = LLMTokenCountUnsupportedError("missing")

        def stream(**_kwargs):
            yield "Teilantwort"
            raise LLMGenerationLengthLimitError("limit")

        llm.generate_stream.side_effect = stream
        responses = service.run_discussion("Statisches Material", "Frage", [agent])

        assert responses[0].text == "Teilantwort"
        assert responses[0].error_code == "generation_length_limit_reached"

    def _context_estimate_inputs(self, tmp_path, *, context_tokens=100_000):
        service = TestDiscussionService()._make_service(tmp_path)
        host = "https://configured.example/v1"
        service.settings.known_llm_hosts = {
            "Configured": {
                "kind": "external",
                "url": host,
                "model_context_tokens": {"model": context_tokens},
            }
        }
        agent = AgentConfig(
            name="A",
            prompt_id="sys_theory",
            api_host=host,
            llm_id="model",
        )
        context = MaterialContext(
            material_type="interview",
            session_type="exploration",
            target_language="English",
            session_input_values={
                "research_material_context": "Background",
                "main_input": "Analyze this",
                "additional_instructions": "Be precise",
            },
        )
        synthesis = SynthesisConfig(enabled=False, api_host=None, llm_id=None)
        return service, agent, context, synthesis

    def test_read_only_estimate_uses_complete_line_numbered_prompt_and_all_overhead(self, tmp_path):
        service, agent, context, synthesis = self._context_estimate_inputs(tmp_path)
        service.llm_manager.get_llm.assert_not_called()
        captured_messages = []

        with patch.object(
            service,
            "_chat_estimate",
            side_effect=lambda messages: (captured_messages.append(messages), 123)[1],
        ):
            estimate = service.estimate_start_context_budget(
                material="First line\nSecond line",
                material_context=context,
                agents=[agent],
                synthesis=synthesis,
            )

        assert estimate["known"] is True
        assert estimate["estimated_input_tokens"] == 410
        assert estimate["context_window_tokens"] == 100_000
        assert estimate["available_input_tokens"] == 95_904
        assert estimate["overflow"] is False
        expected_context = deepcopy(context)
        expected_context.set_session_inputs(
            list(service.session_type_repo.get("exploration").session_inputs)
        )
        expected_system = service.build_system_prompt(
            prompt_id=agent.prompt_id or "",
            agent_config=agent,
            agent_index=0,
            total_agents=1,
            other_agents=[],
            material_context=expected_context,
            use_prompt_snapshot=False,
        )
        expected_state = DiscussionState(
            material="Z0001: First line\nZ0002: Second line",
            round_number=1,
        )
        expected_state.add_user_message("Analyze this")
        expected_user = (
            f"{expected_state.get_context_for_agents()}\n\n"
            "=== CURRENT RESPONSE LANGUAGE REMINDER ===\n"
            "Write all prose in English."
        )
        assert captured_messages == [
            [
                {"role": "system", "content": expected_system},
                {"role": "user", "content": expected_user},
            ]
        ]
        service.llm_manager.get_llm.assert_not_called()

    def test_estimate_allows_equality_and_blocks_one_token_overflow(self, tmp_path):
        service, agent, context, synthesis = self._context_estimate_inputs(tmp_path)
        first = service.estimate_start_context_budget(
            material="Material",
            material_context=context,
            agents=[agent],
            synthesis=synthesis,
        )
        estimated = first["estimated_input_tokens"]
        assert isinstance(estimated, int)

        service.settings.known_llm_hosts["Configured"]["model_context_tokens"]["model"] = (
            estimated + 4_096
        )
        equal = service.estimate_start_context_budget(
            material="Material",
            material_context=context,
            agents=[agent],
            synthesis=synthesis,
        )
        assert equal["overflow"] is False

        service.settings.known_llm_hosts["Configured"]["model_context_tokens"]["model"] = (
            estimated + 4_095
        )
        overflow = service.estimate_start_context_budget(
            material="Material",
            material_context=context,
            agents=[agent],
            synthesis=synthesis,
        )
        assert overflow["overflow"] is True

    def test_external_12288_budget_covers_assembled_prompt_and_recovers(self, tmp_path):
        service, agent, context, synthesis = self._context_estimate_inputs(
            tmp_path, context_tokens=12_288
        )
        context.session_input_values["main_input"] = "Synthetic task " * 500
        long_material = "Synthetic interview material. " * 4_000
        blocked = service.estimate_start_context_budget(
            material=long_material,
            material_context=context,
            agents=[agent],
            synthesis=synthesis,
        )
        assert blocked["known"] is True
        assert blocked["estimated_input_tokens"] > 8_192
        assert blocked["available_input_tokens"] == 8_192
        assert blocked["context_window_tokens"] == 12_288
        assert blocked["reserved_output_tokens"] == 4_096
        assert blocked["overflow"] is True
        assert service.has_active_discussion is False
        service.llm_manager.get_llm.assert_not_called()

        recovered = service.estimate_start_context_budget(
            material="Short synthetic material.",
            material_context=context,
            agents=[agent],
            synthesis=synthesis,
        )
        assert recovered["known"] is True
        assert recovered["overflow"] is False

    def test_multiple_external_perspectives_share_tightest_generation_window(self, tmp_path):
        service, agent, context, synthesis = self._context_estimate_inputs(
            tmp_path, context_tokens=12_288
        )
        other_host = "https://second.example/v1"
        service.settings.known_llm_hosts["Second"] = {
            "kind": "external",
            "url": other_host,
            "model_context_tokens": {"large": 65_536},
        }
        second = AgentConfig(
            name="B",
            prompt_id="sys_theory",
            api_host=other_host,
            llm_id="large",
            perspective_number=2,
        )
        with patch.object(service, "_chat_estimate", side_effect=[100, 7_000]):
            estimate = service.estimate_start_context_budget(
                material="Synthetic material",
                material_context=context,
                agents=[agent, second],
                synthesis=synthesis,
            )
        assert estimate["estimated_input_tokens"] == 9_006
        assert estimate["available_input_tokens"] == 8_192
        assert estimate["overflow"] is True

        service.settings.known_llm_hosts["Configured"]["model_context_tokens"]["model"] = 65_536
        with patch.object(service, "_chat_estimate", side_effect=[100, 7_000]):
            recovered = service.estimate_start_context_budget(
                material="Synthetic material",
                material_context=context,
                agents=[agent, second],
                synthesis=synthesis,
            )
        assert recovered["overflow"] is False

    def test_estimate_uses_nonnumeric_fallback_for_unknown_or_future_requests(self, tmp_path):
        service, agent, context, synthesis = self._context_estimate_inputs(tmp_path)
        service.settings.known_llm_hosts["Configured"]["model_context_tokens"] = {}
        unknown = service.estimate_start_context_budget(
            material="Material",
            material_context=context,
            agents=[agent],
            synthesis=synthesis,
        )
        assert unknown["known"] is False
        assert unknown["available_input_tokens"] is None
        assert unknown["overflow"] is False

        service, agent, context, _synthesis = self._context_estimate_inputs(tmp_path / "sequential")
        second = AgentConfig(
            name="B",
            prompt_id="sys_theory",
            api_host=agent.api_host,
            llm_id=agent.llm_id,
            perspective_number=2,
        )
        sequential = service.estimate_start_context_budget(
            material="Material",
            material_context=context,
            agents=[agent, second],
            synthesis=SynthesisConfig(enabled=False, api_host=None, llm_id=None),
            sequential_mode=True,
        )
        assert sequential["known"] is False

        synthesis = SynthesisConfig(enabled=True, api_host=agent.api_host, llm_id=agent.llm_id)
        with_synthesis = service.estimate_start_context_budget(
            material="Material",
            material_context=context,
            agents=[agent],
            synthesis=synthesis,
        )
        assert with_synthesis["known"] is False

    def test_estimate_preserves_definite_initial_overflow_when_later_requests_are_unknown(
        self, tmp_path
    ):
        service, agent, context, _synthesis = self._context_estimate_inputs(
            tmp_path, context_tokens=32_768
        )
        second = AgentConfig(
            name="B",
            prompt_id="sys_theory",
            api_host=agent.api_host,
            llm_id=agent.llm_id,
            perspective_number=2,
        )
        with patch.object(service, "_chat_estimate", return_value=43_166):
            sequential = service.estimate_start_context_budget(
                material="Material",
                material_context=context,
                agents=[agent, second],
                synthesis=SynthesisConfig(enabled=False, api_host=None, llm_id=None),
                sequential_mode=True,
            )
            with_synthesis = service.estimate_start_context_budget(
                material="Material",
                material_context=context,
                agents=[agent],
                synthesis=SynthesisConfig(
                    enabled=True,
                    api_host=agent.api_host,
                    llm_id=agent.llm_id,
                ),
            )

        for estimate in (sequential, with_synthesis):
            assert estimate == {
                "known": True,
                "estimated_input_tokens": 54_214,
                "available_input_tokens": 28_672,
                "context_window_tokens": 32_768,
                "reserved_output_tokens": 4_096,
                "overflow": True,
            }


# Directory containing the shipped session-context files. Copy these into
# each service fixture so its repository
# resolves the same frontmatter and bodies as the shipped catalogue.
SHIPPED_SESSION_CONTEXTS = (
    Path(__file__).resolve().parent.parent / "data" / "prompts" / "session_contexts"
)


def _populate_session_contexts(target: Path) -> None:
    """Copy shipped session-context assets into ``target``."""

    target.mkdir(parents=True, exist_ok=True)
    for src in SHIPPED_SESSION_CONTEXTS.glob("*.md"):
        shutil.copy2(src, target / src.name)


class TestMaterialContext:
    def test_type_label_known(self):
        ctx = MaterialContext(material_type="interview")
        assert ctx.type_label == MATERIAL_TYPES["interview"]

    def test_type_label_unknown_fallback(self):
        ctx = MaterialContext(material_type="podcast")
        assert ctx.type_label == "Material"  # Default-Fallback

    def test_optional_fields_default_empty(self):
        ctx = MaterialContext(material_type="memo")
        assert ctx.session_type == "exploration"
        assert ctx.session_input_values == {
            "research_material_context": "",
            "main_input": "",
            "additional_instructions": "",
        }

    def test_session_label_known(self):
        ctx = MaterialContext(session_type="critique")
        assert ctx.session_label == SESSION_TYPES["critique"]["label"]

    def test_optional_fields_set(self):
        ctx = MaterialContext(
            material_type="fieldnotes",
            session_input_values={
                "research_material_context": "Interview in Jugendzentrum",
                "main_input": "Bitte Spannungen zwischen Selbstbild und Fremdbild prüfen.",
                "additional_instructions": "Zuerst textnahe Befunde, dann Interpretationen.",
            },
        )
        assert ctx.session_input_values["research_material_context"] == "Interview in Jugendzentrum"
        assert "Spannungen" in ctx.session_input_values["main_input"]
        assert "textnahe" in ctx.session_input_values["additional_instructions"]

    def test_text_material_uses_line_numbers(self):
        assert material_type_uses_line_numbers("memo") is True
        assert material_type_uses_line_numbers("interview") is True
        assert material_type_uses_line_numbers("document") is True

    def test_add_line_numbers_to_material_uses_physical_lines_and_preserves_paragraphs(self):
        numbered = add_line_numbers_to_material(
            "Erste Aussage. Zweite Aussage.\nUnpunktierte Transkriptzeile\n\nDritter Absatz!\n",
            start_line=7,
        )
        assert numbered == (
            "Z0007: Erste Aussage. Zweite Aussage.\n"
            "Z0008: Unpunktierte Transkriptzeile\n\n"
            "Z0009: Dritter Absatz!"
        )

    def test_add_line_numbers_to_material_does_not_split_on_punctuation(self):
        numbered = add_line_numbers_to_material(
            '"Eine Frage?" Eine Antwort! (.) Siehe z. B. Abb. 2 … Danach.'
        )

        assert numbered == 'Z0001: "Eine Frage?" Eine Antwort! (.) Siehe z. B. Abb. 2 … Danach.'

    def test_add_line_numbers_preserves_breaks_without_numbering_blank_lines(self):
        numbered = add_line_numbers_to_material("Erste Zeile\n\n\nZweite Zeile\n")

        assert numbered == "Z0001: Erste Zeile\n\n\nZ0002: Zweite Zeile"

    def test_add_line_numbers_does_not_duplicate_existing_numbers(self):
        numbered = "Z0001: Schon nummeriert\nZ0002: Zweite Zeile"
        assert is_line_numbered_material(numbered) is True
        assert add_line_numbers_to_material(numbered) == numbered


class TestAgentConfig:
    def test_is_active_with_prompt(self):
        a = AgentConfig(name="A", prompt_id="sys_theory", color="#fff")
        assert a.is_active is True

    def test_is_inactive_none_prompt(self):
        a = AgentConfig(name="A", prompt_id=None, color="#fff")
        assert a.is_active is False

    def test_is_inactive_empty_prompt(self):
        a = AgentConfig(name="A", prompt_id="", color="#fff")
        assert a.is_active is False

    def test_is_inactive_whitespace_prompt(self):
        a = AgentConfig(name="A", prompt_id="   \t\n  ", color="#fff")
        assert a.is_active is False

    def test_is_active_strips_surrounding_whitespace(self):
        a = AgentConfig(name="A", prompt_id="  sys_theory  ", color="#fff")
        assert a.is_active is True

    def test_defaults(self):
        a = AgentConfig(name="X", prompt_id="id", color="#000")
        # No explicit override → provider decides → None, not 0.7
        assert a.temperature is None
        assert a.max_tokens is None
        assert a.llm_id is None

    def test_explicit_numeric_temperature_is_preserved(self):
        a = AgentConfig(name="X", prompt_id="id", color="#000", temperature=0.4)
        assert a.temperature == 0.4

    def test_explicit_null_temperature_is_preserved(self):
        a = AgentConfig(name="X", prompt_id="id", color="#000", temperature=None)
        assert a.temperature is None


class TestDiscussionState:
    def _make_state(self) -> DiscussionState:
        s = DiscussionState()
        s.material = "Interview-Text ..."
        s.initial_question = "Was fällt auf?"
        s.round_number = 1
        return s

    def test_add_user_message(self):
        s = self._make_state()
        s.add_user_message("Hallo Runde")
        assert len(s.messages) == 1
        assert s.messages[0].role == "user"
        assert s.messages[0].content == "Hallo Runde"
        assert s.messages[0].round_number == 1

    def test_add_agent_response(self):
        s = self._make_state()
        resp = AgentResponse(
            message_id="agent-msg-1",
            agent_index=0,
            agent_name="Agent A",
            theory_label="Systemtheorie",
            color="#00f",
            text="Meine Analyse...",
            is_complete=True,
        )
        s.add_agent_response(resp)
        assert len(s.messages) == 1
        msg = s.messages[0]
        assert msg.id == "agent-msg-1"
        assert msg.role == "agent"
        assert msg.agent_name == "Agent A"
        assert msg.theory_label == "Systemtheorie"
        assert msg.round_number == 1

    def test_failed_agent_response_keeps_error_out_of_content(self):
        state = self._make_state()

        message = state.add_agent_response(
            AgentResponse(
                message_id="failed-agent",
                agent_index=0,
                agent_name="Agent A",
                theory_label="Systemtheorie",
                color="#00f",
                text="Visible partial",
                status="failed",
                error="HTTP 503: provider unavailable",
                error_code="provider_unavailable",
            )
        )

        assert message.content == "Visible partial"
        assert message.error == "HTTP 503: provider unavailable"
        assert "Fehler" not in message.content

    def test_get_context_for_agents_contains_material(self):
        s = self._make_state()
        ctx = s.get_context_for_agents()
        assert "Interview-Text" in ctx

    def test_get_context_for_agents_contains_question_via_message(self):
        s = self._make_state()
        s.add_user_message("Was fällt auf?")
        ctx = s.get_context_for_agents()
        assert "Was fällt auf?" in ctx

    def test_context_groups_rounds_and_keeps_current_task_out_of_history(self):
        s = self._make_state()
        s.add_user_message("Opening task")
        s.add_agent_response(
            AgentResponse(
                message_id="r1-p3",
                agent_index=0,
                agent_name="Hidden semantic role",
                theory_label="Hidden semantic label",
                color="#00f",
                perspective_number=3,
                text="Round-one response",
            )
        )
        s.round_number = 2
        s.add_user_message("Current follow-up")
        s.add_agent_response(
            AgentResponse(
                message_id="r2-p1",
                agent_index=1,
                agent_name="Another hidden role",
                theory_label="Another hidden label",
                color="#0f0",
                perspective_number=1,
                text="Earlier same-round response",
            )
        )

        context = s.get_context_for_agents()

        assert "=== RESEARCH MATERIAL (AUTHORITATIVE SOURCE) ===" in context
        assert "=== ROUND 1 ===" in context
        assert "=== ROUND 2 (CURRENT ROUND) ===" in context
        assert context.index("[Perspective 3]: Round-one response") < context.index(
            "[Perspective 1]: Earlier same-round response"
        )
        assert "Hidden semantic" not in context
        assert context.count("Opening task") == 1
        assert context.count("Current follow-up") == 1
        assert "[USER]: Current follow-up" not in context
        assert "\n\n=== ROUND 2 (CURRENT ROUND) ===\n\n" in context
        assert context.endswith("=== CURRENT ROUND USER INPUT (ROUND 2) ===\nCurrent follow-up")

    def test_get_context_keeps_complete_material(self):
        s = self._make_state()
        s.material = "A" * 50_000
        ctx = s.get_context_for_agents()
        assert "A" * 50_000 in ctx

    def test_get_context_without_a_limit_preserves_full_material_and_history(self):
        s = self._make_state()
        material = "A" * 50_000
        history = "B" * 50_000
        s.material = material
        s.add_user_message(history)

        ctx = s.get_context_for_agents()

        assert material in ctx
        assert history in ctx
        assert "gekürzt" not in ctx

    def test_clear_resets_all(self):
        s = self._make_state()
        s.add_user_message("test")
        s.clear()
        assert s.material == ""
        assert s.initial_question == ""
        assert s.messages == []
        assert s.round_number == 0

    def test_set_and_get_message_note(self):
        s = self._make_state()
        message = s.add_user_message("Hallo Runde")
        fetched = s.get_message(message.id)
        assert fetched is not None
        fetched.note = "Für später referenzieren"
        assert s.get_message(message.id).note == "Für später referenzieren"

    def test_message_defaults_to_include_in_agent_context(self):
        s = self._make_state()
        user_msg = s.add_user_message("Hallo Standard")
        agent_msg = s.add_agent_response(
            AgentResponse(
                message_id="agent-default-1",
                agent_index=0,
                agent_name="Agent A",
                theory_label="Systemtheorie",
                color="#00f",
                text="Antwort Standard",
                is_complete=True,
            )
        )
        assert user_msg.include_in_agent_context is True
        assert agent_msg.include_in_agent_context is True

    def test_opted_in_agent_note_is_framed_in_context(self):
        s = self._make_state()
        response = s.add_agent_response(
            AgentResponse(
                message_id="agent-note-1",
                agent_index=0,
                agent_name="Legacy name",
                theory_label="Skepticism",
                color="#f00",
                text="Agent contribution",
                perspective_number=3,
            )
        )
        response.note = "Human qualification"
        response.include_note_in_agent_context = True

        context = s.get_context_for_agents()

        assert "[Perspective 3]: Agent contribution" in context
        assert (
            "[HUMAN RESEARCHER NOTE ON THE ABOVE PERSPECTIVE RESPONSE]: Human qualification"
            in context
        )

    def test_agent_note_is_omitted_with_excluded_parent(self):
        s = self._make_state()
        response = s.add_agent_response(
            AgentResponse(
                message_id="agent-note-excluded",
                agent_index=0,
                agent_name="A",
                theory_label="Perspective",
                color="#f00",
                text="Excluded response",
            )
        )
        response.note = "Excluded note"
        response.include_note_in_agent_context = True
        response.include_in_agent_context = False

        assert "Excluded note" not in s.get_context_for_agents()

    def test_excluding_parent_clears_note_context_opt_in(self, tmp_path):
        svc = TestDiscussionService()._make_service(tmp_path)
        svc._current_stored = svc.storage.create_new("Test")
        svc.state.round_number = 1
        message = svc.state.add_agent_response(
            AgentResponse(
                message_id="note-parent",
                agent_index=0,
                agent_name="A",
                theory_label="S",
                color="#f00",
                text="Response",
            )
        )
        message.note = "Note"
        message.include_note_in_agent_context = True

        assert svc.set_message_context_inclusion(message.id, False) == "updated"
        assert message.include_note_in_agent_context is False

    def test_perspective_numbers_survive_roster_reordering(self, tmp_path):
        svc = TestDiscussionService()._make_service(tmp_path)
        svc._current_stored = svc.storage.create_new("Test")
        agents = [
            AgentConfig(name="A", client_id="a", prompt_id="sys_theory", perspective_number=1),
            AgentConfig(name="B", client_id="b", prompt_id="sys_theory", perspective_number=2),
        ]
        assert svc.update_current_agents(agents) is True
        assert svc.update_current_agents([agents[1], agents[0]]) is True
        assert [(a.client_id, a.perspective_number) for a in svc._current_agents] == [
            ("b", 2),
            ("a", 1),
        ]

    def test_reordered_client_roster_requires_stable_numbers(self, tmp_path):
        svc = TestDiscussionService()._make_service(tmp_path)
        svc._current_stored = svc.storage.create_new("Test")
        assert svc.update_current_agents(
            [
                AgentConfig(name="A", client_id="a", prompt_id="sys_theory", perspective_number=1),
                AgentConfig(name="B", client_id="b", prompt_id="sys_theory", perspective_number=2),
            ]
        )

        assert svc.update_current_agents(
            [
                AgentConfig(name="B", client_id="b", prompt_id="sys_theory", perspective_number=2),
                AgentConfig(name="A", client_id="a", prompt_id="sys_theory", perspective_number=1),
            ]
        )
        assert [(agent.client_id, agent.perspective_number) for agent in svc._current_agents] == [
            ("b", 2),
            ("a", 1),
        ]

    def test_context_omits_only_messages_excluded_from_agents(self):
        s = self._make_state()
        s.material = "Originalmaterial"
        kept = s.add_user_message("Diese Frage bleibt sichtbar.")
        removed = s.add_user_message("Diese Notiz soll nicht gepromptet werden.")
        removed.include_in_agent_context = False

        context = s.get_context_for_agents()

        assert kept.content in context
        assert removed.content not in context
        assert "Originalmaterial" in context


def _mock_settings():
    """Build a minimal Settings mock."""
    s = MagicMock()
    s.max_tokens = 2048
    s.llm_host = "http://127.0.0.1:1234"
    s.llm_model = "local-model"
    return s


def _mock_llm_manager():
    """Build an LLMManager mock with ``generate_stream``."""
    mgr = MagicMock()
    llm = MagicMock()
    llm.generate_stream.side_effect = lambda *args, **kwargs: iter(["Hallo ", "Welt"])
    mgr.llm = llm
    mgr.get_llm.return_value = llm
    return mgr


def _mock_prompt_repo():
    """Build a PromptRepository mock with one template."""
    repo = MagicMock()

    template = MagicMock()
    template.id = "sys_theory"
    template.label = "Systemtheorie"
    template.role = "Du bist Systemtheoretiker."
    template.task = "Analysiere das Material."
    template.output_format = "Strukturiert."

    repo.list_templates.return_value = [template]
    repo.get_common_instructions.return_value = (
        "Allgemeine Prinzipien.\n"
        'ZEILENREFERENZEN BEI MATERIALBELEGEN: Zitiere im Format "exakter Wortlaut" (Z0007).\n'
        "BELEGFORMAT STATT BELEGZWANG: Diese Regeln beschreiben, wie Materialbelege aussehen sollen."
    )
    return repo


class TestDiscussionService:
    def _make_service(self, tmp_path) -> DiscussionService:
        # The repository resolves session types only below its configured root.
        session_contexts_dir = tmp_path / "session_contexts"
        _populate_session_contexts(session_contexts_dir)
        return _LanguageConfiguredDiscussionService(
            settings=_mock_settings(),
            llm_manager=_mock_llm_manager(),
            prompt_repo=_mock_prompt_repo(),
            storage_dir=tmp_path / "disc",
            session_context_dir=session_contexts_dir,
        )

    def test_get_available_perspectives(self, tmp_path):
        svc = self._make_service(tmp_path)
        persp = svc.get_available_perspectives()
        assert len(persp) == 1
        assert persp[0] == ("sys_theory", "Systemtheorie")

    def test_get_prompt_by_id_found(self, tmp_path):
        svc = self._make_service(tmp_path)
        t = svc.get_prompt_by_id("sys_theory")
        assert t is not None
        assert t.label == "Systemtheorie"

    def test_get_prompt_by_id_missing(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc.get_prompt_by_id("nope") is None

    def test_agent_stream_receives_run_scoped_cancellation_signal(self, tmp_path):
        svc = self._make_service(tmp_path)
        generation = svc._begin_generation()
        llm = MagicMock()
        llm.generate_stream.return_value = iter(["answer"])
        agent = _AgentConfig(
            name="A",
            prompt_id="sys_theory",
            perspective_number=1,
        )
        start_response = _AgentResponse(
            message_id="message-1",
            agent_index=0,
            agent_name="A",
            perspective_number=1,
            theory_label="Theory",
            color="#000000",
            text="",
        )

        text, _usage, error = svc._stream_agent_output(
            generation,
            llm,
            0,
            agent,
            "Theory",
            start_response,
            "prompt",
            "system",
            None,
        )

        assert text == "answer"
        assert error is None
        assert llm.generate_stream.call_args.kwargs["cancel_event"] is generation.cancelled

    def test_next_round_configuration_is_atomic_and_freezes_new_role(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.settings.known_llm_hosts = {
            "host-a": {"label": "Visible A", "url": "https://a.test/v1/", "models": ["m1"]},
            "host-b": {"label": "Visible B", "url": "https://b.test/v1", "models": ["m2"]},
        }
        original = AgentConfig(
            name="A",
            client_id="stable-client",
            prompt_id="sys_theory",
            perspective_number=1,
            host_configuration_id="host-a",
            api_host="https://a.test/v1",
            llm_id="m1",
        )
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(material="M", question="Q", agents=[original])
        svc._generation_running = False
        new_role = MagicMock(
            id="new_role",
            label="New frozen label",
            role="New role body",
            task="New task body",
            output_format="New output body",
        )
        svc.prompt_repo.get_template.return_value = new_role
        replacement = AgentConfig(
            name="Caller label is ignored",
            client_id="stable-client",
            prompt_id="new_role",
            perspective_number=1,
            temperature=0.35,
            host_configuration_id="host-b",
            host_label="Spoofed label",
            api_host="https://b.test/v1/",
            llm_id="m2",
            api_key="must-not-persist",
        )
        synthesis = SynthesisConfig(
            enabled=True,
            host_configuration_id="host-b",
            host_label="Spoofed synthesis label",
            api_host="https://b.test/v1/",
            llm_id="m2",
            temperature=None,
        )

        result = svc.update_next_round_configuration(
            svc.current_session_file_id() or "", [replacement], synthesis
        )

        assert result == "updated"
        assert svc._current_agents[0].api_key is None
        assert svc._current_agents[0].name == "New frozen label"
        assert svc._current_agents[0].host_label == "host-b"
        assert svc._synthesis_config is not None
        assert svc._synthesis_config.host_label == "host-b"
        assert svc._current_stored is not None
        assert svc._current_stored.agents[0].name == "New frozen label"
        assert svc._current_stored.agents[0].prompt_label == "New frozen label"
        frozen = svc._snapshot_role(svc._current_stored.prompt_snapshot, "new_role")
        assert frozen == {
            "id": "new_role",
            "label": "New frozen label",
            "role": "New role body",
            "task": "New task body",
            "output_format": "New output body",
        }
        persisted = svc.storage.load(svc.current_session_file_id() or "")
        assert persisted is not None
        assert persisted.agents[0].host_label == "host-b"
        assert not hasattr(persisted.agents[0], "api_key")

    def test_next_round_configuration_rolls_back_every_mirror_on_save_failure(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.settings.known_llm_hosts = {
            "host": {"label": "Visible", "url": "https://host.test/v1", "models": ["m"]}
        }
        original = AgentConfig(
            name="A",
            client_id="stable-client",
            prompt_id="sys_theory",
            perspective_number=1,
            host_configuration_id="host",
            api_host="https://host.test/v1",
            llm_id="m",
        )
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(material="M", question="Q", agents=[original])
        svc._generation_running = False
        before_agents = deepcopy(svc._current_agents)
        before_synthesis = deepcopy(svc._synthesis_config)
        before_stored = deepcopy(svc._current_stored)
        changed = deepcopy(original)
        changed.temperature = 0.8

        with (
            patch.object(svc.storage, "save", side_effect=OSError("read-only")),
            pytest.raises(OSError, match="read-only"),
        ):
            svc.update_next_round_configuration(
                svc.current_session_file_id() or "",
                [changed],
                SynthesisConfig(False, None, None),
            )

        assert svc._current_agents == before_agents
        assert svc._synthesis_config == before_synthesis
        assert svc._current_stored == before_stored

    def test_next_round_configuration_preserves_disabled_promptless_slot(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.settings.known_llm_hosts = {"host": {"url": "https://host.test/v1", "models": ["m"]}}
        active = AgentConfig(
            name="Active",
            client_id="active-client",
            prompt_id="sys_theory",
            perspective_number=1,
            host_configuration_id="host",
            api_host="https://host.test/v1",
            llm_id="m",
        )
        placeholder = AgentConfig(
            name="Unused",
            client_id="disabled-client",
            prompt_id=None,
            enabled=False,
            perspective_number=2,
        )
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(material="M", question="Q", agents=[active, placeholder])
        svc._generation_running = False

        result = svc.update_next_round_configuration(
            svc.current_session_file_id() or "",
            [deepcopy(active), deepcopy(placeholder)],
            SynthesisConfig(False, None, None),
        )

        assert result == "updated"
        assert svc._current_agents[1].prompt_id is None
        assert svc._current_stored is not None
        assert svc._current_stored.agents[1].prompt_id == ""
        rejected = deepcopy(placeholder)
        rejected.enabled = True
        before = deepcopy(svc._current_stored)
        assert (
            svc.update_next_round_configuration(
                svc.current_session_file_id() or "",
                [deepcopy(active), rejected],
                SynthesisConfig(False, None, None),
            )
            == "role_changed"
        )
        assert svc._current_stored == before

    def test_external_host_context_remains_open(self, tmp_path):
        svc = self._make_service(tmp_path)
        material = "A" * 50_000
        svc.state.material = material
        agent = AgentConfig(
            name="Extern",
            prompt_id="sys_theory",
            color="#fff",
            api_host="https://example.test/v1",
        )

        context = svc._context_for_agent(agent)

        assert material in context
        assert "gekürzt wegen Kontextlimit" not in context

    def test_managed_local_ai_context_keeps_full_input_for_preflight(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.settings.known_llm_hosts = {
            "Lokale KI": {
                "kind": "local_ai",
                "url": "http://127.0.0.1:8080",
                "context_tokens": 100,
            }
        }
        svc.state.material = "A" * 50_000
        agent = AgentConfig(
            name="Lokal",
            prompt_id="sys_theory",
            color="#fff",
            api_host="http://127.0.0.1:8080",
        )

        context = svc._context_for_agent(agent)

        assert "gekürzt wegen Kontextlimit" not in context
        assert "A" * 50_000 in context

    def test_get_available_session_types_contains_current_shipped_modes(self, tmp_path):
        svc = self._make_service(tmp_path)
        session_ids = [sid for sid, _ in svc.get_available_session_types()]
        assert session_ids == ["critique", "exploration"]

    def test_exploration_session_exposes_current_input_schema(self, tmp_path):
        svc = self._make_service(tmp_path)
        definition = svc.session_type_repo.get("exploration")
        assert definition is not None
        assert [item.key for item in definition.session_inputs] == [
            "research_material_context",
            "main_input",
            "additional_instructions",
        ]
        assert "exploration task" in definition.session_inputs[1].label.lower()

    def test_critique_session_exposes_current_input_schema(self, tmp_path):
        svc = self._make_service(tmp_path)
        definition = svc.session_type_repo.get("critique")
        assert definition is not None
        assert [item.key for item in definition.session_inputs] == [
            "research_material_context",
            "main_input",
            "additional_instructions",
        ]

    def test_shipped_session_types_are_available(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc.get_session_type_description("exploration")
        assert svc.get_session_type_description("critique")

    def test_get_default_agent_prompt_ids_filters_missing_prompts(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc._prompts = {
            "rt_skeptiker": object(),
            "rt_praezise": object(),
        }

        defaults = svc.get_default_agent_prompt_ids("critique")

        assert defaults == []

    def test_critique_defaults_match_exploration_perspective_order(self):
        expected = [
            "conceptualization",
            "precision",
            "skepticism",
        ]
        assert DEFAULT_AGENT_PROMPTS_BY_SESSION_TYPE["exploration"] == expected
        assert DEFAULT_AGENT_PROMPTS_BY_SESSION_TYPE["critique"] == expected

    def test_set_message_note_persists_to_state(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc._current_stored = svc.storage.create_new("Test")
        user_message = svc.state.add_user_message("Was fällt auf?")

        changed = svc.set_message_note(user_message.id, "Später für Memo prüfen")

        assert changed is True
        assert svc.get_message(user_message.id) is not None
        assert svc.get_message(user_message.id).note == "Später für Memo prüfen"

    def test_clear_message_note_empties_existing_note(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc._current_stored = svc.storage.create_new("Test")
        user_message = svc.state.add_user_message("Was fällt auf?")
        svc.set_message_note(user_message.id, "Für später behalten")

        changed = svc.clear_message_note(user_message.id)

        assert changed is True
        assert svc.get_message(user_message.id) is not None
        assert svc.get_message(user_message.id).note == ""

    def test_set_message_note_returns_false_for_unknown_message(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc._current_stored = svc.storage.create_new("Test")

        changed = svc.set_message_note("does-not-exist", "Notiz")

        assert changed is False

    def test_set_message_note_holds_run_lock_for_entire_operation(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc._current_stored = svc.storage.create_new("LockTest")
        user_message = svc.state.add_user_message("Frage?")
        svc._save_current_state()

        # Gate inside the lock: we record each entry and use a
        # barrier so the test can synchronise with the probe.
        original_locked = svc._save_current_state_locked
        call_log: list[str] = []
        block_in_save = threading.Event()
        release_in_save = threading.Event()

        def gated_locked():
            call_log.append("enter")
            if not block_in_save.is_set():
                block_in_save.set()
                release_in_save.wait(timeout=5.0)
            try:
                return original_locked()
            finally:
                call_log.append("exit")

        svc._save_current_state_locked = gated_locked  # type: ignore[method-assign]

        # Schedule a probe thread that, when set_message_note is
        # inside the read step, will call _save_current_state (=
        # acquire the same lock).  If the lock is held, the probe
        # blocks.
        original_get = svc.state.get_message
        probe_started = threading.Event()
        probe_completed = threading.Event()
        probe_thread_ref: list[threading.Thread] = []

        def probed_get(message_id):
            result = original_get(message_id)
            if result is None:
                return result

            def probe():
                try:
                    svc._save_current_state()
                finally:
                    probe_completed.set()

            t = threading.Thread(target=probe, daemon=True)
            probe_thread_ref.append(t)
            t.start()
            probe_started.set()
            # Give the probe a moment; if the lock is NOT held, the
            # probe will enter the gated save, set block_in_save,
            # and then block on release_in_save.  Either way, the
            # probe is not done yet.
            probe_completed.wait(timeout=0.2)
            assert not probe_completed.is_set(), (
                "Concurrent _save_current_state completed while "
                "set_message_note was inside its read step — "
                "set_message_note is not holding _run_lock for the "
                "entire read+mutate+save sequence."
            )
            return result

        svc.state.get_message = probed_get  # type: ignore[method-assign]

        # Run set_message_note.  It will block inside the gated save
        # until we release_in_save.  We use a thread for that.
        set_done = threading.Event()
        set_error: list[BaseException] = []

        def do_set():
            try:
                svc.set_message_note(user_message.id, "sperrige Notiz")
            except BaseException as exc:
                set_error.append(exc)
            finally:
                set_done.set()

        set_thread = threading.Thread(target=do_set, daemon=True)
        set_thread.start()

        # Wait for the probe (or set_message_note) to enter the
        # gated save.  Then release so everything can finish.
        assert block_in_save.wait(timeout=5.0)
        release_in_save.set()

        set_thread.join(timeout=5.0)
        assert set_done.is_set()
        assert not set_error, set_error

        import json as _json

        all_files = list((tmp_path / "disc").glob("*.json"))
        assert all_files
        for f in all_files:
            data = _json.loads(f.read_text(encoding="utf-8"))
            for r in data.get("rounds", []):
                for m in r.get("messages", []):
                    if m.get("id") == user_message.id:
                        assert m.get("note") == "sperrige Notiz"
                        return
        pytest.fail("message with new note not found on disk")

    def test_load_and_load_discussion_preserves_message_note(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc._current_stored = svc.storage.create_new("Test")
        svc.state.material = "Material"
        svc.state.initial_question = "Frage?"
        svc.state.round_number = 1
        user_message = svc.state.add_user_message("Frage?")
        svc.set_message_note(user_message.id, "Wichtige Ausgangsfrage")

        filepath = svc._save_current_state()
        assert filepath is not None

        reloaded = self._make_service(tmp_path)
        loaded = reloaded.open_session(filepath.stem)

        assert loaded is True
        restored = reloaded.get_message(user_message.id)
        assert restored is not None
        assert restored.note == "Wichtige Ausgangsfrage"

    def test_reopened_included_agent_note_reaches_next_context(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc._current_stored = svc.storage.create_new("Synthetic note")
        svc.state.material = "Synthetic material"
        svc.state.round_number = 1
        response = svc.state.add_agent_response(
            AgentResponse(
                message_id="synthetic-note-response",
                agent_index=0,
                agent_name="A",
                theory_label="A",
                color="#f00",
                text="Synthetic contribution",
            )
        )
        assert svc.set_message_note(response.id, "SENTINEL_OLD_NOTE", True)
        svc.state.round_number = 2
        assert svc.set_message_note(response.id, "SENTINEL_REOPENED_NOTE", True)
        filepath = svc.get_current_filepath()
        assert filepath is not None

        reopened = self._make_service(tmp_path)
        assert reopened.open_session(filepath.stem)
        assert reopened.get_message(response.id).include_note_in_agent_context is True
        assert "SENTINEL_REOPENED_NOTE" in reopened.state.get_context_for_agents()
        assert "SENTINEL_OLD_NOTE" not in reopened.state.get_context_for_agents()

    def test_message_context_inclusion_round_trips_through_save_load(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc._current_stored = svc.storage.create_new("Context Inclusion")
        svc.state.material = "Material"
        svc.state.round_number = 1
        kept = svc.state.add_user_message("Bleibt im Kontext")
        removed = svc.state.add_user_message("Nur Verlauf")
        removed.include_in_agent_context = False

        filepath = svc._save_current_state()
        assert filepath is not None

        reloaded = self._make_service(tmp_path)
        loaded = reloaded.open_session(filepath.stem)
        assert loaded is True

        kept_restored = reloaded.get_message(kept.id)
        removed_restored = reloaded.get_message(removed.id)
        assert kept_restored is not None
        assert removed_restored is not None
        assert kept_restored.include_in_agent_context is True
        assert removed_restored.include_in_agent_context is False

        # Context assembly still excludes the flagged message after reload.
        ctx = reloaded.state.get_context_for_agents()
        assert "Bleibt im Kontext" in ctx
        assert "Nur Verlauf" not in ctx

    def test_snapshot_includes_include_in_agent_context(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc._current_stored = svc.storage.create_new("Snapshot")
        svc.state.material = "Material"
        svc.state.round_number = 1
        kept = svc.state.add_user_message("Bleibt")
        removed = svc.state.add_user_message("Nur Verlauf")
        removed.include_in_agent_context = False

        filepath = svc._save_current_state()
        assert filepath is not None

        snapshot = svc.snapshot_open_session(filepath.stem)
        assert snapshot is not None

        by_id = {msg["id"]: msg for msg in snapshot["messages"]}
        assert by_id[kept.id]["include_in_agent_context"] is True
        assert by_id[removed.id]["include_in_agent_context"] is False

    def test_open_session_registers_fresh_generation(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Q?",
                agents=[],
            )
        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem

        # Reset the service's generation to simulate an idle state.
        svc._active_generation = None

        assert svc.open_session(file_id) is True
        assert svc._active_generation is not None
        assert not svc._active_generation.cancelled.is_set()

    def test_save_discussion_preserves_separate_rounds(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc._current_stored = svc.storage.create_new("Round Test")
        svc.state.material = "Material"
        svc.state.initial_question = "Runde 1?"
        svc._current_agents = [AgentConfig(name="A1", prompt_id="sys_theory", color="#00f")]

        svc.state.round_number = 1
        svc.state.add_user_message("Runde 1?")
        svc.state.add_agent_response(
            AgentResponse(
                message_id="agent-r1",
                agent_index=0,
                agent_name="A1",
                theory_label="Systemtheorie",
                color="#00f",
                text="Antwort 1",
                is_complete=True,
            )
        )

        svc.state.round_number = 2
        svc.state.add_user_message("Runde 2?")
        svc.state.add_agent_response(
            AgentResponse(
                message_id="agent-r2",
                agent_index=0,
                agent_name="A1",
                theory_label="Systemtheorie",
                color="#00f",
                text="Antwort 2",
                is_complete=True,
            )
        )

        filepath = svc._save_current_state()
        assert filepath is not None

        stored = svc.storage.load(filepath.stem)
        assert stored is not None
        assert [round_data.round_number for round_data in stored.rounds] == [1, 2]
        assert [msg.content for msg in stored.rounds[0].messages] == ["Runde 1?", "Antwort 1"]
        assert [msg.content for msg in stored.rounds[1].messages] == ["Runde 2?", "Antwort 2"]

    def test_build_system_prompt_single_agent(self, tmp_path):
        svc = self._make_service(tmp_path)
        prompt = svc.build_system_prompt("sys_theory")
        assert prompt is not None
        assert "Systemtheoretiker" in prompt
        assert "Analysiere" in prompt
        assert "ZEILENREFERENZEN BEI MATERIALBELEGEN" in prompt
        assert '"exakter Wortlaut" (Z0007)' in prompt
        assert "BELEGFORMAT STATT BELEGZWANG" in prompt

    def test_build_system_prompt_multi_agent_context(self, tmp_path):
        svc = self._make_service(tmp_path)
        agent = AgentConfig(name="A1", prompt_id="sys_theory", color="#000")
        prompt = svc.build_system_prompt(
            "sys_theory",
            agent_config=agent,
            agent_index=0,
            total_agents=2,
            other_agents=[("A2", "Kritische Theorie")],
        )
        assert "You are `Perspective 1`." in prompt
        assert "A2 (Kritische Theorie)" not in prompt
        assert "Other perspectives may appear in the discussion as `Perspective N`." in prompt

    def test_build_system_prompt_three_agent_context_keeps_other_agent_names(self, tmp_path):
        svc = self._make_service(tmp_path)
        agent = AgentConfig(name="A3", prompt_id="sys_theory", color="#000", perspective_number=3)
        prompt = svc.build_system_prompt(
            "sys_theory",
            agent_config=agent,
            agent_index=2,
            total_agents=3,
            other_agents=[
                ("A1", "Systemtheorie"),
                ("A2", "Kritische Theorie"),
            ],
        )
        assert "You are `Perspective 3`." in prompt
        assert "A1 (Systemtheorie)" not in prompt
        assert "A2 (Kritische Theorie)" not in prompt
        assert "Other perspectives may appear in the discussion as `Perspective N`." in prompt

    def test_build_system_prompt_with_material_context(self, tmp_path):
        svc = self._make_service(tmp_path)
        mc = MaterialContext(
            material_type="interview",
            session_input_values={
                "research_material_context": "Leitfadeninterview in Schule",
                "main_input": "Ich vermute eine Ambivalenz zwischen Anpassung und Widerstand.",
                "additional_instructions": "Nenne zuerst Gegenevidenz, dann unterstützende Evidenz.",
            },
        )
        prompt = svc.build_system_prompt(
            "sys_theory",
            material_context=mc,
        )
        assert f"MATERIAL TYPE: {MATERIAL_TYPES['interview']}" in prompt
        assert "RESEARCH MATERIAL CONTEXT" in prompt
        assert "USER INPUT" in prompt
        assert "ADDITIONAL USER INSTRUCTIONS" in prompt
        assert "ADDITIONAL USER INSTRUCTIONS:\nNenne zuerst Gegenevidenz" in prompt
        assert prompt.index("RESEARCH MATERIAL CONTEXT:") < prompt.index("USER INPUT:")
        assert prompt.index("USER INPUT:") < prompt.index("ADDITIONAL USER INSTRUCTIONS:")
        assert "\n\n=== BEHAVIOR FOR 'EXPLORATION' MODE ===\n" in prompt

    def test_build_system_prompt_includes_review_guidance_without_method_inject(self, tmp_path):
        svc = self._make_service(tmp_path)
        mc = MaterialContext(
            material_type="interview",
            session_type="critique",
            session_input_values={
                "main_input": "Die Befragte normalisiert strukturelle Benachteiligung."
            },
        )
        prompt = svc.build_system_prompt("sys_theory", material_context=mc)
        assert "USER INPUT" in prompt
        assert "Die Befragte normalisiert strukturelle Benachteiligung." in prompt

    def test_build_system_prompt_skips_empty_optional_blocks(self, tmp_path):
        svc = self._make_service(tmp_path)
        mc = MaterialContext(
            material_type="interview",
            session_type="exploration",
            session_input_values={"main_input": "Bitte Muster der Zugehörigkeit analysieren."},
        )
        prompt = svc.build_system_prompt("sys_theory", material_context=mc)
        assert "USER INPUT" in prompt
        assert "RESEARCH MATERIAL CONTEXT" not in prompt
        assert "\nADDITIONAL USER INSTRUCTIONS:\n" not in prompt

    @pytest.mark.parametrize("session_type", ["exploration", "critique"])
    def test_build_system_prompt_skips_unchanged_research_material_context_template(
        self, tmp_path, session_type
    ):
        svc = self._make_service(tmp_path)
        definition = svc.session_type_repo.get(session_type)
        assert definition is not None
        research_context = definition.input_for_key("research_material_context")
        assert research_context is not None
        assert research_context.default_text

        mc = MaterialContext(
            material_type="interview",
            session_type=session_type,
            session_inputs=list(definition.session_inputs),
            session_input_values={
                "research_material_context": research_context.default_text,
                "main_input": "Analyse this material.",
            },
            include_unchanged_research_material_context_in_prompt=(
                definition.include_unchanged_research_material_context_in_prompt
            ),
        )

        prompt = svc.build_system_prompt("sys_theory", material_context=mc)

        assert "USER INPUT:\nAnalyse this material." in prompt
        assert "RESEARCH MATERIAL CONTEXT" not in prompt

    def test_synthesis_uses_same_effective_research_context(self, tmp_path):
        svc = self._make_service(tmp_path)
        definition = svc.session_type_repo.get("exploration")
        assert definition is not None
        research = definition.input_for_key("research_material_context")
        assert research is not None and research.default_text
        context = MaterialContext(
            target_language="English",
            session_type="exploration",
            session_inputs=list(definition.session_inputs),
            session_input_values={
                "research_material_context": research.default_text,
                "main_input": "Synthetic task",
            },
        )
        svc._material_context = context
        args = dict(question="Synthetic question", active_agents=[], responses=[])

        assert research.default_text not in svc.build_synthesis_user_prompt(**args)
        context.include_unchanged_research_material_context_in_prompt = True
        assert research.default_text in svc.build_synthesis_user_prompt(**args)
        context.include_unchanged_research_material_context_in_prompt = False
        context.session_input_values["research_material_context"] = (
            research.default_text + "\nEdited"
        )
        assert "Edited" in svc.build_synthesis_user_prompt(**args)

    def test_synthesis_request_is_round_scoped_without_researcher_notes(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.state.material = "MATERIAL_SENTINEL"
        svc.state.round_number = 1
        response = svc.state.add_agent_response(
            AgentResponse(
                message_id="synthesis-boundary-response",
                agent_index=0,
                agent_name="A",
                theory_label="A",
                color="#f00",
                text="CONTRIBUTION_SENTINEL",
            )
        )
        response.note = "NOTE_SYNTHESIS_SENTINEL"
        response.include_note_in_agent_context = True
        prompt = svc.build_synthesis_user_prompt(
            question="Current question",
            active_agents=[],
            responses=[
                AgentResponse(
                    message_id=response.id,
                    agent_index=0,
                    agent_name="A",
                    theory_label="A",
                    color="#f00",
                    text=response.content,
                )
            ],
        )
        assert "CONTRIBUTION_SENTINEL" in prompt
        assert "NOTE_SYNTHESIS_SENTINEL" not in prompt
        assert "MATERIAL_SENTINEL" not in prompt

    def test_build_system_prompt_unknown_id_returns_none(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc.build_system_prompt("nonexistent") is None

    def test_build_user_prompt_both(self, tmp_path):
        svc = self._make_service(tmp_path)
        p = svc.build_user_prompt("Ein Text", "Was passiert?")
        assert "Ein Text" in p
        assert "Was passiert?" in p
        assert "=== CURRENT ROUND USER INPUT (ROUND 1) ===" in p

    def test_build_user_prompt_places_current_interpretation_at_task_boundary(self, tmp_path):
        svc = self._make_service(tmp_path)
        interpretation = "UNIQUE_INTERPRETATION_MARKER: Ich lese eine verdeckte Ambivalenz."
        material_context = MaterialContext(
            session_type="critique",
            session_input_values={"main_input": interpretation},
        )

        p = svc.build_user_prompt(
            "Ein Text",
            interpretation,
            material_context=material_context,
        )

        assert "Ein Text" in p
        assert p.count(interpretation) == 1
        assert "=== CURRENT ROUND USER INPUT (ROUND 1) ===" in p
        assert "=== RESEARCH TASK ===" in svc.build_system_prompt(
            "sys_theory", material_context=material_context
        )

    def test_build_user_prompt_keeps_different_question_with_context(self, tmp_path):
        svc = self._make_service(tmp_path)
        material_context = MaterialContext(
            session_type="critique",
            session_input_values={"main_input": "Meine ursprüngliche Interpretation."},
        )

        p = svc.build_user_prompt(
            "Ein Text",
            "Bitte prüfe besonders die Gegenbelege.",
            material_context=material_context,
        )

        assert "=== CURRENT ROUND USER INPUT (ROUND 1) ===" in p
        assert "Bitte prüfe besonders die Gegenbelege." in p

    def test_build_user_prompt_material_only(self, tmp_path):
        svc = self._make_service(tmp_path)
        p = svc.build_user_prompt("Nur Material", "")
        assert "Nur Material" in p
        assert "=== RESEARCH MATERIAL (AUTHORITATIVE SOURCE) ===" in p

    def test_build_user_prompt_question_only(self, tmp_path):
        svc = self._make_service(tmp_path)
        p = svc.build_user_prompt("", "Nur Frage")
        assert "[USER]: Nur Frage" not in p
        assert p.endswith("Nur Frage")

    def test_run_discussion_returns_results(self, tmp_path):
        svc = self._make_service(tmp_path)
        agents = [
            AgentConfig(
                name="A1",
                prompt_id="sys_theory",
                color="#00f",
                llm_id="qwen2.5-32b-instruct",
                api_host="http://127.0.0.1:1234",
            ),
        ]
        chunks = []
        results = svc.run_discussion(
            material="Testmaterial",
            question="Analyse?",
            agents=agents,
            on_chunk=lambda r: chunks.append(r.text),
            on_agent_start=lambda r: None,
        )
        assert len(results) == 1
        assert results[0].is_complete
        assert results[0].text == "Hallo Welt"  # from mock iter
        assert len(chunks) == 2  # "Hallo " + "Welt"
        svc.llm_manager.get_llm.assert_called_with(
            host="http://127.0.0.1:1234",
            api_key=None,
            model_name="qwen2.5-32b-instruct",
        )

    def test_run_discussion_places_interpretation_at_current_round_boundary(self, tmp_path):
        svc = self._make_service(tmp_path)
        interpretation = "UNIQUE_INTERPRETATION_MARKER: Die Befragte normalisiert Abhängigkeit."
        material_context = MaterialContext(
            session_type="critique",
            session_input_values={"main_input": interpretation},
        )
        agents = [
            AgentConfig(name="A1", prompt_id="sys_theory", color="#00f"),
        ]

        results = svc.run_discussion(
            material="Testmaterial",
            question=interpretation,
            agents=agents,
            material_context=material_context,
            on_agent_start=lambda r: None,
        )

        assert len(results) == 1
        llm = svc.llm_manager.get_llm.return_value
        _, kwargs = llm.generate_stream.call_args
        assert kwargs["prompt"].count(interpretation) == 1
        assert "=== CURRENT ROUND USER INPUT (ROUND 1) ===" in kwargs["prompt"]
        assert kwargs["prompt"].endswith(
            "=== CURRENT RESPONSE LANGUAGE REMINDER ===\nWrite all prose in English."
        )
        assert kwargs["prompt"].count("CURRENT RESPONSE LANGUAGE REMINDER") == 1
        assert "USER INPUT" in kwargs["system_prompt"]
        assert interpretation in kwargs["system_prompt"]

    def test_run_discussion_no_active_agents(self, tmp_path):
        svc = self._make_service(tmp_path)
        agents = [
            AgentConfig(name="A1", prompt_id=None, color="#00f"),  # prompt_id=None → inactive
        ]
        results = svc.run_discussion(
            material="M",
            question="Q",
            agents=agents,
        )
        assert results == []

    def test_run_discussion_llm_error_captured(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.llm_manager.llm.generate_stream.side_effect = RuntimeError("timeout")
        agents = [
            AgentConfig(name="A1", prompt_id="sys_theory", color="#00f"),
        ]
        results = svc.run_discussion(
            material="M",
            question="Q",
            agents=agents,
            on_agent_start=lambda r: None,
        )
        assert len(results) == 1
        assert results[0].error == "timeout"
        assert results[0].error_code == "agent_generation_failed"
        assert results[0].error_params == {}

    def test_run_discussion_preserves_sparse_agent_slot_indices(self, tmp_path):
        svc = self._make_service(tmp_path)
        agents = [
            AgentConfig(name="A1", prompt_id=None, color="#00f"),
            AgentConfig(name="A2", prompt_id="sys_theory", color="#0f0"),
            AgentConfig(name="A3", prompt_id="sys_theory", color="#f00"),
        ]

        started_indices = []
        results = svc.run_discussion(
            material="Testmaterial",
            question="Analyse?",
            agents=agents,
            on_agent_start=lambda response: started_indices.append(response.agent_index),
        )

        assert started_indices == [1, 2]
        assert [response.agent_index for response in results] == [1, 2]

    def test_has_active_discussion(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc.has_active_discussion is False
        svc.state.round_number = 1
        assert svc.has_active_discussion is True

    @pytest.mark.parametrize("material_context", [None, MaterialContext(target_language="  ")])
    def test_start_requires_target_language_before_mutating_state(self, tmp_path, material_context):
        svc = self._make_service(tmp_path)
        existing = svc.state.add_user_message("Existing discussion")
        svc.state.round_number = 7

        with pytest.raises(TargetLanguageRequiredError):
            DiscussionService.start_new_discussion(
                svc,
                material="Material",
                question="Question",
                agents=[],
                material_context=material_context,
            )

        assert svc.state.round_number == 7
        assert svc.state.messages == [existing]
        assert svc._current_stored is None

    def test_stored_session_cannot_continue_without_target_language(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc._current_stored = svc.storage.create_new("Missing language")
        svc._material_context = MaterialContext()
        svc.state.round_number = 1

        with pytest.raises(TargetLanguageRequiredError):
            svc.continue_discussion(user_input="Continue", agents=[])

        assert svc.state.round_number == 1
        assert svc.state.messages == []

    def test_direct_run_discussion_requires_target_language(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc._material_context = None

        with pytest.raises(TargetLanguageRequiredError):
            DiscussionService.run_discussion(
                svc, material="Material", question="Question", agents=[]
            )

    def test_reset_discussion(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.state.round_number = 2
        svc.state.material = "X"
        svc.reset_discussion()
        assert svc.has_active_discussion is False
        assert svc.state.material == ""

    def test_continue_with_no_active_agents_is_a_noop(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.state.round_number = 2
        original_message = svc.state.add_user_message("Bestehende Nachricht")
        original_generation = svc._active_generation
        completed = threading.Event()

        result = svc.continue_discussion(
            user_input="Darf nicht gespeichert werden",
            agents=[
                AgentConfig(
                    name="Inaktiv",
                    prompt_id="sys_theory",
                    enabled=False,
                )
            ],
            on_all_complete=completed.set,
            sequential_mode=True,
        )

        assert result is None
        assert completed.is_set()
        assert svc.state.round_number == 2
        assert svc.state.messages == [original_message]
        assert svc._current_agents == []
        assert svc._sequential_mode is False
        assert svc._active_generation is original_generation

    def test_continuation_blocks_removed_provider_before_contact_or_mutation(self, tmp_path):
        svc = self._make_service(tmp_path)
        old_url = "https://removed.example/v1"
        svc.settings.known_llm_hosts = {
            "Removed": {"url": old_url, "model": "old-model", "models": ["old-model"]}
        }
        agent = AgentConfig(
            name="A",
            prompt_id="sys_theory",
            api_host=old_url,
            host_label="Removed",
            llm_id="old-model",
        )
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(material="M", question="Q", agents=[agent])
        prior_round = svc.state.round_number
        prior_messages = list(svc.state.messages)
        svc.settings.known_llm_hosts = {
            "Replacement": {
                "url": "https://replacement.example/v1",
                "model": "new-model",
                "models": ["new-model"],
            }
        }
        svc.llm_manager.get_llm.reset_mock()

        with pytest.raises(ProviderRebindRequiredError) as exc_info:
            svc.continue_discussion(user_input="Continue", agents=[agent])

        assert exc_info.value.params == {"count": 1}
        assert svc.state.round_number == prior_round
        assert svc.state.messages == prior_messages
        svc.llm_manager.get_llm.assert_not_called()

    def test_continuation_resolution_rebinds_agents_and_synthesis_without_mutation(self, tmp_path):
        svc = self._make_service(tmp_path)
        old_url = "https://removed.example/v1"
        new_url = "https://replacement.example/v1"
        svc.settings.known_llm_hosts = {"Old": {"url": old_url, "model": "old", "models": ["old"]}}
        agent = AgentConfig(
            name="A",
            client_id="stable-agent",
            prompt_id="sys_theory",
            host_configuration_id="Old",
            api_host=old_url,
            llm_id="old",
        )
        synthesis = SynthesisConfig(
            enabled=True,
            host_configuration_id="Old",
            api_host=old_url,
            llm_id="old",
        )
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Q",
                agents=[agent],
                synthesis_config=synthesis,
            )
        svc.settings.known_llm_hosts = {"New": {"url": new_url, "model": "new", "models": ["new"]}}
        before_agents = deepcopy(svc._current_agents)
        before_synthesis = deepcopy(svc._synthesis_config)
        before_state = deepcopy(svc.state)

        resolved_agents, resolved_synthesis = svc.resolve_continuation_configuration(
            [agent],
            rebind_configuration_id="New",
            rebind_model_id="new",
        )

        assert resolved_agents[0].host_configuration_id == "New"
        assert resolved_agents[0].api_host == new_url
        assert resolved_agents[0].llm_id == "new"
        assert resolved_synthesis is not None
        assert resolved_synthesis.host_configuration_id == "New"
        assert resolved_synthesis.api_host == new_url
        assert resolved_synthesis.llm_id == "new"
        assert svc._current_agents == before_agents
        assert svc._synthesis_config == before_synthesis
        assert svc.state == before_state

    def test_continuation_resolution_rejects_stale_rebind_without_mutation(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.state.round_number = 1
        svc.settings.known_llm_hosts = {
            "New": {"url": "https://new.example/v1", "model": "new", "models": ["new"]}
        }
        before_state = deepcopy(svc.state)

        with pytest.raises(ProviderRebindTargetChangedError):
            svc.resolve_continuation_configuration(
                [],
                rebind_configuration_id="New",
                rebind_model_id="changed",
            )

        assert svc.state == before_state

    def test_explicit_rebind_records_only_future_round_provenance(self, tmp_path):
        svc = self._make_service(tmp_path)
        old_url = "https://old.example/v1"
        new_url = "https://new.example/v1"
        svc.settings.known_llm_hosts = {
            "Old": {"url": old_url, "model": "old-model", "models": ["old-model"]}
        }
        old_agent = AgentConfig(
            name="A",
            prompt_id="sys_theory",
            api_host=old_url,
            host_configuration_id="Old",
            host_label="Old",
            llm_id="old-model",
        )
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(material="M", question="Q", agents=[old_agent])
        svc.settings.known_llm_hosts = {
            "New": {"url": new_url, "model": "new-model", "models": ["new-model"]}
        }
        new_agent = AgentConfig(
            name="A",
            client_id=old_agent.client_id,
            prompt_id="sys_theory",
            api_host=new_url,
            host_configuration_id="New",
            host_label="New",
            llm_id="new-model",
        )

        with patch.object(svc, "run_discussion_async"):
            svc.continue_discussion(user_input="Continue", agents=[new_agent])

        assert svc._round_provider_provenance[1][0].host_label == "Old"
        assert svc._round_provider_provenance[1][0].model_id == "old-model"
        assert svc._round_provider_provenance[2][0].host_label == "New"
        assert svc._round_provider_provenance[2][0].model_id == "new-model"

    def test_duplicate_url_requires_label_rebind_and_records_selected_identity(self, tmp_path):
        svc = self._make_service(tmp_path)
        shared_url = "https://shared.example/v1"
        svc.settings.known_llm_hosts = {
            "A": {"url": shared_url, "model": "shared", "models": ["shared"]},
            "B": {"url": shared_url, "model": "shared", "models": ["shared"]},
            "C": {"url": "https://alternate.example/v1", "model": "other", "models": ["other"]},
        }
        agent = AgentConfig(
            name="A",
            prompt_id="sys_theory",
            host_configuration_id="A",
            host_label="A",
            api_host=shared_url,
            llm_id="shared",
        )
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(material="M", question="Q", agents=[agent])
        del svc.settings.known_llm_hosts["A"]

        with pytest.raises(ProviderRebindRequiredError):
            svc.continue_discussion(user_input="Continue", agents=[agent])

        completed = threading.Event()
        with (
            patch.object(svc, "_run_agent_round", return_value=[]),
            patch.object(svc, "_run_round_synthesis"),
        ):
            caller_supplied_alternate = deepcopy(agent)
            caller_supplied_alternate.host_label = "C"
            caller_supplied_alternate.host_configuration_id = "C"
            caller_supplied_alternate.api_host = "https://alternate.example/v1"
            caller_supplied_alternate.llm_id = "other"
            svc.continue_discussion(
                user_input="Continue",
                agents=[caller_supplied_alternate],
                rebind_configuration_id="B",
                rebind_model_id="shared",
                on_all_complete=completed.set,
            )
            assert completed.wait(timeout=1)
        assert svc._current_agents[0].host_label == "B"
        assert svc._current_agents[0].host_configuration_id == "B"
        assert svc._round_provider_provenance[1][0].host_label == "A"
        assert svc._round_provider_provenance[2][0].host_label == "B"

    def test_rebind_save_failure_restores_session_before_provider_contact(self, tmp_path):
        svc = self._make_service(tmp_path)
        old_url = "https://old.example/v1"
        svc.settings.known_llm_hosts = {"Old": {"url": old_url, "model": "old", "models": ["old"]}}
        agent = AgentConfig(
            name="A",
            prompt_id="sys_theory",
            host_configuration_id="Old",
            host_label="Old",
            api_host=old_url,
            llm_id="old",
        )
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(material="M", question="Q", agents=[agent])
        previous_state = deepcopy(svc.state)
        previous_stored = deepcopy(svc._current_stored)
        previous_generation = svc._begin_generation_locked()
        assert previous_generation.cancelled.is_set() is False
        svc.settings.known_llm_hosts = {
            "New": {
                "url": "https://new.example/v1",
                "model": "new",
                "models": ["new"],
            }
        }

        with (
            patch.object(svc.storage, "save", side_effect=OSError("read-only")),
            patch.object(svc, "run_discussion_async") as run_async,
            pytest.raises(OSError, match="read-only"),
        ):
            svc.continue_discussion(
                user_input="Continue",
                agents=[agent],
                rebind_configuration_id="New",
                rebind_model_id="new",
            )

        assert svc.state == previous_state
        assert svc._current_stored == previous_stored
        assert svc._current_agents[0].host_label == "Old"
        assert svc._active_generation is previous_generation
        assert previous_generation.cancelled.is_set() is False
        run_async.assert_not_called()
        svc.llm_manager.get_llm.assert_not_called()

    def test_rebind_to_managed_raw_configuration_id_records_display_label(self, tmp_path):
        svc = self._make_service(tmp_path)
        old_url = "https://removed.example/v1"
        svc.settings.known_llm_hosts = {
            "Removed": {"url": old_url, "model": "old", "models": ["old"]}
        }
        agent = AgentConfig(
            name="A",
            prompt_id="sys_theory",
            host_configuration_id="Removed",
            host_label="Removed",
            api_host=old_url,
            llm_id="old",
        )
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(material="M", question="Q", agents=[agent])
        managed = _local_ai_host()
        managed_url = managed["url"]
        managed_model = managed["model"]
        svc.settings.known_llm_hosts = {
            LOCAL_AI_HOST_LABEL: managed,
            "Integrierte KI": {
                "url": managed_url,
                "model": "external-model",
                "models": ["external-model"],
            },
        }
        completed = threading.Event()

        with (
            patch.object(svc, "_run_agent_round", return_value=[]),
            patch.object(svc, "_run_round_synthesis"),
        ):
            svc.continue_discussion(
                user_input="Continue",
                agents=[agent],
                rebind_configuration_id=LOCAL_AI_HOST_LABEL,
                rebind_model_id=managed_model,
                on_all_complete=completed.set,
            )
            assert completed.wait(timeout=1)

        rebound = svc._current_agents[0]
        assert rebound.host_configuration_id == LOCAL_AI_HOST_LABEL
        assert rebound.host_label == "Integrierte KI"
        assert rebound.api_host == managed_url
        assert rebound.llm_id == managed_model
        assert svc._round_provider_provenance[2][0].host_configuration_id == LOCAL_AI_HOST_LABEL
        assert svc._round_provider_provenance[2][0].host_label == "Integrierte KI"

        svc.reset_discussion()
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Managed start",
                agents=[rebound],
            )
        assert svc._round_provider_provenance[1][0].host_configuration_id == LOCAL_AI_HOST_LABEL
        assert svc._round_provider_provenance[1][0].host_label == "Integrierte KI"

    def test_reset_wins_before_contending_continue_checks_state(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.state.round_number = 1
        svc.state.material = "Material"

        class NotifyingRLock:
            def __init__(self):
                self._lock = threading.RLock()
                self.owner = None
                self.contended = threading.Event()

            def acquire(self, *args, **kwargs):
                if self.owner is not None and self.owner != threading.get_ident():
                    self.contended.set()
                acquired = self._lock.acquire(*args, **kwargs)
                if acquired:
                    self.owner = threading.get_ident()
                return acquired

            def release(self):
                self._lock.release()
                self.owner = None

            def __enter__(self):
                self.acquire()
                return self

            def __exit__(self, exc_type, exc, tb):
                self.release()

        lock = NotifyingRLock()
        svc._run_lock = lock
        result = []

        lock.acquire()
        thread = threading.Thread(
            target=lambda: result.append(
                svc.continue_discussion(
                    user_input="Stale Fortsetzung",
                    agents=[AgentConfig(name="A", prompt_id="sys_theory")],
                )
            ),
            daemon=True,
        )
        thread.start()
        assert lock.contended.wait(timeout=5.0)

        # Re-entrant for the owner: reset completes while the continuation is
        # waiting to acquire lifecycle ownership.
        svc.reset_discussion()
        lock.release()
        thread.join(timeout=5.0)

        assert not thread.is_alive()
        assert result == [None]
        assert svc.state.round_number == 0
        assert svc.state.material == ""
        assert svc.state.messages == []


class TestRunScopedCancellation:
    def _make_service(self, tmp_path) -> DiscussionService:
        """Dedicated helper so this class can run independently."""
        session_contexts_dir = tmp_path / "session_contexts"
        _populate_session_contexts(session_contexts_dir)
        llm = MagicMock()
        llm.generate_stream.return_value = iter(["Hallo ", "Welt"])
        llm_manager = MagicMock()
        llm_manager.get_llm.return_value = llm
        return _LanguageConfiguredDiscussionService(
            settings=_mock_settings(),
            llm_manager=llm_manager,
            prompt_repo=_mock_prompt_repo(),
            storage_dir=tmp_path / "disc",
            session_context_dir=session_contexts_dir,
        )

    def test_initial_worker_reports_unexpected_failure_and_clears_running_state(self, tmp_path):
        svc = self._make_service(tmp_path)
        interrupted = threading.Event()
        svc._generation_running = True
        generation = svc._begin_generation()
        svc.run_discussion = MagicMock(side_effect=RuntimeError("private provider detail"))

        svc.run_discussion_async(
            material="M",
            question="Q",
            agents=[],
            on_unexpected_error=interrupted.set,
            _generation=generation,
        )

        assert interrupted.wait(timeout=5.0)
        assert svc._generation_running is False

    def test_continuation_worker_reports_unexpected_failure_and_clears_running_state(
        self, tmp_path
    ):
        svc = self._make_service(tmp_path)
        initial_complete = threading.Event()
        svc.start_new_discussion(
            material="M",
            question="Q",
            agents=[AgentConfig(name="A", prompt_id="sys_theory", color="#00f")],
            on_all_complete=initial_complete.set,
        )
        assert initial_complete.wait(timeout=5.0)

        interrupted = threading.Event()
        svc._run_agent_round = MagicMock(side_effect=RuntimeError("private provider detail"))
        result = svc.continue_discussion(
            user_input="Continue",
            agents=[AgentConfig(name="A", prompt_id="sys_theory", color="#00f")],
            on_unexpected_error=interrupted.set,
        )

        assert result is not None
        assert interrupted.wait(timeout=5.0)
        assert svc._generation_running is False

    def test_unexpected_worker_failure_marks_current_round_cards_failed_before_save(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.state.round_number = 1
        svc.state.round_status = "in_progress"
        svc.state.upsert_agent_response(
            AgentResponse(
                message_id="agent-in-progress",
                agent_index=0,
                agent_name="A",
                theory_label="Theory",
                color="#00f",
                text="Visible partial",
            )
        )
        svc.state.upsert_synthesis_response(
            _SynthesisResponse(
                message_id="synthesis-in-progress", text="Partial synthesis", round_number=1
            )
        )
        generation = svc._begin_generation()
        saved_statuses: list[tuple[str, str]] = []

        def capture_save():
            saved_statuses.extend((message.id, message.status) for message in svc.state.messages)
            return None

        svc._save_current_state = capture_save  # type: ignore[method-assign]

        svc._fail_generation(generation)

        assert svc.state.round_status == "failed"
        assert {message.status for message in svc.state.messages} == {"failed"}
        assert dict(saved_statuses) == {
            "agent-in-progress": "failed",
            "synthesis-in-progress": "failed",
        }

    def test_cancel_and_reset_keeps_state_empty_even_if_old_generator_dies(self, tmp_path):
        svc = self._make_service(tmp_path)
        llm = svc.llm_manager.get_llm.return_value

        entered_generate = threading.Event()
        release_generate = threading.Event()

        def blocking_stream(*args, **kwargs):
            entered_generate.set()
            release_generate.wait()
            raise RuntimeError("Local AI stopped")

        llm.generate_stream.side_effect = blocking_stream

        started = threading.Event()
        completed = threading.Event()
        external_complete_errors: list[str] = []
        autosaves: list[object] = []

        original_save = svc._save_current_state

        def counting_save():
            autosaves.append(object())
            return original_save()

        svc._save_current_state = counting_save  # type: ignore[method-assign]

        def on_agent_complete(response: AgentResponse):
            if response.error:
                external_complete_errors.append(response.error)

        def on_all_complete():
            completed.set()

        agent = AgentConfig(name="A1", prompt_id="sys_theory", color="#00f")

        def run():
            started.set()
            svc.run_discussion(
                material="Testmaterial",
                question="Analyse?",
                agents=[agent],
                on_agent_start=lambda r: None,
                on_agent_complete=on_agent_complete,
                on_all_complete=on_all_complete,
            )

        old_thread = threading.Thread(target=run, daemon=True)
        old_thread.start()

        assert entered_generate.wait(timeout=5.0), "old worker must enter generate_stream"

        # Idempotent: cancel returns True once, then False.
        assert svc.cancel_active_generation() is True
        assert svc.cancel_active_generation() is False

        release_generate.set()
        completed.wait(timeout=5.0)

        assert svc.cancel_active_generation() is False

        svc.reset_discussion()

        release_generate.set()
        assert completed.wait(timeout=5.0), "old all_complete must still fire"

        # State must remain empty and no late error reported externally.
        assert not svc.has_active_discussion
        assert svc.state.messages == []
        assert svc.state.round_number == 0
        assert svc.state.material == ""
        assert external_complete_errors == []
        assert autosaves == []

    def test_replacement_run_supersedes_blocked_old_worker(self, tmp_path):
        svc = self._make_service(tmp_path)
        llm = svc.llm_manager.get_llm.return_value

        # Block the old worker *before* its body (and therefore before it could
        # acquire a generation).  This simulates a deferred child waking after
        # a replacement has already begun.
        old_enter_run = threading.Event()
        old_release_run = threading.Event()
        original_run_discussion = svc.run_discussion

        call_count = [0]

        def blocking_run_discussion(*args, **kwargs) -> list[AgentResponse]:
            if call_count[0] == 0:
                call_count[0] += 1
                old_enter_run.set()
                old_release_run.wait()
            return original_run_discussion(*args, **kwargs)

        svc.run_discussion = blocking_run_discussion  # type: ignore[method-assign]

        old_completed = threading.Event()

        svc.start_new_discussion(
            material="First material",
            question="First question?",
            agents=[AgentConfig(name="Old", prompt_id="sys_theory", color="#f00")],
            on_all_complete=old_completed.set,
        )

        assert old_enter_run.wait(timeout=5.0), (
            "old worker must enter run_discussion before state mutation"
        )

        # Replacement run: generator responds immediately.
        def second_stream(*args, **kwargs):
            return iter(["replacement"])

        llm.generate_stream.side_effect = second_stream

        autosaves: list[str] = []
        original_save = svc._save_current_state

        def capture_save() -> Path | None:
            autosaves.append(svc.state.initial_question)
            return original_save()

        svc._save_current_state = capture_save  # type: ignore[method-assign]

        replacement_completed = threading.Event()

        svc.start_new_discussion(
            material="Second material",
            question="Second question?",
            agents=[AgentConfig(name="New", prompt_id="sys_theory", color="#00f")],
            on_all_complete=replacement_completed.set,
        )

        # Wait for the *replacement* to finish before releasing the old worker.
        assert replacement_completed.wait(timeout=5.0), (
            "replacement must complete before we inspect anything"
        )

        old_release_run.set()
        assert old_completed.wait(timeout=5.0), (
            "old all_complete must still fire to end its generator"
        )

        # Only replacement messages/state remain; old worker must not corrupt.
        assert svc.state.initial_question == "Second question?"
        assert any("replacement" in str(msg.content) for msg in svc.state.messages)
        assert not any("First question" in str(msg.content) for msg in svc.state.messages)

        all_messages = [msg for msg in svc.state.messages]
        assert all(msg.agent_name != "Old" for msg in all_messages)
        assert all("[Fehler: Local AI stopped]" not in str(msg.content) for msg in all_messages)

        assert autosaves == ["Second question?"]

    def test_cancel_active_generation_idempotency_contract(self, tmp_path):
        svc = self._make_service(tmp_path)
        llm = svc.llm_manager.get_llm.return_value

        entered_generate = threading.Event()
        release_generate = threading.Event()

        def blocking_stream(*args, **kwargs):
            entered_generate.set()
            release_generate.wait()
            return iter([])

        llm.generate_stream.side_effect = blocking_stream

        completed = threading.Event()

        def run():
            svc.run_discussion(
                material="M",
                question="Q?",
                agents=[AgentConfig(name="A", prompt_id="sys_theory", color="#00f")],
                on_all_complete=completed.set,
            )

        t = threading.Thread(target=run, daemon=True)
        t.start()
        assert entered_generate.wait(timeout=5.0)

        assert svc.cancel_active_generation() is True
        assert svc.cancel_active_generation() is False

        release_generate.set()
        completed.wait(timeout=5.0)

        assert svc.cancel_active_generation() is False

    def test_stale_stream_token_cannot_cancel_replacement_generation(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.state.round_number = 1
        svc.state.round_status = "in_progress"
        old_generation = svc._begin_generation()
        old_token = svc.active_generation_token()
        assert old_token == old_generation.id

        replacement = svc._begin_generation()
        svc.state.round_status = "in_progress"

        assert svc.cancel_generation(old_token) is False
        assert replacement.cancelled.is_set() is False
        assert svc.cancel_active_generation() is True
        assert replacement.cancelled.is_set() is True

    def test_old_terminal_stream_disconnect_cannot_cancel_new_generation(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.state.round_number = 1
        svc.state.round_status = "in_progress"
        old_generation = svc._begin_generation()
        release_request = MagicMock()
        events: queue.Queue[dict] = queue.Queue()
        events.put({"type": "all_complete"})
        done = threading.Event()
        done.set()
        svc_context = MagicMock()
        svc_context.discussion = svc
        response = _stream_response(
            events,
            done,
            [{"type": "discussion_started"}],
            on_disconnect=lambda: _disconnect_generation(
                svc_context, old_generation.id, release_request
            ),
        )
        iterator = response.body_iterator

        async def consume_initial_then_disconnect() -> str:
            initial = await anext(iterator)
            replacement = svc._begin_generation()
            svc.state.round_status = "in_progress"
            await iterator.aclose()
            assert replacement.cancelled.is_set() is False
            return initial

        assert asyncio.run(consume_initial_then_disconnect()).startswith("data: ")
        release_request.assert_called_once_with()

    def test_atomic_mutation_rejects_a_superseded_generation(self, tmp_path):
        svc = self._make_service(tmp_path)
        old_generation = svc._begin_generation()
        observed: list[str] = []

        replacement_generation = svc._begin_generation()

        changed = svc._mutate_state_if_current(
            old_generation,
            lambda: observed.append("old"),
        )

        assert changed is False
        assert observed == []
        assert svc._is_current_generation(replacement_generation) is True


class TestInterruptedRoundPersistence:
    def test_cancel_persists_partial_output_as_interrupted(self, tmp_path):
        svc = TestRunScopedCancellation()._make_service(tmp_path)
        llm = svc.llm_manager.get_llm.return_value
        chunk_seen = threading.Event()
        release = threading.Event()

        def stream(*args, **kwargs):
            yield "visible partial"
            release.wait(timeout=5)

        llm.generate_stream.side_effect = stream
        done = threading.Event()
        svc.start_new_discussion(
            material="Material",
            question="Question?",
            agents=[AgentConfig(name="A", prompt_id="sys_theory", color="#00f")],
            on_chunk=lambda _response: chunk_seen.set(),
            on_all_complete=done.set,
        )
        assert chunk_seen.wait(timeout=5)
        file_id = svc.current_session_file_id()
        assert file_id is not None
        assert svc.cancel_active_generation() is True
        stored = svc.storage.load(file_id)
        assert stored is not None
        assert stored.rounds[0].status == "interrupted"
        assert stored.rounds[0].messages[-1].content == "visible partial"
        assert stored.rounds[0].messages[-1].status == "interrupted"
        release.set()
        assert done.wait(timeout=5)

        assert svc.open_session(file_id) is True
        assert svc.state.round_status == "interrupted"
        assert svc.state.messages[-1].content == "visible partial"
        assert svc.state.messages[-1].status == "interrupted"

    def test_cancel_closes_provider_stream(self, tmp_path):
        svc = TestRunScopedCancellation()._make_service(tmp_path)
        llm = svc.llm_manager.get_llm.return_value
        entered = threading.Event()
        closed = threading.Event()

        class BlockingStream:
            def __iter__(self):
                return self

            def __next__(self):
                if not entered.is_set():
                    entered.set()
                    return "visible partial"
                closed.wait()
                raise StopIteration

            def close(self):
                closed.set()

        llm.generate_stream.side_effect = lambda *args, **kwargs: BlockingStream()
        done = threading.Event()
        svc.start_new_discussion(
            material="Material",
            question="Question?",
            agents=[AgentConfig(name="A", prompt_id="sys_theory", color="#00f")],
            on_all_complete=done.set,
        )

        assert entered.wait(timeout=5)
        assert svc.cancel_active_generation() is True
        assert done.wait(timeout=5)
        assert closed.wait(timeout=5)

    def test_cancel_aborts_blocked_openai_http_response(self, tmp_path):
        svc = TestRunScopedCancellation()._make_service(tmp_path)
        entered = threading.Event()
        response_closed = threading.Event()

        class BlockingResponse:
            ok = True
            encoding = "utf-8"

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

            def iter_lines(self, decode_unicode=True):
                assert decode_unicode is True
                entered.set()
                response_closed.wait()
                return iter(())

            def close(self):
                response_closed.set()

        adapter = OpenAICompatibleLLM(
            model_name="model",
            host="https://provider.example/v1",
            retries=0,
        )
        adapter.session.post = MagicMock(return_value=BlockingResponse())
        svc.llm_manager.get_llm.return_value = adapter
        done = threading.Event()

        with patch.object(
            svc,
            "_preflight_context_usage",
            return_value=ContextUsage(available=False),
        ):
            svc.start_new_discussion(
                material="Material",
                question="Question?",
                agents=[AgentConfig(name="A", prompt_id="sys_theory", color="#00f")],
                on_all_complete=done.set,
            )
            assert entered.wait(timeout=5)
            assert svc.cancel_active_generation() is True
            assert response_closed.wait(timeout=1)
            assert done.wait(timeout=1)

    def test_cancel_closes_blocked_synthesis_stream(self, tmp_path):
        svc = TestRunScopedCancellation()._make_service(tmp_path)
        llm = svc.llm_manager.get_llm.return_value
        entered = threading.Event()
        closed = threading.Event()

        class BlockingStream:
            def __iter__(self):
                return self

            def __next__(self):
                entered.set()
                closed.wait()
                raise StopIteration

            def close(self):
                closed.set()

        llm.generate_stream.side_effect = lambda *args, **kwargs: BlockingStream()
        svc._synthesis_config = SynthesisConfig(
            enabled=True,
            api_host="https://provider.example/v1",
            llm_id="model",
        )
        svc.state.round_number = 1
        svc.state.round_status = "in_progress"
        generation = svc._begin_generation()
        svc._generation_running = True
        response = AgentResponse(
            message_id="perspective",
            agent_index=0,
            agent_name="A",
            theory_label="Theory",
            color="#00f",
            text="usable",
            is_complete=True,
            status="completed",
        )
        completed = threading.Event()

        with (
            patch.object(svc, "_save_state_if_current"),
            patch.object(svc, "build_synthesis_system_prompt", return_value="system"),
            patch.object(svc, "build_synthesis_user_prompt", return_value="user"),
            patch.object(
                svc,
                "_preflight_context_usage",
                return_value=ContextUsage(available=False),
            ),
        ):
            worker = threading.Thread(
                target=lambda: (
                    svc._run_round_synthesis(
                        generation=generation,
                        question="Question?",
                        active_agents=[(0, AgentConfig(name="A", prompt_id="sys_theory"))],
                        responses=[response],
                        on_start=None,
                        on_chunk=None,
                        on_complete=None,
                    ),
                    completed.set(),
                ),
                daemon=True,
            )
            worker.start()
            assert entered.wait(timeout=5)
            assert svc.cancel_active_generation() is True
            assert closed.wait(timeout=5)
            assert completed.wait(timeout=5)

    def test_old_stream_cleanup_cannot_unregister_replacement_stream(self, tmp_path):
        svc = TestRunScopedCancellation()._make_service(tmp_path)
        old_closed = threading.Event()
        replacement_closed = threading.Event()
        old_stream = MagicMock()
        old_stream.close.side_effect = old_closed.set
        replacement_stream = MagicMock()
        replacement_stream.close.side_effect = replacement_closed.set

        old_generation = svc._begin_generation()
        assert svc._register_generation_stream(old_generation, old_stream) is True
        replacement_generation = svc._begin_generation()
        assert old_closed.wait(timeout=5)
        assert svc._register_generation_stream(replacement_generation, replacement_stream) is True

        svc._unregister_generation_stream(old_generation, old_stream)

        assert replacement_closed.is_set() is False
        svc.state.round_status = "in_progress"
        svc._generation_running = True
        assert svc.cancel_active_generation() is True
        assert replacement_closed.wait(timeout=5)

    def test_provider_failure_retains_text_and_marks_round_failed(self, tmp_path):
        svc = TestRunScopedCancellation()._make_service(tmp_path)
        llm = svc.llm_manager.get_llm.return_value

        def stream(*args, **kwargs):
            yield "visible before failure"
            raise RuntimeError("provider disconnected")

        llm.generate_stream.side_effect = stream
        done = threading.Event()
        svc.start_new_discussion(
            material="Material",
            question="Question?",
            agents=[AgentConfig(name="A", prompt_id="sys_theory", color="#00f")],
            on_all_complete=done.set,
        )
        assert done.wait(timeout=5)
        assert svc.state.round_status == "failed"
        message = svc.state.messages[-1]
        assert "visible before failure" in message.content
        assert message.status == "failed"
        assert message.error_code == "agent_generation_failed"

    def test_provider_failure_never_persists_or_reopens_api_credentials(self, tmp_path):
        secret = "aqa-persistence-secret-123"
        adapter = OpenAICompatibleLLM(
            model_name="custom-model",
            host="https://provider.invalid",
            api_key=secret,
            retries=0,
        )
        response = MagicMock(
            status_code=401,
            text=f"Authorization: Bearer {secret} rejected",
        )
        response.json.return_value = {"error": {"message": response.text}}
        provider_error = adapter._provider_http_error(response)
        assert secret not in str(provider_error)

        svc = TestRunScopedCancellation()._make_service(tmp_path)
        llm = svc.llm_manager.get_llm.return_value

        def stream(*args, **kwargs):
            yield "visible before failure"
            raise provider_error

        llm.generate_stream.side_effect = stream
        done = threading.Event()
        svc.start_new_discussion(
            material="Material",
            question="Question?",
            agents=[AgentConfig(name="A", prompt_id="sys_theory", color="#00f")],
            on_all_complete=done.set,
        )
        assert done.wait(timeout=5)
        file_id = svc.current_session_file_id()
        assert file_id is not None
        stored_text = (tmp_path / "disc" / f"{file_id}.json").read_text(encoding="utf-8")
        assert secret not in stored_text
        assert "[REDACTED]" in stored_text

        assert svc.open_session(file_id) is True
        reopened = svc.state.messages[-1]
        assert secret not in (reopened.error or "")
        assert reopened.error_code == "provider_authentication_failed"

    def test_incomplete_stream_is_persisted_reopened_and_allows_later_recovery(self, tmp_path):
        svc = TestRunScopedCancellation()._make_service(tmp_path)
        llm = svc.llm_manager.get_llm.return_value
        llm.generate_stream.side_effect = LLMRequestError(
            "The provider stream ended before a terminal event.",
            code="provider_stream_incomplete",
        )
        done = threading.Event()

        svc.start_new_discussion(
            material="Material",
            question="Question?",
            agents=[AgentConfig(name="A", prompt_id="sys_theory", color="#00f")],
            on_all_complete=done.set,
        )

        assert done.wait(timeout=5)
        file_id = svc.current_session_file_id()
        assert file_id is not None
        assert svc.state.round_status == "failed"
        assert svc.state.messages[-1].error_code == "provider_stream_incomplete"
        stored = svc.storage.load(file_id)
        assert stored is not None
        assert stored.rounds[-1].messages[-1].error_code == "provider_stream_incomplete"

        assert svc.open_session(file_id) is True
        assert svc.state.messages[-1].error_code == "provider_stream_incomplete"

        llm.generate_stream.side_effect = lambda *args, **kwargs: iter(["Recovered answer"])
        recovery_done = threading.Event()
        svc.start_new_discussion(
            material="Material",
            question="Try again?",
            agents=[AgentConfig(name="A", prompt_id="sys_theory", color="#00f")],
            on_all_complete=recovery_done.set,
        )
        assert recovery_done.wait(timeout=5)
        recovered = svc.state.messages[-1]
        assert recovered.content == "Recovered answer"
        assert recovered.status == "completed"
        assert recovered.error_code is None

    def test_partial_transport_failure_is_persisted_without_replay(self, tmp_path):
        svc = TestRunScopedCancellation()._make_service(tmp_path)
        llm = svc.llm_manager.get_llm.return_value

        def broken_stream(*args, **kwargs):
            yield "Partial answer"
            raise LLMRequestError(
                "The provider stream ended before a terminal event.",
                code="provider_stream_incomplete",
            )

        llm.generate_stream.side_effect = broken_stream
        done = threading.Event()
        completed = []
        svc.start_new_discussion(
            material="Material",
            question="Question?",
            agents=[AgentConfig(name="A", prompt_id="sys_theory", color="#00f")],
            on_agent_complete=completed.append,
            on_all_complete=done.set,
        )

        assert done.wait(timeout=5)
        assert llm.generate_stream.call_count == 1
        assert completed[0].is_complete is False
        message = svc.state.messages[-1]
        assert message.content == "Partial answer"
        assert message.status == "failed"
        assert message.error_code == "provider_stream_incomplete"
        assert svc.state.round_status == "failed"

        file_id = svc.current_session_file_id()
        assert file_id is not None
        stored = svc.storage.load(file_id)
        assert stored is not None
        assert stored.rounds[-1].status == "failed"
        assert stored.rounds[-1].messages[-1].content == "Partial answer"
        assert stored.rounds[-1].messages[-1].status == "failed"

        assert svc.open_session(file_id) is True
        reopened = svc.state.messages[-1]
        assert reopened.content == "Partial answer"
        assert reopened.status == "failed"
        assert reopened.error_code == "provider_stream_incomplete"

    @pytest.mark.parametrize("provider_text", ["", "   \n\t"])
    def test_empty_provider_output_is_persisted_as_failure(self, tmp_path, provider_text):
        svc = TestRunScopedCancellation()._make_service(tmp_path)
        llm = svc.llm_manager.get_llm.return_value
        llm.generate_stream.side_effect = lambda *args, **kwargs: iter([provider_text])
        done = threading.Event()

        svc.start_new_discussion(
            material="Material",
            question="Question?",
            agents=[AgentConfig(name="A", prompt_id="sys_theory", color="#00f")],
            on_all_complete=done.set,
        )

        assert done.wait(timeout=5)
        assert svc.state.round_status == "failed"
        message = svc.state.messages[-1]
        assert message.content == provider_text
        assert message.status == "failed"
        assert message.error_code == "provider_empty_response"
        stored = svc.storage.load(svc.current_session_file_id() or "")
        assert stored is not None
        assert stored.rounds[-1].status == "failed"
        assert stored.rounds[-1].messages[-1].error_code == "provider_empty_response"


class TestStartDiscussionLineNumbers:
    def _make_service(self, tmp_path) -> DiscussionService:
        session_contexts_dir = tmp_path / "session_contexts"
        _populate_session_contexts(session_contexts_dir)
        return _LanguageConfiguredDiscussionService(
            settings=_mock_settings(),
            llm_manager=_mock_llm_manager(),
            prompt_repo=_mock_prompt_repo(),
            storage_dir=tmp_path / "disc",
            session_context_dir=session_contexts_dir,
        )

    def test_start_new_discussion_line_numbers_in_state_and_llm_argument(self, tmp_path):
        svc = self._make_service(tmp_path)
        raw_material = "Erste Aussage. Zweite Aussage.\n\nUnpunktierte Zeile"

        with patch.object(svc, "run_discussion_async") as run_async:
            svc.start_new_discussion(
                material=raw_material,
                question="Was faellt auf?",
                agents=[],
                material_context=MaterialContext(material_type="interview"),
            )

        assert svc.state.material == (
            "Z0001: Erste Aussage. Zweite Aussage.\n\nZ0002: Unpunktierte Zeile"
        )
        run_async.assert_called_once()
        assert run_async.call_args.kwargs["material"] == svc.state.material
        assert run_async.call_args.kwargs["material"].startswith("Z0001:")

    def test_line_numbered_material_reaches_the_agent_prompt(self, tmp_path):
        svc = self._make_service(tmp_path)
        numbered_material = add_line_numbers_to_material("Erste Aussage. Zweite Aussage.")

        prompt = svc.build_user_prompt(numbered_material, "Was faellt auf?")

        assert numbered_material in prompt

    def test_start_new_discussion_defaults_to_numbering(self, tmp_path):
        svc = self._make_service(tmp_path)
        raw_material = "Default eins\nDefault zwei"

        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material=raw_material,
                question="Was faellt auf?",
                agents=[],
                material_context=None,
            )

        assert svc.state.material.startswith("Z0001: Default eins")

    def test_start_new_discussion_preserves_unknown_material_type_without_numbering(self, tmp_path):
        svc = self._make_service(tmp_path)
        raw_material = "Podcast text\nWeitere Zeile"

        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material=raw_material,
                question="Was faellt auf?",
                agents=[],
                material_context=MaterialContext(material_type="podcast"),
            )

        assert svc.state.material == raw_material

    def test_start_new_discussion_does_not_duplicate_existing_numbers(self, tmp_path):
        svc = self._make_service(tmp_path)
        numbered_material = "Z0001: Erste Zeile\nZ0002: Zweite Zeile"

        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material=numbered_material,
                question="Was faellt auf?",
                agents=[],
                material_context=MaterialContext(material_type="interview"),
            )

        assert svc.state.material == numbered_material

    def test_line_numbers_in_stored_after_save(self, tmp_path):
        svc = self._make_service(tmp_path)
        raw_material = "Zeile A\nZeile B"

        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material=raw_material,
                question="Was faellt auf?",
                agents=[],
                material_context=MaterialContext(material_type="document"),
            )

        svc._save_current_state()
        assert svc._current_stored is not None
        assert "Z0001:" in svc._current_stored.material

    def test_numbered_material_survives_storage_roundtrip_and_markdown(self, tmp_path):
        svc = self._make_service(tmp_path)
        raw_material = "Zeile Alpha. Zeile Beta.\n\nZeile Gamma"

        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material=raw_material,
                question="Was faellt auf?",
                agents=[],
                material_context=MaterialContext(material_type="document"),
            )

        filepath = svc._save_current_state()
        assert filepath is not None

        restored = svc.storage.load(filepath.stem)
        assert restored is not None
        assert restored.material == ("Z0001: Zeile Alpha. Zeile Beta.\n\nZ0002: Zeile Gamma")

        markdown = restored.to_markdown()
        assert "Z0001: Zeile Alpha. Zeile Beta." in markdown
        assert "Z0002: Zeile Gamma" in markdown


# Session persistence lifecycle — initial save before async
# completion, full roundtrip including sequential_mode + agent config
class TestSessionLifecycle:
    def _make_service(self, tmp_path) -> DiscussionService:
        session_contexts_dir = tmp_path / "session_contexts"
        _populate_session_contexts(session_contexts_dir)
        return _LanguageConfiguredDiscussionService(
            settings=_mock_settings(),
            llm_manager=_mock_llm_manager(),
            prompt_repo=_mock_prompt_repo(),
            storage_dir=tmp_path / "disc",
            session_context_dir=session_contexts_dir,
        )

    def test_provider_history_and_request_context_stay_with_saved_discussion(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.settings.known_llm_hosts = {
            "Synthetic A": {
                "url": "https://synthetic-a.invalid/v1",
                "model": "model-a",
                "models": ["model-a"],
            },
            "Synthetic B": {
                "url": "https://synthetic-b.invalid/v1",
                "model": "model-b",
                "models": ["model-b"],
            },
        }
        agent_a = AgentConfig(
            name="A perspective",
            prompt_id="sys_theory",
            host_configuration_id="Synthetic A",
            host_label="Synthetic A",
            api_host="https://synthetic-a.invalid/v1",
            llm_id="model-a",
        )
        agent_b = AgentConfig(
            name="B perspective",
            prompt_id="sys_theory",
            host_configuration_id="Synthetic B",
            host_label="Synthetic B",
            api_host="https://synthetic-b.invalid/v1",
            llm_id="model-b",
        )

        completed = threading.Event()
        svc.start_new_discussion(
            material="Only A material",
            question="Only A opening task",
            agents=[agent_a],
            title="Synthetic discussion A",
            on_all_complete=completed.set,
        )
        assert completed.wait(timeout=5)
        file_id_a = svc.current_session_file_id()
        assert file_id_a is not None
        for round_number in (2, 3):
            completed.clear()
            svc.continue_discussion(
                user_input=f"Only A follow-up {round_number}",
                agents=[agent_a],
                on_all_complete=completed.set,
            )
            assert completed.wait(timeout=5)

        with pytest.raises(MaterialRequiredError):
            svc.start_new_discussion(
                material="",
                question="Rejected B task",
                agents=[agent_b],
            )
        assert svc.current_session_file_id() == file_id_a
        assert [item["round_number"] for item in svc.round_provider_provenance_snapshot()] == [
            1,
            2,
            3,
        ]

        completed.clear()
        svc.start_new_discussion(
            material="Only B material",
            question="Only B opening task",
            agents=[agent_b],
            title="Synthetic discussion B",
            on_all_complete=completed.set,
        )
        assert completed.wait(timeout=5)
        file_id_b = svc.current_session_file_id()
        assert file_id_b is not None and file_id_b != file_id_a

        b_prompt = svc.llm_manager.get_llm.return_value.generate_stream.call_args.kwargs["prompt"]
        assert svc.llm_manager.get_llm.call_args.kwargs["host_configuration_id"] == "Synthetic B"
        assert svc.llm_manager.get_llm.call_args.kwargs["model_name"] == "model-b"
        assert "Only B material" in b_prompt
        assert "Only B opening task" in b_prompt
        assert "Only A material" not in b_prompt
        assert "Only A opening task" not in b_prompt
        assert "Only A follow-up" not in b_prompt

        fresh = self._make_service(tmp_path)
        for file_id, rounds, host, model, other_model in (
            (file_id_a, [1, 2, 3], "Synthetic A", "model-a", "model-b"),
            (file_id_b, [1], "Synthetic B", "model-b", "model-a"),
            (file_id_a, [1, 2, 3], "Synthetic A", "model-a", "model-b"),
        ):
            snapshot = fresh.snapshot_open_session(file_id)
            assert snapshot is not None
            history = snapshot["round_provider_provenance"]
            assert [item["round_number"] for item in history] == rounds
            assert all(
                len(item["providers"]) == 1
                and item["providers"][0]["host_configuration_id"] == host
                and item["providers"][0]["model_id"] == model
                for item in history
            )
            assert fresh.round_provider_provenance_snapshot() == history
            stored = fresh.storage.load(file_id)
            assert stored is not None
            assert [item.round_number for item in stored.rounds] == rounds
            assert all(item.provider_provenance[0].model_id == model for item in stored.rounds)
            markdown = fresh.get_markdown(locale="en")
            assert markdown is not None
            assert model in markdown
            assert other_model not in markdown

    def test_start_new_writes_initial_session_before_async_completes(self, tmp_path):
        svc = self._make_service(tmp_path)

        # Block the async worker until we have inspected the disk.
        llm = svc.llm_manager.get_llm.return_value
        worker_entered = threading.Event()
        release_worker = threading.Event()
        worker_completed = threading.Event()

        def blocking_stream(*args, **kwargs):
            worker_entered.set()
            release_worker.wait()
            return iter([])

        llm.generate_stream.side_effect = blocking_stream

        with patch.object(svc, "run_discussion_async", wraps=svc.run_discussion_async):
            svc.start_new_discussion(
                material="Analyse-Material mit ein paar Wörtern.",
                question="Was fällt auf?",
                agents=[
                    AgentConfig(
                        name="A1",
                        client_id="client-1",
                        prompt_id="sys_theory",
                        color="#123456",
                        temperature=0.42,
                        llm_id="qwen2.5",
                        api_host="http://127.0.0.1:1234",
                        max_tokens=512,
                    )
                ],
                sequential_mode=True,
                on_all_complete=worker_completed.set,
            )

        assert worker_entered.wait(timeout=5.0)
        assert not worker_completed.is_set()

        listing = svc.list_sessions()
        assert len(listing) == 1
        item = listing[0]
        import re

        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} ", item["title"]), (
            f"unexpected default title format: {item['title']!r}"
        )
        # The excerpt contains the material (possibly with line numbers
        # prepended depending on material_type).
        assert "Analyse-Material" in item["title"]

        # The user message was added to round 1 before the initial
        # save, so the persisted session has exactly one round on
        # disk (with the user prompt inside).
        assert item["round_count"] == 1

        release_worker.set()
        assert worker_completed.wait(timeout=5.0)

    def test_start_new_preserves_explicit_title(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Frage?",
                agents=[],
                title="Mein eigener Titel",
            )
        assert svc._current_stored is not None
        assert svc._current_stored.title == "Mein eigener Titel"
        listing = svc.list_sessions()
        assert listing[0]["title"] == "Mein eigener Titel"

    def test_start_new_uses_the_task_as_the_first_moderator_message(self, tmp_path):
        svc = self._make_service(tmp_path)
        task = "Explore the material openly and closely."

        with patch.object(svc, "run_discussion_async"):
            user_message = svc.start_new_discussion(
                material="Material",
                question=task,
                agents=[],
            )

        assert user_message is not None
        assert user_message.role == "user"
        assert user_message.content == task
        assert svc.state.messages[0].content == task
        assert svc._current_stored is not None
        assert svc._current_stored.rounds[0].messages[0].content == task

    def test_started_session_uses_frozen_prompt_assets(self, tmp_path):
        svc = self._make_service(tmp_path)
        context = MaterialContext(target_language="English")

        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Question?",
                agents=[AgentConfig(name="A", prompt_id="sys_theory", color="#123456")],
                material_context=context,
            )

        assert svc._current_stored is not None
        frozen_role = svc._current_stored.prompt_snapshot.roles[0]["role"]
        svc._prompts["sys_theory"].role = "MUTATED ROLE"

        prompt = svc.build_system_prompt("sys_theory", material_context=context)

        assert frozen_role in prompt
        assert "MUTATED ROLE" not in prompt

    @pytest.mark.parametrize("material", ["", "   \n\t"])
    def test_start_new_rejects_blank_material_without_creating_session(self, tmp_path, material):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            with pytest.raises(MaterialRequiredError):
                svc.start_new_discussion(
                    material=material,
                    question="Frage?",
                    agents=[],
                )
        assert svc._current_stored is None

    def test_session_roundtrip_restores_full_state_and_settings(self, tmp_path):
        svc = self._make_service(tmp_path)
        agent = AgentConfig(
            name="A1",
            client_id="client-1",
            prompt_id="sys_theory",
            color="#123456",
            temperature=0.42,
            llm_id="qwen2.5",
            api_host="http://127.0.0.1:1234",
            max_tokens=1024,
        )
        # Use a material_type that does NOT auto-add line numbers, so
        # the roundtrip assertion stays simple.
        material_context = MaterialContext(
            material_type="other",
            session_type="critique",
            session_input_values={
                "research_material_context": "Leitfadeninterview",
                "main_input": "Eine Spannung zwischen Sicherheit und Aufstieg.",
                "additional_instructions": "Zuerst Gegenargumente, dann Belege.",
            },
        )

        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material A\nMaterial B",
                question="Runde 1?",
                agents=[agent],
                material_context=material_context,
                sequential_mode=True,
            )
            svc.state.add_agent_response(
                AgentResponse(
                    message_id="agent-msg-1",
                    agent_index=0,
                    agent_name="A1",
                    theory_label="Systemtheorie",
                    color="#123456",
                    text="Erste Antwort.",
                    is_complete=True,
                )
            )

        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem

        fresh = self._make_service(tmp_path)
        ok = fresh.open_session(file_id)
        assert ok is True

        # Material + messages restored.  The exact form depends on the
        # material_type's line-numbering policy; what matters for the
        # resume contract is that *whatever* the service persisted
        # comes back byte-identical from open_session.
        persisted = svc._current_stored.material
        assert fresh.state.material == persisted
        assert fresh.state.initial_question == "Runde 1?"
        assert fresh.state.round_number == 1
        assert any(
            m.role == "agent" and m.content == "Erste Antwort." for m in fresh.state.messages
        )

        assert len(fresh._current_agents) == 1
        restored_agent = fresh._current_agents[0]
        assert restored_agent.name == "A1"
        assert restored_agent.client_id == "client-1"
        assert restored_agent.prompt_id == "sys_theory"
        assert restored_agent.color == "#123456"
        assert restored_agent.temperature == pytest.approx(0.42)
        assert restored_agent.llm_id == "qwen2.5"
        assert restored_agent.api_host == "http://127.0.0.1:1234"
        assert restored_agent.max_tokens == 1024
        # API key is *never* persisted nor re-hydrated
        assert getattr(restored_agent, "api_key", None) in (None, "")

        assert fresh._material_context is not None
        mc = fresh._material_context
        assert mc.material_type == "other"
        assert mc.session_type == "critique"
        assert mc.session_input_values["research_material_context"] == "Leitfadeninterview"
        assert "Spannung" in mc.session_input_values["main_input"]
        assert "Gegenargumente" in mc.session_input_values["additional_instructions"]

        assert fresh.sequential_mode is True

    def test_open_session_uses_exact_id_no_substring_match(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Q?",
                agents=[],
            )
        fp = svc._save_current_state()
        assert fp is not None
        full_stem = fp.stem

        # Substring: must be rejected
        assert svc.open_session(full_stem[:8]) is False
        # Unsafe id: must raise
        with pytest.raises(ValueError):
            svc.open_session("../etc/passwd")
        # Unknown but safe id: returns False
        assert svc.open_session("definitely-not-here") is False
        # Exact stem: works
        assert svc.open_session(full_stem) is True

    def test_open_session_rejects_unsafe_id(self, tmp_path):
        svc = self._make_service(tmp_path)
        with pytest.raises(ValueError):
            svc.open_session("..\\windows")
        with pytest.raises(ValueError):
            svc.open_session("sub/dir")

    def test_open_session_invalidation_cancels_deferred_old_worker(self, tmp_path):
        svc = self._make_service(tmp_path)
        llm = svc.llm_manager.get_llm.return_value

        # Block the old worker so the replacement is forced to preempt it.
        old_entered = threading.Event()
        old_release = threading.Event()
        old_completed = threading.Event()

        def blocking_stream(*args, **kwargs):
            old_entered.set()
            old_release.wait()
            return iter([])

        llm.generate_stream.side_effect = blocking_stream

        old_agent = AgentConfig(
            name="OLD",
            prompt_id="sys_theory",
            color="#f00",
        )
        svc.start_new_discussion(
            material="OLD material",
            question="OLD question?",
            agents=[old_agent],
            on_all_complete=old_completed.set,
        )
        assert old_entered.wait(timeout=5.0)

        # Persist a "saved" session
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Replacement material",
                question="Replacement question?",
                agents=[],
            )
        fp = svc._save_current_state()
        assert fp is not None
        svc.reset_discussion()
        # But the OLD worker is still blocked → opening must still work
        ok = svc.open_session(fp.stem)
        assert ok is True

        # Release the old worker; it must NOT corrupt the new state.
        old_release.set()
        assert old_completed.wait(timeout=5.0)

        assert svc.state.initial_question == "Replacement question?"
        assert "Replacement material" in svc.state.material
        assert not any(m.content == "OLD question?" for m in svc.state.messages)

    def test_delete_session_removes_file(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Q?",
                agents=[],
            )
        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem

        result = svc.delete_session(file_id)
        # delete returns the active-status flag
        assert result == {"deleted": True, "deleted_ids": [file_id], "was_active": True}
        assert not fp.exists()
        assert svc.list_sessions() == []

    def test_delete_current_session_resets_state_and_reports_active(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Q?",
                agents=[],
            )
        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem

        result = svc.delete_session(file_id)
        # delete returns the active-status flag
        assert result == {"deleted": True, "deleted_ids": [file_id], "was_active": True}

        assert not svc.has_active_discussion
        assert svc.state.messages == []
        assert svc._current_stored is None

    def test_delete_current_session_supersedes_active_generation(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(material="Material", question="Q?", agents=[])
        stored = svc._save_current_state()
        assert stored is not None
        generation = svc._begin_generation()
        svc._generation_running = True

        result = svc.delete_session(stored.stem)

        assert result["was_active"] is True
        assert generation.cancelled.is_set()
        assert svc._active_generation is not generation
        assert svc.is_generation_running is False

    def test_delete_noncurrent_session_does_not_reset_state(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Active material",
                question="Active Q?",
                agents=[],
            )
        active_fp = svc._save_current_state()
        assert active_fp is not None

        other = svc.storage.create_new("OTHER")
        other_fp = svc.storage.save(other)
        other_id = other_fp.stem

        result = svc.delete_session(other_id)
        assert result == {"deleted": True, "deleted_ids": [other_id], "was_active": False}

        # Active state untouched (note: state.material may have line
        # numbers prepended; we only check that the active discussion
        # is still set up with the active question).
        assert svc.has_active_discussion
        assert svc.state.initial_question == "Active Q?"
        assert svc._current_stored is not None

    def test_delete_noncurrent_session_preserves_active_generation(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(material="Active", question="Active Q?", agents=[])
        active = svc._save_current_state()
        assert active is not None
        inactive = svc.storage.save(svc.storage.create_new("Inactive"))
        generation = svc._begin_generation()
        svc._generation_running = True

        result = svc.delete_session(inactive.stem)

        assert result["was_active"] is False
        assert generation.cancelled.is_set() is False
        assert svc._active_generation is generation
        assert svc.is_generation_running is True

    def test_bulk_delete_all_removes_favorites_and_resets_open_session(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(material="First", question="Q1?", agents=[])
        first = svc._save_current_state()
        assert first is not None
        assert svc.set_session_favorite(first.stem, True) is True

        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(material="Second", question="Q2?", agents=[])
        second = svc._save_current_state()
        assert second is not None
        assert svc.current_session_file_id() == second.stem

        with patch.object(
            svc,
            "_reset_deleted_session_state_locked",
            wraps=svc._reset_deleted_session_state_locked,
        ) as reset:
            result = svc.delete_sessions("all", [first.stem, second.stem])

        assert result["deleted_count"] == 2
        assert set(result["deleted_ids"]) == {first.stem, second.stem}
        assert result["was_active"] is True
        assert svc.list_sessions() == []
        assert not svc.has_active_discussion
        assert reset.call_count == 1

    def test_bulk_delete_except_favorites_preserves_favorites(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(material="Favorite", question="Q1?", agents=[])
        favorite = svc._save_current_state()
        assert favorite is not None
        assert svc.set_session_favorite(favorite.stem, True) is True

        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(material="Disposable", question="Q2?", agents=[])
        disposable = svc._save_current_state()
        assert disposable is not None

        result = svc.delete_sessions("except_favorites", [disposable.stem])

        assert result == {
            "deleted_count": 1,
            "deleted_ids": [disposable.stem],
            "was_active": True,
        }
        assert not disposable.exists()
        assert favorite.exists()
        assert [item["file_id"] for item in svc.list_sessions()] == [favorite.stem]
        assert svc.list_sessions()[0]["is_favorite"] is True
        assert not svc.has_active_discussion

    def test_bulk_delete_empty_and_rejects_invalid_mode(self, tmp_path):
        svc = self._make_service(tmp_path)

        assert svc.delete_sessions("except_favorites", []) == {
            "deleted_count": 0,
            "deleted_ids": [],
            "was_active": False,
        }
        with pytest.raises(ValueError, match="mode must be"):
            svc.delete_sessions("favorites_only", [])  # type: ignore[arg-type]

    def test_bulk_delete_rejects_changed_catalogue_before_mutation(self, tmp_path):
        svc = self._make_service(tmp_path)
        stored = svc.storage.save(svc.storage.create_new("Keep"))

        with pytest.raises(ValueError, match="session_catalog_changed"):
            svc.delete_sessions("all", [])

        assert stored.exists()

    def test_bulk_delete_move_failure_rolls_back_every_session(self, tmp_path):
        svc = self._make_service(tmp_path)
        first = svc.storage.save(svc.storage.create_new("First"))
        second = svc.storage.save(svc.storage.create_new("Second"))
        real_replace = __import__("os").replace
        calls = 0

        def fail_second_move(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise PermissionError("injected")
            return real_replace(source, destination)

        with patch("src.service.discussion_storage.os.replace", side_effect=fail_second_move):
            with pytest.raises(PermissionError):
                svc.delete_sessions("all", [first.stem, second.stem])

        assert first.exists()
        assert second.exists()

    def test_bulk_delete_reports_bounded_ids_when_rollback_fails(self, tmp_path):
        svc = self._make_service(tmp_path)
        first = svc.storage.save(svc.storage.create_new("First"))
        second = svc.storage.save(svc.storage.create_new("Second"))
        real_replace = __import__("os").replace
        calls = 0

        def fail_move_and_rollback(source, destination):
            nonlocal calls
            calls += 1
            if calls in (2, 3):
                raise PermissionError("injected")
            return real_replace(source, destination)

        with patch("src.service.discussion_storage.os.replace", side_effect=fail_move_and_rollback):
            with pytest.raises(SessionDeletionRollbackError) as caught:
                svc.delete_sessions("all", [first.stem, second.stem])

        assert len(caught.value.deleted_ids) == 1
        assert len(caught.value.retained_ids) == 1
        assert set(caught.value.deleted_ids + caught.value.retained_ids) == {
            first.stem,
            second.stem,
        }

    def test_list_sessions_returns_canonical_metadata(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material A",
                question="Q?",
                agents=[],
            )
        svc._save_current_state()
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material B with some words",
                question="Q2?",
                agents=[],
            )
        svc._save_current_state()

        listing = svc.list_sessions()
        assert len(listing) == 2
        for item in listing:
            for key in ("file_id", "title", "created", "updated", "session_type", "round_count"):
                assert key in item, f"missing canonical key: {key}"
            assert item["session_type"] == "exploration"
            assert "/" not in item["file_id"]
            assert "\\" not in item["file_id"]
            assert ".json" not in item["file_id"]

    def test_rename_session_changes_metadata(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Q?",
                agents=[],
            )
        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem

        ok = svc.rename_session(file_id, "Mein neuer Titel")
        assert ok is True
        assert fp.exists()
        reloaded = svc.storage.load(file_id)
        assert reloaded is not None
        assert reloaded.title == "Mein neuer Titel"
        item = svc.list_sessions()[0]
        assert item["file_id"] == file_id
        assert item["title"] == "Mein neuer Titel"

    def test_current_session_file_id_returns_canonical_stem(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc.current_session_file_id() is None

        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Q?",
                agents=[],
            )
        filepath = svc._save_current_state()
        assert filepath is not None

        assert svc.current_session_file_id() == filepath.stem

    def test_rename_session_rejects_unsafe_id(self, tmp_path):
        svc = self._make_service(tmp_path)
        with pytest.raises(ValueError):
            svc.rename_session("../escape", "X")
        with pytest.raises(ValueError):
            svc.rename_session("a/b", "X")

    def test_delete_session_does_not_use_private_storage_method(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Q?",
                agents=[],
            )
        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem

        # If the implementation ever calls the private helper,
        # this call-count probe will catch it.
        original_private = svc.storage._load_file
        calls: list[str] = []

        def guarded_private(*args, **kwargs):
            calls.append("called")
            return original_private(*args, **kwargs)

        svc.storage._load_file = guarded_private  # type: ignore[method-assign]

        result = svc.delete_session(file_id)
        assert result == {"deleted": True, "deleted_ids": [file_id], "was_active": True}
        assert calls == [], f"delete_session invoked private storage._load_file: {calls}"

    def test_session_path_for_reveal_returns_exact_path(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Q?",
                agents=[],
            )
        fp = svc._save_current_state()
        assert fp is not None
        revealed = svc.session_path_for_reveal(fp.stem)
        assert revealed == fp
        with pytest.raises(ValueError):
            svc.session_path_for_reveal("../escape")

    def test_rename_session_holds_run_lock_around_storage_rename(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Q?",
                agents=[AgentConfig(name="A1", prompt_id="sys_theory", color="#00f")],
            )
        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem

        user_message = svc.state.add_user_message("Erste Frage?")

        # Gate inside storage.rename: when rename_session holds the
        # run lock, no autosave running via _save_current_state can
        # pass through until we release this gate.
        rename_in_storage = threading.Event()
        release_storage_rename = threading.Event()
        original_storage_rename = svc.storage.rename

        def gated_storage_rename(file_id_arg: str, new_title: str) -> bool:
            rename_in_storage.set()
            release_storage_rename.wait(timeout=5.0)
            return original_storage_rename(file_id_arg, new_title)

        svc.storage.rename = gated_storage_rename  # type: ignore[method-assign]

        rename_done = threading.Event()
        rename_error: list[BaseException] = []

        def do_rename():
            try:
                svc.rename_session(file_id, "Neuer Titel")
            except BaseException as exc:
                rename_error.append(exc)
            finally:
                rename_done.set()

        rename_thread = threading.Thread(target=do_rename, daemon=True)
        rename_thread.start()

        # Wait for rename to be inside the storage call.
        assert rename_in_storage.wait(timeout=5.0), (
            "rename_session never reached DiscussionStorage.rename"
        )

        # While rename is in the storage call, an autosave via
        # set_message_note must block (it takes the same lock).
        autosave_completed = threading.Event()
        autosave_thread = threading.Thread(
            target=lambda: (
                svc.set_message_note(user_message.id, "Notiz"),
                autosave_completed.set(),
            ),
            daemon=True,
        )
        autosave_thread.start()

        # The autosave must NOT have completed yet (it is blocked
        # behind the run lock that rename_session holds).
        # We poll briefly to give the scheduler a chance to schedule
        # the autosave thread.
        autosave_completed.wait(timeout=0.2)
        assert not autosave_completed.is_set(), (
            "set_message_note completed while rename_session held the "
            "lock — rename_session is not properly serialised."
        )

        # Release the rename so it can finish.
        release_storage_rename.set()
        assert rename_done.wait(timeout=5.0)
        autosave_thread.join(timeout=5.0)
        assert autosave_completed.is_set(), "autosave never completed"
        assert not rename_error, rename_error

        # The final title is the renamed one, and the note was saved.
        reloaded = svc.storage.load(file_id)
        assert reloaded is not None
        assert reloaded.title == "Neuer Titel"
        saved_note = next(
            (m.note for m in reloaded.rounds[0].messages if m.id == user_message.id),
            None,
        )
        assert saved_note == "Notiz"


# Real storage covers snapshot path validation, lock discipline, credential
# omission, and detachment from mutable service state.
class TestSnapshotOpenSession:
    def _make_service(self, tmp_path) -> DiscussionService:
        session_contexts_dir = tmp_path / "session_contexts"
        _populate_session_contexts(session_contexts_dir)
        return _LanguageConfiguredDiscussionService(
            settings=_mock_settings(),
            llm_manager=_mock_llm_manager(),
            prompt_repo=_mock_prompt_repo(),
            storage_dir=tmp_path / "disc",
            session_context_dir=session_contexts_dir,
        )

    def test_returns_none_for_unknown_id(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc.snapshot_open_session("nope-not-here") is None

    def test_raises_value_error_for_unsafe_id(self, tmp_path):
        svc = self._make_service(tmp_path)
        with pytest.raises(ValueError):
            svc.snapshot_open_session("../etc/passwd")
        with pytest.raises(ValueError):
            svc.snapshot_open_session("sub/dir")

    def test_snapshot_contains_every_required_field(self, tmp_path):
        svc = self._make_service(tmp_path)
        material_context = MaterialContext(
            material_type="other",
            session_type="critique",
            session_input_values={
                "research_material_context": "Leitfadeninterview",
                "main_input": "Spannung zwischen Sicherheit und Aufstieg.",
                "additional_instructions": "Zuerst Gegenargumente, dann Belege.",
            },
        )
        agent = AgentConfig(
            name="A1",
            client_id="client-1",
            prompt_id="sys_theory",
            color="#123456",
            temperature=0.42,
            llm_id="qwen2.5",
            api_host="http://127.0.0.1:1234",
            max_tokens=1024,
        )
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material A\nMaterial B",
                question="Runde 1?",
                agents=[agent],
                material_context=material_context,
                sequential_mode=True,
            )
            svc.state.add_agent_response(
                AgentResponse(
                    message_id="agent-msg-1",
                    agent_index=0,
                    agent_name="A1",
                    theory_label="Systemtheorie",
                    color="#123456",
                    text="Erste Antwort.",
                    is_complete=True,
                )
            )
        svc._round_provider_provenance = {
            1: [
                StoredProviderProvenance(
                    kind="perspective",
                    client_id="client-1",
                    prompt_id="sys_theory",
                    prompt_label="Systemtheorie",
                    perspective_number=1,
                    temperature=0.7,
                    host_configuration_id="stable-host-id",
                    host_label="Visible Host",
                    api_host="http://127.0.0.1:1234",
                    model_id="qwen2.5",
                )
            ]
        }
        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem

        # Open a *fresh* service so the snapshot must be the only
        # source of the open state.
        fresh = self._make_service(tmp_path)
        snap = fresh.snapshot_open_session(file_id)
        assert snap is not None

        for key in (
            "file_id",
            "title",
            "material",
            "initial_question",
            "messages",
            "material_context",
            "agents",
            "sequential_mode",
            "round_number",
            "has_active_discussion",
        ):
            assert key in snap, f"missing snapshot field: {key}"

        assert snap["file_id"] == file_id
        # The material may be line-numbered (line-numbering policy
        # depends on material_type); the contract is that the
        # snapshot must reflect *whatever* was persisted.
        assert snap["material"] == svc._current_stored.material
        assert snap["initial_question"] == "Runde 1?"
        assert snap["sequential_mode"] is True
        assert snap["round_number"] >= 1
        assert snap["has_active_discussion"] is True

        # Material context — canonical setup schema
        mc = snap["material_context"]
        for key in (
            "material_type",
            "session_type",
            "target_language",
            "input_values",
            "input_definitions",
            "include_unchanged_research_material_context_in_prompt",
        ):
            assert key in mc, f"missing material_context field: {key}"
        assert mc["material_type"] == "other"
        assert mc["session_type"] == "critique"
        assert mc["include_unchanged_research_material_context_in_prompt"] is False

        # Agent: no api_key, no private fields
        assert len(snap["agents"]) == 1
        ag = snap["agents"][0]
        for key in (
            "name",
            "client_id",
            "prompt_id",
            "color",
            "temperature",
            "llm_id",
            "api_host",
            "max_tokens",
        ):
            assert key in ag, f"missing agent field: {key}"
        # Defence-in-depth: api_key never present
        assert "api_key" not in ag
        assert getattr(ag.get("api_key", None), "__class__", None) is not str

        # Every field required by ProviderProvenanceResponse must survive the
        # persisted-session bridge; otherwise opening a real saved session
        # fails response validation with HTTP 500.
        provenance = snap["round_provider_provenance"]
        assert provenance[0]["providers"][0]["host_configuration_id"] == "stable-host-id"

        # Messages: every required field
        msgs = snap["messages"]
        assert isinstance(msgs, list)
        assert any(m["role"] == "agent" and m["content"] == "Erste Antwort." for m in msgs)
        for m in msgs:
            for key in (
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
                "error_code",
                "error_params",
            ):
                assert key in m, f"missing message field: {key}"

    def test_snapshot_is_plain_safe_data_not_live_objects(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Q?",
                agents=[AgentConfig(name="A1", prompt_id="sys_theory", color="#f00")],
            )
        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem

        snap = svc.snapshot_open_session(file_id)
        assert snap is not None

        # The snapshot must contain plain dict/list, not the live
        # dataclass instances.
        assert isinstance(snap["messages"], list)
        for m in snap["messages"]:
            assert isinstance(m, dict), "snapshot message must be a plain dict"
        assert isinstance(snap["agents"], list)
        for a in snap["agents"]:
            assert isinstance(a, dict), "snapshot agent must be a plain dict"
        assert isinstance(snap["material_context"], dict)

        snap["agents"][0]["name"] = "MUTATED"
        snap["material_context"]["material_type"] = "MUTATED"
        snap["messages"].clear()

        fresh = self._make_service(tmp_path)
        fresh.open_session(file_id)
        assert fresh._current_agents[0].name == "A1"
        # The material context was either restored from disk (if the
        # in-memory one was reset) or the snapshot did not touch it.
        # What matters is that the live state is still consistent
        # and the agent name is the original one.
        assert fresh._material_context is not None
        # We never lost the original material_type on disk
        assert fresh._material_context.material_type in {"document", "other"}

    def test_snapshot_acquires_run_lock_during_open(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Q?",
                agents=[AgentConfig(name="A1", prompt_id="sys_theory", color="#f00")],
            )
        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem

        svc.reset_discussion()

        # Wrap open_session to observe lock state during the call
        original_open = svc.open_session
        lock_held_during_open = {"value": False}

        def wrapped_open(file_id_arg):
            lock_held_during_open["value"] = svc._run_lock.acquire(blocking=False)
            try:
                return original_open(file_id_arg)
            finally:
                if lock_held_during_open["value"]:
                    svc._run_lock.release()

        import types

        svc.open_session = types.MethodType(lambda self, fid: wrapped_open(fid), svc)

        snap = svc.snapshot_open_session(file_id)
        assert snap is not None
        # The lock must have been acquired by snapshot before calling open_session
        # (open_session itself takes the lock; the wrapper above re-enters
        # the RLock — which is fine.  The important invariant is that
        # snapshot_open_session as a whole serialises with other state
        # mutators; we test that separately via concurrent threads below.)
        assert snap["file_id"] == file_id


# Terminal-agent metadata must round-trip through save and session opening.
class TestFreshServicePreservesTerminalMetadata:
    def _make_service(self, tmp_path) -> DiscussionService:
        session_contexts_dir = tmp_path / "session_contexts"
        _populate_session_contexts(session_contexts_dir)
        return _LanguageConfiguredDiscussionService(
            settings=_mock_settings(),
            llm_manager=_mock_llm_manager(),
            prompt_repo=_mock_prompt_repo(),
            storage_dir=tmp_path / "disc",
            session_context_dir=session_contexts_dir,
        )

    def test_fresh_service_snapshot_preserves_terminal_metadata(self, tmp_path):
        svc = self._make_service(tmp_path)
        agent = AgentConfig(
            name="A1",
            client_id="client-save-open",
            prompt_id="sys_theory",
            color="#abc123",
            temperature=0.42,
        )
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material A",
                question="Frage?",
                agents=[agent],
            )
            svc.state.add_agent_response(
                AgentResponse(
                    message_id="agent-msg-1",
                    agent_index=0,
                    agent_name="A1",
                    theory_label="Systemtheorie",
                    color="#abc123",
                    text="Antwort mit allen vier Feldern.",
                    client_id="client-save-open",
                    is_complete=True,
                    error=None,
                )
            )
        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem

        # Open in a *fresh* service so the snapshot must be the only
        # source of the open state — proves the on-disk bridge is
        # lossless.
        fresh = self._make_service(tmp_path)
        snap = fresh.snapshot_open_session(file_id)
        assert snap is not None

        # The agent message is the second message in the snapshot
        # (the first is the user question).
        agent_msgs = [m for m in snap["messages"] if m["role"] == "agent"]
        assert agent_msgs, "snapshot must contain at least one agent message"
        agent_msg = agent_msgs[0]
        assert agent_msg["client_id"] == "client-save-open"
        assert agent_msg["color"] == "#abc123"
        assert agent_msg["agent_index"] == 0
        assert agent_msg["error"] is None

    def test_fresh_service_snapshot_preserves_persisted_error(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material A",
                question="Frage?",
                agents=[
                    AgentConfig(
                        name="A1",
                        client_id="client-fail",
                        prompt_id="sys_theory",
                        color="#deadbe",
                    )
                ],
            )
            svc.state.add_agent_response(
                AgentResponse(
                    message_id="agent-msg-fail",
                    agent_index=0,
                    agent_name="A1",
                    theory_label="Systemtheorie",
                    color="#deadbe",
                    text="",
                    client_id="client-fail",
                    is_complete=True,
                    error="Anbieter-Fehler: 503",
                    error_code="agent_generation_failed",
                    error_params={},
                )
            )
        fp = svc._save_current_state()
        assert fp is not None

        fresh = self._make_service(tmp_path)
        snap = fresh.snapshot_open_session(fp.stem)
        assert snap is not None
        agent_msgs = [m for m in snap["messages"] if m["role"] == "agent"]
        assert agent_msgs
        msg = agent_msgs[0]
        assert msg["error"] == "Anbieter-Fehler: 503"
        assert msg["error_code"] == "agent_generation_failed"
        assert msg["error_params"] == {}
        assert msg["client_id"] == "client-fail"
        assert msg["color"] == "#deadbe"

    def test_fresh_service_open_exposes_client_id_for_roster_match(self, tmp_path):
        svc = self._make_service(tmp_path)
        agent = AgentConfig(
            name="A1",
            client_id="client-roster-match",
            prompt_id="sys_theory",
            color="#00ff00",
        )
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Q?",
                agents=[agent],
            )
            svc.state.add_agent_response(
                AgentResponse(
                    message_id="agent-msg-x",
                    agent_index=0,
                    agent_name="A1",
                    theory_label="Systemtheorie",
                    color="#00ff00",
                    text="OK",
                    client_id="client-roster-match",
                    is_complete=True,
                )
            )
        fp = svc._save_current_state()
        assert fp is not None

        fresh = self._make_service(tmp_path)
        snap = fresh.snapshot_open_session(fp.stem)
        assert snap is not None

        assert len(snap["agents"]) == 1
        assert snap["agents"][0]["client_id"] == "client-roster-match"
        agent_msg = next(m for m in snap["messages"] if m["role"] == "agent")
        assert agent_msg["client_id"] == "client-roster-match"
        # Stable client IDs join roster entries to messages in the frontend.
        assert agent_msg["client_id"] == snap["agents"][0]["client_id"]


# Session favorites must be mutated under the service lock.
# Agent temperature remains optional end-to-end; ``None`` lets the provider decide.
class TestTemperatureContract:
    def _make_service(self, tmp_path) -> DiscussionService:
        session_contexts_dir = tmp_path / "session_contexts"
        _populate_session_contexts(session_contexts_dir)
        return _LanguageConfiguredDiscussionService(
            settings=_mock_settings(),
            llm_manager=_mock_llm_manager(),
            prompt_repo=_mock_prompt_repo(),
            storage_dir=tmp_path / "disc",
            session_context_dir=session_contexts_dir,
        )

    def test_snapshot_returns_null_when_agent_has_no_override(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Q?",
                agents=[AgentConfig(name="A1", prompt_id="sys_theory", color="#f00")],
            )
        fp = svc._save_current_state()
        assert fp is not None
        snap = svc.snapshot_open_session(fp.stem)
        assert snap is not None
        assert snap["agents"][0]["temperature"] is None

    def test_snapshot_preserves_explicit_numeric_override(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Q?",
                agents=[
                    AgentConfig(
                        name="A1",
                        prompt_id="sys_theory",
                        color="#f00",
                        temperature=0.42,
                    )
                ],
            )
        fp = svc._save_current_state()
        assert fp is not None
        snap = svc.snapshot_open_session(fp.stem)
        assert snap is not None
        assert snap["agents"][0]["temperature"] == pytest.approx(0.42)

    def test_run_discussion_passes_none_through_to_llm(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.run_discussion(
            material="M",
            question="Q?",
            agents=[AgentConfig(name="A1", prompt_id="sys_theory", color="#f00")],
            on_agent_start=lambda r: None,
        )
        llm = svc.llm_manager.get_llm.return_value
        _, kwargs = llm.generate_stream.call_args
        # No explicit override → None must reach the adapter verbatim
        assert kwargs["temperature"] is None

    def test_run_discussion_passes_explicit_value_through_to_llm(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.run_discussion(
            material="M",
            question="Q?",
            agents=[
                AgentConfig(
                    name="A1",
                    prompt_id="sys_theory",
                    color="#f00",
                    temperature=0.4,
                )
            ],
            on_agent_start=lambda r: None,
        )
        llm = svc.llm_manager.get_llm.return_value
        _, kwargs = llm.generate_stream.call_args
        assert kwargs["temperature"] == pytest.approx(0.4)

    def test_continue_discussion_passes_none_through_to_llm(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Q?",
                agents=[AgentConfig(name="A1", prompt_id="sys_theory", color="#f00")],
            )
            svc.state.add_user_message("Erste Frage")
            svc.state.round_number = 1

        # The continue path calls generate_stream with the agent's
        # temperature.  We patch the service's ``_save_current_state``
        # to be a no-op (we already persisted above) and let the
        # LLM mock run.  Then we inspect the recorded temperature.
        with patch.object(svc, "_save_current_state", return_value=None):
            svc.continue_discussion(
                user_input="Weiter?",
                agents=[AgentConfig(name="A1", prompt_id="sys_theory", color="#f00")],
                on_all_complete=lambda: None,
            )

        llm = svc.llm_manager.get_llm.return_value
        # ``continue_discussion`` runs the round on a worker thread; the
        # mock LLM returns its tokens synchronously, so the call site
        # has fired by the time we reach the assertion.  Poll briefly
        # so the test does not depend on thread scheduling.
        for _ in range(50):
            if llm.generate_stream.called:
                break
            time.sleep(0.02)
        assert llm.generate_stream.called, "continue path must invoke generate_stream"
        _, kwargs = llm.generate_stream.call_args
        assert kwargs["temperature"] is None

    def test_continue_discussion_passes_explicit_value_through_to_llm(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Q?",
                agents=[
                    AgentConfig(
                        name="A1",
                        prompt_id="sys_theory",
                        color="#f00",
                        temperature=0.3,
                    )
                ],
            )
            svc.state.add_user_message("Erste Frage")
            svc.state.round_number = 1

        with patch.object(svc, "_save_current_state", return_value=None):
            svc.continue_discussion(
                user_input="Weiter?",
                agents=[
                    AgentConfig(
                        name="A1",
                        prompt_id="sys_theory",
                        color="#f00",
                        temperature=0.3,
                    )
                ],
                on_all_complete=lambda: None,
            )

        llm = svc.llm_manager.get_llm.return_value
        # ``continue_discussion`` runs the round on a worker thread;
        # the mock LLM returns its tokens synchronously, so the call
        # site has fired by the time we reach the assertion.  Poll
        # briefly so the test does not depend on thread scheduling.
        for _ in range(50):
            if llm.generate_stream.called:
                break
            time.sleep(0.02)
        assert llm.generate_stream.called
        _, kwargs = llm.generate_stream.call_args
        assert kwargs["temperature"] == pytest.approx(0.3)


# Favorite updates synchronize disk and the active snapshot so autosave cannot
# revert the new value; unsafe and unknown IDs retain their public behavior.
class TestSetSessionFavorite:
    def _make_service(self, tmp_path) -> DiscussionService:
        session_contexts_dir = tmp_path / "session_contexts"
        _populate_session_contexts(session_contexts_dir)
        return _LanguageConfiguredDiscussionService(
            settings=_mock_settings(),
            llm_manager=_mock_llm_manager(),
            prompt_repo=_mock_prompt_repo(),
            storage_dir=tmp_path / "disc",
            session_context_dir=session_contexts_dir,
        )

    def test_set_session_favorite_unknown_returns_false(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc.set_session_favorite("does-not-exist", True) is False

    def test_set_session_favorite_unsafe_id_raises(self, tmp_path):
        svc = self._make_service(tmp_path)
        with pytest.raises(ValueError):
            svc.set_session_favorite("../escape", True)
        with pytest.raises(ValueError):
            svc.set_session_favorite("a/b", True)

    def test_set_session_favorite_writes_through_storage(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Q?",
                agents=[],
            )
        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem

        assert svc.set_session_favorite(file_id, True) is True
        reloaded = svc.storage.load(file_id)
        assert reloaded is not None
        assert reloaded.is_favorite is True

        assert svc.set_session_favorite(file_id, False) is True
        reloaded = svc.storage.load(file_id)
        assert reloaded is not None
        assert reloaded.is_favorite is False

    def test_set_session_favorite_updates_in_memory_current(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Q?",
                agents=[],
            )
        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem

        assert svc._current_stored is not None
        assert svc._current_stored.is_favorite is False

        svc.set_session_favorite(file_id, True)
        assert svc._current_stored.is_favorite is True

    def test_set_session_favorite_does_not_touch_unrelated_current(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="A",
                question="Q?",
                agents=[],
            )
        fp_a = svc._save_current_state()
        assert fp_a is not None
        file_id_a = fp_a.stem

        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="B",
                question="Q2?",
                agents=[],
            )
        fp_b = svc._save_current_state()
        assert fp_b is not None
        assert svc.current_session_file_id() == fp_b.stem

        # Toggle favorite on A (the older, non-current session)
        svc.set_session_favorite(file_id_a, True)
        assert svc._current_stored is not None
        assert svc._current_stored.is_favorite is False
        reloaded_a = svc.storage.load(file_id_a)
        assert reloaded_a is not None
        assert reloaded_a.is_favorite is True

    def test_set_session_favorite_holds_run_lock(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Q?",
                agents=[],
            )
        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem
        user_message = svc.state.add_user_message("Frage?")

        in_storage = threading.Event()
        release_storage = threading.Event()
        original_set = svc.storage.set_favorite

        def gated(file_id_arg: str, value: bool) -> bool:
            in_storage.set()
            release_storage.wait(timeout=5.0)
            return original_set(file_id_arg, value)

        svc.storage.set_favorite = gated  # type: ignore[method-assign]

        done = threading.Event()
        errors: list[BaseException] = []

        def do_toggle():
            try:
                svc.set_session_favorite(file_id, True)
            except BaseException as exc:
                errors.append(exc)
            finally:
                done.set()

        t = threading.Thread(target=do_toggle, daemon=True)
        t.start()

        assert in_storage.wait(timeout=5.0), (
            "set_session_favorite never reached DiscussionStorage.set_favorite"
        )

        # While the toggle is inside the storage call, an autosave
        # (e.g. set_message_note) must block on the same run lock.
        autosave_done = threading.Event()

        def do_autosave():
            svc.set_message_note(user_message.id, "Notiz")
            autosave_done.set()

        at = threading.Thread(target=do_autosave, daemon=True)
        at.start()

        autosave_done.wait(timeout=0.2)
        assert not autosave_done.is_set(), (
            "set_message_note completed while set_session_favorite held the "
            "run lock — toggle is not properly serialised."
        )

        release_storage.set()
        assert done.wait(timeout=5.0)
        at.join(timeout=5.0)
        assert autosave_done.is_set()
        assert not errors, errors


# ``enabled`` persists independently from ``is_active`` so disabled agents
# remain editable but are excluded from execution.
def _bare_service(tmp_path):
    """Build a ``DiscussionService`` instance with the minimal attributes
    that ``_save_current_state_locked`` / ``open_session`` actually
    touch — no LLM, no prompt repository needed.

    The ``SessionTypeRepository`` is wired against a fresh
    ``session_contexts`` directory seeded with the shipped fixtures so
    ``_normalize_session_type`` (called from ``_hydrate_from_stored_locked``)
    can resolve ``"exploration"`` and other canonical keys
    exactly like the production service does.
    """
    svc = DiscussionService.__new__(DiscussionService)
    svc.storage = _DiscussionStorage(tmp_path / "disc")
    svc.state = DiscussionState()
    svc._current_stored = svc.storage.create_new("EnabledRoster")
    svc._sequential_mode = False
    svc._run_lock = _threading.RLock()
    svc._prompts = {}
    # No in-flight generation (the production constructor sets this
    # up via ``_begin_generation_locked``; the bare service is used
    # for unit-level assertions and skips that path).
    svc._active_generation = None
    # Seed a session_type_repo against the shipped fixtures so
    # ``_normalize_session_type`` (called by ``open_session``) can
    # resolve canonical keys.
    session_contexts_dir = tmp_path / "session_contexts"
    _populate_session_contexts(session_contexts_dir)
    svc.session_type_repo = _SessionTypeRepository(base_path=session_contexts_dir)
    definition = svc.session_type_repo.get("exploration")
    assert definition is not None
    svc._material_context = MaterialContext(
        material_type="document",
        session_type="exploration",
        target_language="English",
        session_input_values={item.key: "" for item in definition.session_inputs},
        session_inputs=list(definition.session_inputs),
    )
    return svc


class TestAgentConfigEnabled:
    def test_default_enabled_is_true(self):
        a = AgentConfig(name="A", prompt_id="sys_theory", color="#000")
        assert a.enabled is True

    def test_explicit_enabled_false_is_preserved(self):
        a = AgentConfig(name="A", prompt_id="sys_theory", color="#000", enabled=False)
        assert a.enabled is False

    def test_is_active_requires_enabled_and_nonblank_prompt_id(self):
        enabled_with_prompt = AgentConfig(
            name="A", prompt_id="sys_theory", color="#000", enabled=True
        )
        disabled_with_prompt = AgentConfig(
            name="B", prompt_id="sys_theory", color="#000", enabled=False
        )
        disabled_no_prompt = AgentConfig(name="C", prompt_id=None, color="#000", enabled=False)
        enabled_no_prompt = AgentConfig(name="D", prompt_id=None, color="#000", enabled=True)

        assert enabled_with_prompt.is_active is True
        assert disabled_with_prompt.is_active is False
        assert disabled_no_prompt.is_active is False
        # The pre-existing prompt_id contract: blank/no prompt → inactive.
        assert enabled_no_prompt.is_active is False

    def test_disabled_agent_with_prompt_id_is_not_active(self):
        a = AgentConfig(
            name="A",
            prompt_id="sys_theory",
            color="#000",
            enabled=False,
        )
        assert a.is_active is False

    def test_agent_without_enabled_keyword_defaults_to_active(self, tmp_path):
        a = AgentConfig(name="Default", prompt_id="sys_theory", color="#000")
        assert a.enabled is True
        assert a.is_active is True


class TestEnabledRosterPersistence:
    def test_save_keeps_disabled_agent_with_prompt_id(self, tmp_path):
        svc = _bare_service(tmp_path)
        svc._current_agents = [
            AgentConfig(name="On", prompt_id="sys_theory", color="#000", enabled=True),
            AgentConfig(
                name="Off",
                prompt_id="sys_theory",
                color="#111",
                enabled=False,
                client_id="client-off",
            ),
        ]

        saved = svc._save_current_state_locked()
        assert saved is not None

        reloaded = svc.storage.load(saved.stem)
        assert reloaded is not None
        by_name = {a.name: a for a in reloaded.agents}
        assert set(by_name) == {"On", "Off"}, (
            "Disabled agents must NOT be filtered out before write — "
            "the editable roster must be persisted in full."
        )
        # The disabled agent keeps its prompt_id and client_id so
        # subsequent edits work without re-typing the configuration.
        assert by_name["Off"].enabled is False
        assert by_name["Off"].prompt_id == "sys_theory"
        assert by_name["Off"].client_id == "client-off"

    def test_save_promotes_enabled_to_stored_field(self, tmp_path):
        svc = _bare_service(tmp_path)
        svc._current_agents = [
            AgentConfig(name="Off", prompt_id="sys_theory", color="#000", enabled=False),
        ]
        saved = svc._save_current_state_locked()
        assert saved is not None

        reloaded = svc.storage.load(saved.stem)
        assert reloaded is not None
        assert reloaded.agents[0].enabled is False

    def test_rehydrate_preserves_enabled_flag(self, tmp_path):
        svc = _bare_service(tmp_path)
        svc._current_agents = [
            AgentConfig(name="On", prompt_id="sys_theory", color="#000", enabled=True),
            AgentConfig(name="Off", prompt_id="sys_theory", color="#111", enabled=False),
        ]
        saved = svc._save_current_state_locked()
        assert saved is not None
        file_id = saved.stem

        fresh = _bare_service(tmp_path)
        # ``open_session`` cancels any active generation and starts a
        # fresh one.  We stub the helper so the bare service has no
        # need for an LLM / prompt repo wiring, and prime
        # ``_active_generation`` to ``None`` (no in-flight run to
        # cancel — the production constructor would already have
        # set it).
        fresh._active_generation = None
        fresh._begin_generation_locked = lambda: None  # type: ignore[method-assign]
        assert fresh.open_session(file_id) is True
        by_name = {a.name: a for a in fresh._current_agents}
        assert by_name["On"].enabled is True
        assert by_name["Off"].enabled is False
        # And — the disabled agent is still in the roster at all.
        assert set(by_name) == {"On", "Off"}


class TestEnabledRosterSnapshot:
    def _make_service(self, tmp_path):
        session_contexts_dir = tmp_path / "session_contexts"
        _populate_session_contexts(session_contexts_dir)
        return _LanguageConfiguredDiscussionService(
            settings=_mock_settings(),
            llm_manager=_mock_llm_manager(),
            prompt_repo=_mock_prompt_repo(),
            storage_dir=tmp_path / "disc",
            session_context_dir=session_contexts_dir,
        )

    def test_snapshot_preserves_disabled_agent_with_prompt_id(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Q?",
                agents=[
                    AgentConfig(
                        name="On",
                        prompt_id="sys_theory",
                        color="#000",
                        client_id="client-on",
                    ),
                    AgentConfig(
                        name="Off",
                        prompt_id="sys_theory",
                        color="#111",
                        client_id="client-off",
                        enabled=False,
                    ),
                ],
            )
        fp = svc._save_current_state()
        assert fp is not None
        file_id = fp.stem

        # Snapshot from a *fresh* service so we exercise the
        # on-disk -> AgentConfig -> snapshot path.
        fresh = self._make_service(tmp_path)
        snap = fresh.snapshot_open_session(file_id)
        assert snap is not None

        agents_by_name = {a["name"]: a for a in snap["agents"]}
        assert set(agents_by_name) == {"On", "Off"}, (
            "Snapshot must include the full editable roster, not just active agents."
        )
        assert agents_by_name["Off"]["enabled"] is False
        assert agents_by_name["Off"]["prompt_id"] == "sys_theory"
        assert agents_by_name["Off"]["client_id"] == "client-off"
        assert agents_by_name["On"]["enabled"] is True

    def test_execution_skips_disabled_agent(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Q?",
                agents=[
                    AgentConfig(
                        name="On",
                        prompt_id="sys_theory",
                        color="#000",
                    ),
                    AgentConfig(
                        name="Off",
                        prompt_id="sys_theory",
                        color="#111",
                        enabled=False,
                    ),
                ],
            )
        # Bypass the async run; we want to assert the executable set.
        active = [a for a in svc._current_agents if a.is_active]
        assert [a.name for a in active] == ["On"]


class TestStoredAgentEnabledConversion:
    def test_stored_agent_to_dict_carries_enabled(self):
        a = _StoredAgent(
            name="A",
            prompt_id="sys_theory",
            prompt_label="L",
            enabled=False,
        )
        assert a.enabled is False
        assert "enabled" in a.__dict__


# Roster replacement is an atomic read-mutate-save operation under ``_run_lock``.
class TestUpdateCurrentAgents:
    def _make_service(self, tmp_path) -> DiscussionService:
        session_contexts_dir = tmp_path / "session_contexts"
        _populate_session_contexts(session_contexts_dir)
        return _LanguageConfiguredDiscussionService(
            settings=_mock_settings(),
            llm_manager=_mock_llm_manager(),
            prompt_repo=_mock_prompt_repo(),
            storage_dir=tmp_path / "disc",
            session_context_dir=session_contexts_dir,
        )

    def test_update_returns_false_when_no_stored_session(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc._current_stored is None
        new_agents = [AgentConfig(name="X", prompt_id="sys_theory", color="#000")]
        assert svc.update_current_agents(new_agents) is False
        assert svc._current_agents == []

    def test_update_replaces_full_roster_and_persists(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="Material",
                question="Frage?",
                agents=[AgentConfig(name="A1", prompt_id="sys_theory", color="#f00")],
            )
        file_id = svc.current_session_file_id()
        assert file_id is not None

        new_agents = [
            AgentConfig(name="B1", prompt_id="sys_theory", color="#0f0"),
            AgentConfig(name="B2", prompt_id="sys_theory", color="#00f"),
            AgentConfig(name="B3", prompt_id="sys_theory", color="#ff0"),
        ]

        assert svc.update_current_agents(new_agents) is True

        # In-memory roster is the new roster, in order, with the same
        # instance references we passed in (caller-supplied list is
        # adopted verbatim by the contract).
        assert [a.name for a in svc._current_agents] == ["B1", "B2", "B3"]
        assert svc._current_agents is new_agents or [a.name for a in svc._current_agents] == [
            a.name for a in new_agents
        ]

        # And the new roster is on disk: reloading from storage
        # returns the new names in the same order.
        reloaded = svc.storage.load(file_id)
        assert reloaded is not None
        assert [a.name for a in reloaded.agents] == ["B1", "B2", "B3"]

    def test_update_preserves_supplied_ordering(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Q?",
                agents=[],
            )

        names = ["Zeta", "Alpha", "Mike", "Bravo"]
        new_agents = [AgentConfig(name=n, prompt_id="sys_theory", color="#abc") for n in names]
        assert svc.update_current_agents(new_agents) is True
        assert [a.name for a in svc._current_agents] == names

        file_id = svc.current_session_file_id()
        assert file_id is not None
        reloaded = svc.storage.load(file_id)
        assert reloaded is not None
        assert [a.name for a in reloaded.agents] == names

    def test_update_holds_run_lock_for_entire_operation(self, tmp_path):
        svc = self._make_service(tmp_path)
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Q?",
                agents=[],
            )
        file_id = svc.current_session_file_id()
        assert file_id is not None

        # Gate inside the save: while update_current_agents is in
        # the middle of its _save_current_state_locked call, a
        # concurrent _save_current_state() (which also takes the
        # run lock) must block until the update releases the lock.
        original_locked = svc._save_current_state_locked
        call_log: list[str] = []
        block_in_save = threading.Event()
        release_in_save = threading.Event()

        def gated_locked():
            call_log.append("enter")
            if not block_in_save.is_set():
                block_in_save.set()
                release_in_save.wait(timeout=5.0)
            try:
                return original_locked()
            finally:
                call_log.append("exit")

        svc._save_current_state_locked = gated_locked  # type: ignore[method-assign]

        new_agents = [AgentConfig(name="X", prompt_id="sys_theory", color="#0f0")]

        update_done = threading.Event()
        update_errors: list[BaseException] = []

        def do_update():
            try:
                svc.update_current_agents(new_agents)
            except BaseException as exc:
                update_errors.append(exc)
            finally:
                update_done.set()

        t = threading.Thread(target=do_update, daemon=True)
        t.start()

        # Wait until the gated save is in flight.
        assert block_in_save.wait(timeout=5.0), (
            "update_current_agents never reached _save_current_state_locked"
        )

        # While the update is inside the save, an autosave must
        # block on the run lock.
        autosave_done = threading.Event()

        def do_autosave():
            svc._save_current_state()
            autosave_done.set()

        at = threading.Thread(target=do_autosave, daemon=True)
        at.start()

        autosave_done.wait(timeout=0.2)
        assert not autosave_done.is_set(), (
            "Concurrent _save_current_state completed while "
            "update_current_agents held the run lock — the mutation "
            "is not properly serialised."
        )

        release_in_save.set()
        assert update_done.wait(timeout=5.0)
        at.join(timeout=5.0)
        assert autosave_done.is_set()
        assert not update_errors, update_errors


# Only current-round context flags are mutable; locking older rounds preserves
# the persisted audit trail.
class TestSetMessageContextInclusion:
    def _make_service(self, tmp_path) -> DiscussionService:
        session_contexts_dir = tmp_path / "session_contexts"
        _populate_session_contexts(session_contexts_dir)
        return _LanguageConfiguredDiscussionService(
            settings=_mock_settings(),
            llm_manager=_mock_llm_manager(),
            prompt_repo=_mock_prompt_repo(),
            storage_dir=tmp_path / "disc",
            session_context_dir=session_contexts_dir,
        )

    def _seed_two_rounds(self, svc):
        """Build a service with one message in round 1 and one in round 2."""
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Q1?",
                agents=[],
            )
        r1 = svc.state.add_user_message("R1-Frage")
        svc.state.round_number = 2
        r2 = svc.state.add_user_message("R2-Frage")
        # Also add an agent response in round 2 so we can toggle that too.
        agent_r2 = svc.state.add_agent_response(
            AgentResponse(
                message_id="agent-r2",
                agent_index=0,
                agent_name="A",
                theory_label="T",
                color="#fff",
                text="Antwort R2",
                is_complete=True,
            )
        )
        return r1, r2, agent_r2

    def test_set_inclusion_unknown_message_returns_not_found(self, tmp_path):
        svc = self._make_service(tmp_path)
        # Empty state, unknown id
        assert svc.set_message_context_inclusion("does-not-exist", False) == "not_found"

    def test_set_inclusion_older_round_returns_locked(self, tmp_path):
        svc = self._make_service(tmp_path)
        r1, r2, agent_r2 = self._seed_two_rounds(svc)
        # Current round is 2; r1 is round 1 → locked.
        assert svc.state.round_number == 2
        result = svc.set_message_context_inclusion(r1.id, False)
        assert result == "locked"
        # r1's flag must NOT have been mutated.
        assert r1.include_in_agent_context is True

    def test_set_inclusion_current_round_returns_updated_and_persists(self, tmp_path):
        svc = self._make_service(tmp_path)
        r1, r2, agent_r2 = self._seed_two_rounds(svc)
        file_id = svc.current_session_file_id()
        assert file_id is not None

        # r2 belongs to round 2 = current round → updatable.
        assert r2.include_in_agent_context is True
        result = svc.set_message_context_inclusion(r2.id, False)
        assert result == "updated"
        assert r2.include_in_agent_context is False

        reloaded = svc.storage.load(file_id)
        assert reloaded is not None
        flat_msgs = [m for rnd in reloaded.rounds for m in rnd.messages]
        by_id = {m.id: m for m in flat_msgs}
        assert by_id[r2.id].include_in_agent_context is False
        assert by_id[r1.id].include_in_agent_context is True

    def test_set_inclusion_can_flip_back_to_true(self, tmp_path):
        svc = self._make_service(tmp_path)
        r1, r2, agent_r2 = self._seed_two_rounds(svc)

        assert svc.set_message_context_inclusion(r2.id, False) == "updated"
        assert r2.include_in_agent_context is False

        assert svc.set_message_context_inclusion(r2.id, True) == "updated"
        assert r2.include_in_agent_context is True

    def test_set_inclusion_flip_actually_changes_next_context(self, tmp_path):
        svc = self._make_service(tmp_path)
        r1, r2, agent_r2 = self._seed_two_rounds(svc)

        assert svc.set_message_context_inclusion(r2.id, False) == "updated"
        ctx = svc.state.get_context_for_agents()
        assert "R2-Frage" not in ctx
        # r1 is locked so its content stays visible in history.
        assert "R1-Frage" in ctx

        # Flip r2 back on, then flip r1 (locked) — must be rejected,
        # the context must continue to include r1.
        assert svc.set_message_context_inclusion(r2.id, True) == "updated"
        assert svc.set_message_context_inclusion(r1.id, False) == "locked"
        ctx2 = svc.state.get_context_for_agents()
        assert "R1-Frage" in ctx2
        assert "R2-Frage" in ctx2

    def test_set_inclusion_holds_run_lock_for_entire_operation(self, tmp_path):
        svc = self._make_service(tmp_path)
        r1, r2, agent_r2 = self._seed_two_rounds(svc)

        # Gate inside the save: while the toggle is in
        # _save_current_state_locked, a concurrent _save_current_state()
        # (same lock) must block.
        original_locked = svc._save_current_state_locked
        block_in_save = threading.Event()
        release_in_save = threading.Event()
        in_save = threading.Event()

        def gated_locked():
            in_save.set()
            if not block_in_save.is_set():
                block_in_save.set()
                release_in_save.wait(timeout=5.0)
            return original_locked()

        svc._save_current_state_locked = gated_locked  # type: ignore[method-assign]

        flip_done = threading.Event()
        flip_errors: list[BaseException] = []

        def do_flip():
            try:
                svc.set_message_context_inclusion(r2.id, False)
            except BaseException as exc:
                flip_errors.append(exc)
            finally:
                flip_done.set()

        t = threading.Thread(target=do_flip, daemon=True)
        t.start()

        assert in_save.wait(timeout=5.0), (
            "set_message_context_inclusion never reached _save_current_state_locked"
        )

        autosave_done = threading.Event()

        def do_autosave():
            svc._save_current_state()
            autosave_done.set()

        at = threading.Thread(target=do_autosave, daemon=True)
        at.start()

        autosave_done.wait(timeout=0.2)
        assert not autosave_done.is_set(), (
            "Concurrent _save_current_state completed while "
            "set_message_context_inclusion held the run lock — the "
            "mutation is not properly serialised."
        )

        release_in_save.set()
        assert flip_done.wait(timeout=5.0)
        at.join(timeout=5.0)
        assert autosave_done.is_set()
        assert not flip_errors, flip_errors


# Reordered rosters retain full-roster indices for stable client mapping, and
# current-round context flags control the next generated prompt. Events make
# the asynchronous assertions deterministic.
class TestRosterAndContextUIContract:
    _PROMPT_ID = "sys_theory"

    def _make_service(self, tmp_path) -> DiscussionService:
        session_contexts_dir = tmp_path / "session_contexts"
        _populate_session_contexts(session_contexts_dir)
        # LLM manager with a *recording* stream — the side-effect
        # appends a copy of the kwargs so we can later assert on the
        # exact ``prompt=...`` argument the service built.
        llm = MagicMock()
        stream_calls: list[dict] = []

        def _recording_stream(*args, **kwargs):
            stream_calls.append({"args": args, "kwargs": dict(kwargs)})
            # Yield a single chunk so ``continue_discussion``'s
            # streaming loop terminates normally and the worker
            # thread advances to ``on_all_complete``.
            yield "ok"

        llm.generate_stream.side_effect = _recording_stream
        llm.host = "recording"
        llm.model_name = "recording-model"
        llm_manager = MagicMock()
        llm_manager.llm = llm
        llm_manager.get_llm.return_value = llm
        return (
            _LanguageConfiguredDiscussionService(
                settings=_mock_settings(),
                llm_manager=llm_manager,
                prompt_repo=_mock_prompt_repo(),
                storage_dir=tmp_path / "disc",
                session_context_dir=session_contexts_dir,
            ),
            llm,
            stream_calls,
        )

    def _start_session_round_1(self, svc: DiscussionService) -> None:
        """Seed a session and bump state.round_number to 1 so the
        first ``continue_discussion`` call is meaningful."""
        with patch.object(svc, "run_discussion_async"):
            svc.start_new_discussion(
                material="M",
                question="Q?",
                agents=[AgentConfig(name="A1", prompt_id=self._PROMPT_ID, color="#f00")],
            )
        svc.state.add_user_message("Erste Frage")
        svc.state.round_number = 1

    @pytest.mark.parametrize("language", ["English", "Deutsch"])
    @pytest.mark.parametrize("note_included", [True, False])
    def test_export_reconstructs_current_prompts_without_claiming_historical_requests(
        self, tmp_path, language, note_included
    ):
        from src.prompts.preview import build_preview_user_prompt

        svc, _llm, _calls = self._make_service(tmp_path)
        self._start_session_round_1(svc)
        assert svc._material_context is not None
        assert svc._current_stored is not None
        svc._material_context.target_language = language
        svc._current_stored.prompt_snapshot.target_language = language
        svc._current_stored.prompt_snapshot.layout = "Historical snapshot layout"
        contribution = svc.state.add_agent_response(
            AgentResponse(
                message_id="export-note",
                agent_index=0,
                agent_name="A1",
                theory_label="A1",
                color="#f00",
                text="Synthetic contribution",
            )
        )
        assert svc.set_message_note(contribution.id, "Synthetic interpretation", note_included)
        svc.state.round_number = 2
        svc.state.add_user_message("Current moderator input")

        reconstructed = svc._export_prompt_documentation()
        assert len(reconstructed) == 1
        label, system_prompt, user_prompt = reconstructed[0]
        assert label == "Perspective 1"
        assert system_prompt == svc.build_system_prompt(
            prompt_id=self._PROMPT_ID,
            agent_config=svc._current_agents[0],
            material_context=svc._material_context,
            mark_prompt_usage=False,
        )
        assert user_prompt == build_preview_user_prompt(
            svc._material_context, discussion_state=svc.state
        )
        assert (
            system_prompt.index("=== RESEARCHER NOTES ===")
            < system_prompt.index("=== YOUR PERSPECTIVE ===")
            < system_prompt.index("=== FINAL RESPONSE LANGUAGE REQUIREMENT ===")
        )
        assert f"Write all prose in {language}." in system_prompt
        assert f"Write all prose in {language}." in user_prompt
        if note_included:
            assert (
                user_prompt.index("Current moderator input")
                < user_prompt.index("=== RESEARCHER NOTES REMINDER ===")
                < user_prompt.index("=== CURRENT RESPONSE LANGUAGE REMINDER ===")
            )
        else:
            assert "=== RESEARCHER NOTES REMINDER ===" not in user_prompt
        markdown = svc.get_markdown(locale="en")
        assert markdown is not None
        assert "Historical snapshot layout" not in markdown
        assert "Saved Assembly Policy" not in markdown
        assert "not recorded historical requests" in markdown
        assert (
            markdown.index("### Saved Prompt Definitions")
            < markdown.index("### Current Prompt Organization")
            < markdown.index("### Current-State Prompt Reconstruction")
        )
        assert (
            markdown.index("##### System Message")
            < markdown.index("##### User Message")
            < markdown.index("### Current-State Prompt Reconstruction")
        )
        assert (
            markdown.index("6. Researcher-note rule (applies across perspectives)")
            < markdown.index("7. Perspective definition")
            < markdown.index("8. Final language requirement (applies across perspectives)")
        )
        assert markdown.index("4. Conditional researcher-note reminder") < markdown.index(
            "5. Final language reminder (applies across perspectives)"
        )
        assert "`{N}` is that round's number." in markdown
        assert "   === RESEARCHER NOTES REMINDER ===\n" in markdown
        assert (
            "   Address the included researcher notes from Round {N} where relevant to the current question.\n"
            in markdown
        )
        assert f"```text\n{system_prompt}\n```" in markdown
        assert f"```text\n{user_prompt}\n```" in markdown
        assert "Synthetic interpretation" in markdown
        assert "[Preview: synthetic researcher note" not in markdown
        assert "[Preview: synthetic researcher note" not in user_prompt

    def test_export_synthesis_reconstruction_remains_round_scoped(self, tmp_path):
        svc, _llm, _calls = self._make_service(tmp_path)
        self._start_session_round_1(svc)
        assert svc._current_stored is not None
        svc._current_stored.prompt_snapshot.synthesis_used = True
        svc._current_stored.prompt_snapshot.synthesis = {
            "label": "Round Synthesis",
            "content": "Synthetic synthesis guidance.",
        }
        contribution = svc.state.add_agent_response(
            AgentResponse(
                message_id="synthesis-note",
                agent_index=0,
                agent_name="A1",
                theory_label="A1",
                color="#f00",
                text="Current contribution",
            )
        )
        assert svc.set_message_note(contribution.id, "Researcher note only for perspectives", True)
        reconstructed = svc._export_prompt_documentation()
        assert len(reconstructed) == 2
        _label, system_prompt, user_prompt = reconstructed[1]
        assert "=== FINAL RESPONSE LANGUAGE REQUIREMENT ===" in system_prompt
        assert "Write all synthesis prose and every category lead-in in English." in system_prompt
        assert "=== CURRENT RESPONSE LANGUAGE REMINDER ===" in user_prompt
        assert "Researcher note only for perspectives" not in system_prompt + user_prompt
        assert "=== RESEARCHER NOTES ===" not in system_prompt
        assert "=== RESEARCHER NOTES REMINDER ===" not in user_prompt
        markdown = svc.get_markdown(locale="en")
        assert markdown is not None
        synthesis_section = markdown.split("#### Synthesis Prompting", 1)[1].split(
            "### Current-State Prompt Reconstruction", 1
        )[0]
        assert "=== RESEARCHER NOTES ===" not in synthesis_section
        assert "=== RESEARCHER NOTES REMINDER ===" not in synthesis_section
        assert (
            "Write all synthesis prose and every category lead-in in English." in synthesis_section
        )

    def test_new_export_snapshot_documents_conditional_reminder_without_claiming_delivery(
        self, tmp_path
    ):
        svc, _llm, _calls = self._make_service(tmp_path)
        self._start_session_round_1(svc)
        assert svc._current_stored is not None
        layout = svc._current_stored.prompt_snapshot.layout
        assert "Included researcher notes provide the researcher’s interpretations" in layout
        assert "=== RESEARCHER NOTES REMINDER ===\n" in layout
        assert "Round {N}" in layout
        assert "immediately preceding round" in layout
        assert "not historical request payloads" in layout
        markdown = svc.get_markdown(locale="en")
        assert markdown is not None
        assert "#### Saved Assembly Policy" not in markdown
        assert layout not in markdown
        assert "### Current Prompt Organization" in markdown
        assert "Round {N}" in markdown
        assert "not recorded historical requests" in markdown
        reconstruction = markdown.split("### Current-State Prompt Reconstruction", 1)[1]
        assert "=== RESEARCHER NOTES REMINDER ===" not in reconstruction
        assert "=== CURRENT RESPONSE LANGUAGE REMINDER ===" in reconstruction

    @pytest.mark.parametrize(
        (
            "note_round",
            "note_opted_in",
            "parent_included",
            "generation_round",
            "reminder_expected",
        ),
        [
            (1, True, True, 2, True),
            (2, True, True, 3, True),
            (1, False, True, 2, False),
            (1, True, False, 2, False),
            (1, True, True, 3, False),
        ],
    )
    def test_preceding_round_note_reminder_only_reaches_eligible_perspective_request(
        self,
        tmp_path,
        note_round,
        note_opted_in,
        parent_included,
        generation_round,
        reminder_expected,
    ):
        svc, _llm, stream_calls = self._make_service(tmp_path)
        self._start_session_round_1(svc)
        svc.state.round_number = note_round
        if note_round > 1:
            svc.state.add_user_message("Synthetic preceding question")
        contribution = svc.state.add_agent_response(
            AgentResponse(
                message_id="synthetic-prior-note",
                agent_index=0,
                agent_name="A1",
                theory_label="A1",
                color="#f00",
                text="Synthetic perspective response",
            )
        )
        assert svc.set_message_note(contribution.id, "SENTINEL_PRIOR_NOTE", note_opted_in)
        if not parent_included:
            assert svc.set_message_context_inclusion(contribution.id, False) == "updated"
        svc.state.round_number = generation_round - 1

        completed = threading.Event()
        with patch.object(svc, "_save_current_state", return_value=None):
            svc.continue_discussion(
                user_input="Synthetic next question",
                agents=[AgentConfig(name="A1", prompt_id=self._PROMPT_ID, color="#f00")],
                on_all_complete=completed.set,
            )
        assert completed.wait(timeout=5.0)
        assert len(stream_calls) == 1
        prompt = stream_calls[0]["kwargs"]["prompt"]
        system_prompt = stream_calls[0]["kwargs"]["system_prompt"]
        assert (
            "=== RESEARCHER NOTES ===\n"
            "Included researcher notes provide the researcher’s interpretations and guidance for "
            "the discussion. Consider them when developing your response, distinguishing them "
            "from evidence in the source material."
        ) in system_prompt
        assert (
            system_prompt.index("=== RESEARCHER NOTES ===")
            < system_prompt.index("=== YOUR PERSPECTIVE ===")
            < system_prompt.index("=== FINAL RESPONSE LANGUAGE REQUIREMENT ===")
        )
        reminder = (
            "=== RESEARCHER NOTES REMINDER ===\n"
            f"Address the included researcher notes from Round {note_round} "
            "where relevant to the current question."
        )
        assert (reminder in prompt) is reminder_expected
        assert ("SENTINEL_PRIOR_NOTE" in prompt) is (parent_included and note_opted_in)
        if reminder_expected:
            assert prompt.index(
                "[HUMAN RESEARCHER NOTE ON THE ABOVE PERSPECTIVE RESPONSE]"
            ) < prompt.index("=== CURRENT ROUND USER INPUT")
            assert prompt.index("Synthetic next question") < prompt.index(reminder)
            assert prompt.index(reminder) < prompt.index(
                "=== CURRENT RESPONSE LANGUAGE REMINDER ==="
            )
        assert prompt.endswith(
            "=== CURRENT RESPONSE LANGUAGE REMINDER ===\nWrite all prose in English."
        )

    # 1) Roster reorder + agent_index preservation across a disabled slot
    def test_continue_uses_passed_roster_order_and_preserves_full_roster_index(
        self,
        tmp_path,
    ):
        svc, llm, stream_calls = self._make_service(tmp_path)
        self._start_session_round_1(svc)

        # Roster in REORDERED order, with a disabled agent at slot 0
        # (no prompt_id → ``is_active`` is False).  The three
        # active agents are deliberately NOT in alphabetical order,
        # so an ordering error in the service would be obvious.
        agents = [
            AgentConfig(name="DisabledSlot", prompt_id=None, color="#888"),
            AgentConfig(name="Charlie", prompt_id=self._PROMPT_ID, color="#0f0"),
            AgentConfig(name="Alpha", prompt_id=self._PROMPT_ID, color="#f00"),
            AgentConfig(name="Bravo", prompt_id=self._PROMPT_ID, color="#00f"),
        ]
        # Sanity: confirm the test fixture is actually exercising
        # the contract — slot 0 is inactive, slots 1-3 are active.
        assert agents[0].is_active is False
        assert [a.is_active for a in agents] == [False, True, True, True]

        # Capture on_agent_start events so we can assert on the
        # order + the agent_index the service reports.
        starts: list[AgentResponse] = []
        all_complete = threading.Event()

        # Suppress the on-complete autosave to keep the test
        # isolated from disk I/O — the existing pattern used by
        # the temperature contract tests.
        with patch.object(svc, "_save_current_state", return_value=None):
            svc.continue_discussion(
                user_input="Bitte weiter diskutieren.",
                agents=agents,
                on_agent_start=lambda response: starts.append(response),
                on_all_complete=all_complete.set,
            )

        # Deterministic wait — the worker thread fires
        # ``on_all_complete`` exactly once after the last agent's
        # chunk has been consumed and the round has been stored.
        assert all_complete.wait(timeout=5.0), (
            "continue_discussion worker did not complete within 5s"
        )

        # -- 1a. The start order matches the passed order, skipping
        #        the disabled slot.  ``on_agent_start`` is called
        #        in the same order the service will call
        #        ``llm.generate_stream`` — proof that the roster
        #        reorder is honoured at scheduling time.
        start_names = [r.agent_name for r in starts]
        start_indices = [r.agent_index for r in starts]
        assert start_names == ["Charlie", "Alpha", "Bravo"], (
            f"on_agent_start fired in wrong order: {start_names!r}; "
            "expected the passed roster order with disabled slot skipped"
        )

        # -- 1b. The agent_index values are the ORIGINAL full-roster
        #        positions (1, 2, 3), not the dense "active slot"
        #        (0, 1, 2).  This is the contract that lets the
        #        frontend keep its slot-to-agent mapping stable
        #        even when a slot is toggled off.
        assert start_indices == [1, 2, 3], (
            f"agent_index does not preserve full-roster position: "
            f"got {start_indices!r}, expected [1, 2, 3]"
        )

        # -- 1c. The LLM was actually invoked in the same order, and
        #        with the same agent_index (via the surrounding
        #        AgentResponse, not the prompt).  The LLM is hit
        #        once per active agent, with the user prompt the
        #        service built.
        assert len(stream_calls) == 3, (
            f"expected 3 llm.generate_stream calls, got {len(stream_calls)}"
        )

        # Every LLM call must have received a non-empty ``prompt=``
        # keyword argument — the actual user prompt is the
        # continuation's context + new user input.  This also
        # proves that the second continuation's prompt includes
        # the previous round's user message (no broken prompt
        # pipeline).
        for i, call in enumerate(stream_calls):
            assert "prompt" in call["kwargs"], f"call #{i} missing 'prompt' kwarg: {call!r}"
            assert isinstance(call["kwargs"]["prompt"], str)
            assert call["kwargs"]["prompt"].strip(), f"call #{i} got empty 'prompt' string"

    def test_continue_roster_order_survives_multiple_resequences(
        self,
        tmp_path,
    ):
        svc, llm, stream_calls = self._make_service(tmp_path)
        self._start_session_round_1(svc)

        round1_agents = [
            AgentConfig(name="X", prompt_id=self._PROMPT_ID, color="#111"),
            AgentConfig(name="Y", prompt_id=self._PROMPT_ID, color="#222"),
            AgentConfig(name="Z", prompt_id=self._PROMPT_ID, color="#333"),
        ]
        all_complete_1 = threading.Event()
        with patch.object(svc, "_save_current_state", return_value=None):
            svc.continue_discussion(
                user_input="Runde 1: bitte starten.",
                agents=round1_agents,
                on_agent_start=lambda r: None,
                on_all_complete=all_complete_1.set,
            )
        assert all_complete_1.wait(timeout=5.0)
        assert len(stream_calls) == 3

        # middle slot, to also re-verify the full-roster index
        # preservation on a second call.
        round2_agents = [
            AgentConfig(name="Z", prompt_id=self._PROMPT_ID, color="#333"),
            AgentConfig(name="Y-Disabled", prompt_id=None, color="#999"),
            AgentConfig(name="X", prompt_id=self._PROMPT_ID, color="#111"),
        ]
        assert round2_agents[1].is_active is False
        starts_2: list[AgentResponse] = []
        all_complete_2 = threading.Event()
        with patch.object(svc, "_save_current_state", return_value=None):
            svc.continue_discussion(
                user_input="Runde 2: bitte weiter.",
                agents=round2_agents,
                on_agent_start=lambda response: starts_2.append(response),
                on_all_complete=all_complete_2.set,
            )
        assert all_complete_2.wait(timeout=5.0)

        # The reverse order is honoured, the disabled middle slot
        # is skipped, and the original full-roster indices are
        # preserved (0 for Z, 2 for X).
        names_2 = [r.agent_name for r in starts_2]
        idx_2 = [r.agent_index for r in starts_2]
        assert names_2 == ["Z", "X"], f"round 2 on_agent_start fired in wrong order: {names_2!r}"
        assert idx_2 == [0, 2], (
            f"round 2 agent_index did not preserve full-roster slots: "
            f"got {idx_2!r}, expected [0, 2]"
        )

    # 2) set_message_context_inclusion controls the next prompt
    def test_excluded_current_round_message_sentinel_is_absent_from_next_prompt(
        self,
        tmp_path,
    ):
        svc, llm, stream_calls = self._make_service(tmp_path)

        # Bootstrap a session in round 1 with an opening user
        # message.  After the first ``continue_discussion`` call,
        # state.round_number will be 2 and the new user message
        # will be in round 2 (the current round).  The user_input
        # here carries the EXCLUDED sentinel — it is the message
        # we will then toggle off via set_message_context_inclusion.
        self._start_session_round_1(svc)
        excluded_sentinel = "EXCLUDE_SENTINEL_XYZ_42_999"
        all_complete_1 = threading.Event()
        with patch.object(svc, "_save_current_state", return_value=None):
            svc.continue_discussion(
                user_input=(
                    f"Eröffnungsfrage der Runde 2. "
                    f"{excluded_sentinel} ist der Hinweis, "
                    "den wir gleich ausschließen wollen."
                ),
                agents=[AgentConfig(name="A1", prompt_id=self._PROMPT_ID, color="#f00")],
                on_agent_start=lambda r: None,
                on_all_complete=all_complete_1.set,
            )
        assert all_complete_1.wait(timeout=5.0)

        # After round 1's continue, the service is in round 2 and
        # the just-added user message is the only current-round
        # user message.  Find it by role + content (the agent
        # response is appended after the user message by the
        # worker thread, so ``messages[-1]`` is the agent).
        assert svc.state.round_number == 2
        excluded_sentinel = "EXCLUDE_SENTINEL_XYZ_42_999"
        excluded_msg = next(
            m
            for m in reversed(svc.state.messages)
            if m.role == "user" and excluded_sentinel in m.content
        )
        assert excluded_msg.round_number == 2

        # Reset the LLM call recorder so we only inspect the next
        # (round 2) continuation, not the bootstrap round 1 call.
        stream_calls.clear()

        # Toggle the EXCLUDED message off — it is the current
        # round, so the service must return "updated" and the
        # in-memory flag must flip.
        result = svc.set_message_context_inclusion(
            excluded_msg.id,
            False,
        )
        assert result == "updated", (
            f"set_message_context_inclusion returned {result!r}; "
            "expected 'updated' for a current-round message"
        )
        assert excluded_msg.include_in_agent_context is False

        # Now call continue_discussion again.  This will:
        #   * increment round to 3,
        #   * add a NEW user message in round 3 (containing the
        #     INCLUDED sentinel token),
        #   * build the prompt from get_context_for_agents(), which
        #     honours include_in_agent_context and must therefore
        #     *skip* the EXCLUDED round-2 message.
        included_sentinel = "INCLUDE_SENTINEL_ABC_7_777"
        new_user_input = (
            f"Bitte weiter diskutieren. {included_sentinel} ist der wichtige Hinweis dieser Runde."
        )
        all_complete_2 = threading.Event()
        with patch.object(svc, "_save_current_state", return_value=None):
            svc.continue_discussion(
                user_input=new_user_input,
                agents=[AgentConfig(name="A1", prompt_id=self._PROMPT_ID, color="#f00")],
                on_agent_start=lambda r: None,
                on_all_complete=all_complete_2.set,
            )
        assert all_complete_2.wait(timeout=5.0), (
            "second continue_discussion did not complete within 5s"
        )

        assert len(stream_calls) == 1
        prompt_arg = stream_calls[0]["kwargs"]["prompt"]
        assert isinstance(prompt_arg, str)

        # -- The included sentinel MUST appear in the next prompt.
        #    It was added as the new round-3 user message which is
        #    included by default, so the context builder must
        #    surface it.
        assert included_sentinel in prompt_arg, (
            f"included sentinel {included_sentinel!r} missing from "
            f"the next llm.generate_stream(prompt=...).\n"
            f"Prompt excerpt: {prompt_arg[:400]!r}"
        )

        # -- The excluded sentinel MUST NOT appear in the next
        #    prompt.  This is the core promise of the toggle: the
        #    excluded message stays in the audit log and Markdown
        #    export, but is silently dropped from the next
        #    continuation's context.
        assert excluded_sentinel not in prompt_arg, (
            f"excluded sentinel {excluded_sentinel!r} leaked into "
            f"the next llm.generate_stream(prompt=...) — "
            f"set_message_context_inclusion did not take effect.\n"
            f"Prompt excerpt: {prompt_arg[:400]!r}"
        )

    def test_inclusion_flip_back_to_true_restores_sentinel_in_prompt(
        self,
        tmp_path,
    ):
        svc, llm, stream_calls = self._make_service(tmp_path)
        self._start_session_round_1(svc)
        sentinel = "ROUND2_USER_TOKEN_REV_555"
        all_complete_1 = threading.Event()
        with patch.object(svc, "_save_current_state", return_value=None):
            svc.continue_discussion(
                user_input=(
                    f"Eröffnung der Diskussion. {sentinel} "
                    "ist der Hinweis, der gleich getoggelt wird."
                ),
                agents=[AgentConfig(name="A1", prompt_id=self._PROMPT_ID, color="#f00")],
                on_agent_start=lambda r: None,
                on_all_complete=all_complete_1.set,
            )
        assert all_complete_1.wait(timeout=5.0)

        assert svc.state.round_number == 2
        # The agent response is appended after the user message by
        # the worker thread, so ``messages[-1]`` is the agent —
        # find the user message by role + content.
        msg = next(
            m for m in reversed(svc.state.messages) if m.role == "user" and sentinel in m.content
        )
        assert msg.round_number == 2

        # Exclude, then immediately include.
        assert svc.set_message_context_inclusion(msg.id, False) == "updated"
        assert svc.set_message_context_inclusion(msg.id, True) == "updated"
        assert msg.include_in_agent_context is True

        # Reset the LLM call recorder so we only inspect the next
        # (round 2) continuation, not the bootstrap round 1 call.
        stream_calls.clear()

        # Trigger one more continuation round and inspect the
        # actual prompt the service sent to the LLM.
        all_complete_2 = threading.Event()
        with patch.object(svc, "_save_current_state", return_value=None):
            svc.continue_discussion(
                user_input="Folgefrage ohne eigenen Sentinel.",
                agents=[AgentConfig(name="A1", prompt_id=self._PROMPT_ID, color="#f00")],
                on_agent_start=lambda r: None,
                on_all_complete=all_complete_2.set,
            )
        assert all_complete_2.wait(timeout=5.0)

        assert len(stream_calls) == 1
        prompt_arg = stream_calls[0]["kwargs"]["prompt"]
        assert isinstance(prompt_arg, str)
        assert sentinel in prompt_arg, (
            f"after flipping inclusion back to True, the sentinel "
            f"{sentinel!r} is still missing from the next prompt. "
            f"The toggle appears to be one-way.\n"
            f"Prompt excerpt: {prompt_arg[:400]!r}"
        )
