"""Focused tests for context-window selection and deterministic compaction."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.llm.errors import LLMTokenCountUnsupportedError
from src.service.discussion import (
    CONTEXT_OUTPUT_RESERVE_TOKENS,
    AgentConfig,
    ContextUsage,
    DiscussionMessage,
    DiscussionService,
    DiscussionState,
    _ContextPreflightFailure,
)


def _service() -> DiscussionService:
    service = DiscussionService.__new__(DiscussionService)
    service.state = DiscussionState(material="Material")
    service._token_count_capabilities = {}
    service.settings = SimpleNamespace(known_llm_hosts={})
    return service


def _agent(*, host: str = "https://example.test/v1", model: str = "model-a") -> AgentConfig:
    return AgentConfig(name="A", prompt_id="role", api_host=host, llm_id=model)


def _message(round_number: int, content: str, *, included: bool = True) -> DiscussionMessage:
    return DiscussionMessage(
        id=f"r{round_number}-{content}",
        role="agent",
        content=content,
        round_number=round_number,
        agent_name="A",
        theory_label="Role",
        include_in_agent_context=included,
    )


def test_external_model_windows_and_managed_window_use_lowest_active_limit() -> None:
    service = _service()
    service.settings.known_llm_hosts = {
        "External": {
            "url": "https://example.test/v1",
            "model_context_tokens": {"model-a": 32_768, "model-b": 16_384},
        },
        "Local": {
            "url": "http://127.0.0.1:8080",
            "kind": "local_ai",
            "context_tokens": 65_536,
        },
    }
    agents = [
        _agent(model="model-a"),
        _agent(model="model-b"),
        _agent(host="http://127.0.0.1:8080", model="local"),
        AgentConfig(
            name="Off",
            prompt_id="role",
            enabled=False,
            api_host="https://example.test/v1",
            llm_id="model-a",
        ),
    ]

    assert service._context_tokens_for_agent(agents[0]) == 32_768
    assert service._context_tokens_for_agent(agents[2]) == 65_536
    assert service._effective_context_tokens(agents) == 16_384


def test_duplicate_host_urls_use_the_tightest_matching_model_limit() -> None:
    service = _service()
    service.settings.known_llm_hosts = {
        "First": {
            "url": "https://same.example/v1",
            "model_context_tokens": {"model-a": 65_536},
        },
        "Second": {
            "url": "https://same.example/v1",
            "model_context_tokens": {"model-a": 32_768},
        },
    }

    assert service._context_tokens_for_agent(_agent(host="https://same.example/v1")) == 32_768


def test_unsupported_external_count_endpoint_is_cached_and_uses_estimate() -> None:
    service = _service()
    llm = MagicMock(host="https://example.test/v1", model_name="model-a")
    llm.count_chat_input_tokens.side_effect = LLMTokenCountUnsupportedError("missing")

    first = service._preflight_context_usage(
        llm=llm,
        agent=_agent(),
        system_prompt="System",
        user_prompt="User",
    )
    second = service._preflight_context_usage(
        llm=llm,
        agent=_agent(),
        system_prompt="System",
        user_prompt="User",
    )

    assert first.available is True
    assert first.exact is False
    assert second.exact is False
    assert first.input_tokens is not None
    assert first.input_tokens == second.input_tokens
    assert llm.count_chat_input_tokens.call_count == 1


def test_managed_final_guard_estimates_assembled_request_without_token_endpoint() -> None:
    service = _service()
    service.settings.known_llm_hosts = {
        "Local": {
            "url": "http://127.0.0.1:8080",
            "kind": "local_ai",
            "context_tokens": 8192,
        }
    }
    llm = MagicMock(host="http://127.0.0.1:8080", model_name="local")
    llm.count_chat_input_tokens.side_effect = ConnectionError("token route unavailable")
    agent = _agent(host="http://127.0.0.1:8080", model="local")
    short = service._preflight_context_usage(
        llm=llm, agent=agent, system_prompt="System", user_prompt="Material"
    )
    with_history = service._preflight_context_usage(
        llm=llm,
        agent=agent,
        system_prompt="System",
        user_prompt="Material\nIncluded earlier discussion: " + ("synthetic history " * 100),
    )
    assert short.available is True
    assert short.exact is False
    assert with_history.input_tokens > short.input_tokens
    llm.count_chat_input_tokens.assert_not_called()


def test_compaction_keeps_round_one_and_latest_two_then_omits_oldest_middle_round() -> None:
    service = _service()
    service.state.messages = [_message(number, f"round-{number}") for number in range(1, 7)]
    llm = MagicMock(host="https://example.test/v1", model_name="model-a")

    def measured(**kwargs):
        omitted = kwargs["omitted_round_numbers"]
        return ContextUsage(
            available=True,
            exact=True,
            input_tokens=1_000 if omitted == (2,) else 5_000,
            context_tokens=CONTEXT_OUTPUT_RESERVE_TOKENS + 1_000,
            omitted_round_numbers=omitted,
        )

    service._preflight_context_usage = measured  # type: ignore[method-assign]
    prompt, usage = service._prepare_context_limited_prompt(
        llm=llm,
        agent=_agent(),
        system_prompt="System",
        effective_context_tokens=CONTEXT_OUTPUT_RESERVE_TOKENS + 1_000,
        before_round=7,
        build_user_prompt=lambda context: context,
    )

    assert usage.omitted_round_numbers == (2,)
    assert "round-1" in prompt
    assert "round-2" not in prompt
    assert "round-5" in prompt
    assert "round-6" in prompt
    assert "Rounds omitted from the LLM context: 2" in prompt


def test_compaction_fails_when_protected_content_alone_exceeds_budget() -> None:
    service = _service()
    service.state.messages = [_message(number, f"round-{number}") for number in (1, 5, 6)]
    llm = MagicMock(host="https://example.test/v1", model_name="model-a")
    service._preflight_context_usage = lambda **kwargs: ContextUsage(  # type: ignore[method-assign]
        available=True,
        exact=True,
        input_tokens=1_001,
        context_tokens=CONTEXT_OUTPUT_RESERVE_TOKENS + 1_000,
        omitted_round_numbers=kwargs["omitted_round_numbers"],
    )

    with pytest.raises(_ContextPreflightFailure) as raised:
        service._prepare_context_limited_prompt(
            llm=llm,
            agent=_agent(),
            system_prompt="System",
            effective_context_tokens=CONTEXT_OUTPUT_RESERVE_TOKENS + 1_000,
            before_round=7,
            build_user_prompt=lambda context: context,
        )

    assert raised.value.code == "context_limit_exceeded"
    assert raised.value.usage is not None
    assert raised.value.usage.omitted_round_numbers == ()


def test_request_assembly_reflects_note_edits_exclusion_and_compaction() -> None:
    service = _service()
    included = _message(1, "Included contribution")
    included.note = "NOTE_FIRST_SYNTHETIC"
    included.include_note_in_agent_context = True
    excluded = _message(1, "Excluded contribution", included=False)
    excluded.note = "NOTE_EXCLUDED_SYNTHETIC"
    excluded.include_note_in_agent_context = True
    middle = _message(2, "Middle contribution")
    middle.note = "NOTE_COMPACTED_SYNTHETIC"
    middle.include_note_in_agent_context = True
    latest = _message(4, "Latest contribution")
    latest.note = "NOTE_RECENT_SYNTHETIC"
    latest.include_note_in_agent_context = True
    service.state.messages = [
        included,
        excluded,
        middle,
        _message(3, "Recent contribution"),
        latest,
    ]
    service.state.round_number = 5
    service._preflight_context_usage = lambda **kwargs: ContextUsage(  # type: ignore[method-assign]
        available=True,
        exact=True,
        input_tokens=1000 if not kwargs["omitted_round_numbers"] else 100,
        omitted_round_numbers=kwargs["omitted_round_numbers"],
    )
    args = dict(
        llm=MagicMock(),
        agent=_agent(),
        system_prompt="System",
        before_round=5,
        build_user_prompt=lambda context: context,
    )

    first, _ = service._prepare_context_limited_prompt(**args, effective_context_tokens=None)
    assert "NOTE_FIRST_SYNTHETIC" in first
    assert "NOTE_EXCLUDED_SYNTHETIC" not in first
    assert "NOTE_COMPACTED_SYNTHETIC" in first

    included.note = "NOTE_EDITED_SYNTHETIC"
    second, _ = service._prepare_context_limited_prompt(**args, effective_context_tokens=None)
    assert "NOTE_EDITED_SYNTHETIC" in second
    assert "NOTE_FIRST_SYNTHETIC" not in second

    compacted, usage = service._prepare_context_limited_prompt(
        **args, effective_context_tokens=CONTEXT_OUTPUT_RESERVE_TOKENS + 500
    )
    assert usage.omitted_round_numbers == (2,)
    assert "NOTE_EDITED_SYNTHETIC" in compacted
    assert "NOTE_RECENT_SYNTHETIC" in compacted
    assert "NOTE_COMPACTED_SYNTHETIC" not in compacted
