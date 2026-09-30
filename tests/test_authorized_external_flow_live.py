"""Opt-in smoke tests for one explicitly authorized external host.

Set AQA_RUN_AUTHORIZED_EXTERNAL_LLM_TESTS=1, AQA_AUTHORIZED_EXTERNAL_CONFIG
(a private JSON file with endpoint_url, api_key, and model), and
AQA_AUTHORIZED_EXTERNAL_BUDGET (a caller-owned cumulative budget JSON file).
Initialize the latter from tests/fixtures/authorized_external_budget.json only
when authorizing a new budget; reusing it preserves counts across test runs.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.llm.llm_manager import LLMManager
from src.llm.openai_compatible_llm import OpenAICompatibleLLM
from src.prompts.storage import PromptRepository
from src.service.discussion import AgentConfig, DiscussionService, MaterialContext, SynthesisConfig
from tests.authorized_external_llm import (
    BudgetedSession,
    load_authorized_external_budget,
    load_authorized_external_config,
)

pytestmark = pytest.mark.integration

_ENABLED = os.getenv("AQA_RUN_AUTHORIZED_EXTERNAL_LLM_TESTS", "").strip() == "1"


def _require_enabled() -> None:
    if not _ENABLED:
        pytest.skip("Authorized external-host tests require an explicit opt-in.")


def test_authorized_model_discovery_is_reachable_without_redirects() -> None:
    _require_enabled()
    config = load_authorized_external_config()
    session = BudgetedSession(config, load_authorized_external_budget())

    response = session.get(
        f"{config.api_base}/v1/models",
        headers={"Authorization": f"Bearer {config.api_key}"},
        timeout=(10, 30),
        stream=True,
        allow_redirects=False,
    )
    try:
        assert response.status_code == 200, "authorized_model_discovery_failed"
    finally:
        response.close()


def test_authorized_model_streams_bounded_text_and_usage() -> None:
    _require_enabled()
    config = load_authorized_external_config()
    llm = OpenAICompatibleLLM(
        model_name=config.model,
        host=config.api_base,
        api_key=config.api_key,
        timeout=45,
        connect_timeout=10,
        stream_timeout=45,
        retries=0,
    )
    llm.session = BudgetedSession(config, load_authorized_external_budget())
    usage: list[dict[str, int]] = []

    chunks = list(
        llm.generate_stream(
            "Reply with exactly: STREAM READY",
            temperature=0,
            max_tokens=256,
            on_usage=usage.append,
        )
    )

    assert "".join(chunks).strip(), "authorized_stream_returned_no_visible_text"
    assert usage and usage[-1]["completion_tokens"] <= 256


def test_authorized_full_discussion_two_rounds_and_reopen(  # noqa: C901
    tmp_path: Path,
) -> None:
    """Exercise the previously cap-blocked workflow without exposing provider text."""
    _require_enabled()
    config = load_authorized_external_config()
    host_id = "authorized-test-host"
    prompt_root = Path("data/prompts").resolve()
    settings = Settings(
        known_llm_hosts={
            host_id: {
                "url": config.api_base,
                "api_key": config.api_key,
                "model": config.model,
                "models": [config.model],
                "is_favorite": True,
                "context_tokens": 32_768,
            }
        },
        prompt_library_path=str(prompt_root),
        prompt_defaults_path=str(prompt_root),
        llm_timeout=180,
        llm_connect_timeout=10,
        llm_health_timeout=10,
        llm_health_retries=0,
        llm_max_retries=0,
    )
    manager = LLMManager(settings)
    llm = manager.get_llm(
        host=config.api_base,
        model_name=config.model,
        host_configuration_id=host_id,
    )
    if not isinstance(llm, OpenAICompatibleLLM):
        pytest.fail("authorized_adapter_type_invalid", pytrace=False)
    # Live diagnostics use a separate per-request ceiling; External AI product
    # behavior deliberately has no application read or generation deadline.
    llm.stream_timeout = (10, 300)
    llm.session = BudgetedSession(config, load_authorized_external_budget())
    service = DiscussionService(
        settings=settings,
        llm_manager=manager,
        prompt_repo=PromptRepository(base_path=prompt_root),
        storage_dir=tmp_path / "discussions",
        session_context_dir=prompt_root / "session_contexts",
    )
    perspectives = service.get_available_perspectives()
    if len(perspectives) < 3:
        pytest.fail("authorized_perspective_catalog_empty", pytrace=False)
    colors = ("#2563eb", "#7c3aed", "#0f766e")
    agents = [
        AgentConfig(
            name=label,
            client_id=f"authorized-perspective-{number}",
            prompt_id=prompt_id,
            color=colors[number - 1],
            temperature=0,
            llm_id=config.model,
            api_host=config.api_base,
            host_configuration_id=host_id,
            host_label=host_id,
            max_tokens=None,
            perspective_number=number,
        )
        for number, (prompt_id, label) in enumerate(perspectives[:3], start=1)
    ]
    synthesis = SynthesisConfig(
        enabled=True,
        api_host=config.api_base,
        llm_id=config.model,
        temperature=0,
        host_configuration_id=host_id,
        host_label=host_id,
    )
    context = MaterialContext(
        material_type="document",
        session_type="exploration",
        target_language="English",
    )
    material = (
        "A research team adopted a shared planning tool. Some members welcomed the "
        "visibility, while others worried that decisions were becoming opaque."
    )

    def run_and_require_round(start: Callable[..., object], code: str) -> None:
        finished = threading.Event()
        unexpected = threading.Event()
        agent_results: list[object] = []
        synthesis_results: list[object] = []
        try:
            start(
                on_agent_complete=agent_results.append,
                on_synthesis_complete=synthesis_results.append,
                on_all_complete=finished.set,
                on_unexpected_error=unexpected.set,
            )
        except Exception:
            service.cancel_active_generation()
            pytest.fail(f"{code}_start_failed", pytrace=False)
        if not finished.wait(timeout=600):
            service.cancel_active_generation()
            finished.wait(timeout=5)
            pytest.fail(f"{code}_timeout", pytrace=False)
        if unexpected.is_set():
            pytest.fail(f"{code}_unexpected_failure", pytrace=False)
        if len(agent_results) != 3:
            pytest.fail(f"{code}_perspective_count_invalid", pytrace=False)
        for response in agent_results:
            if (
                getattr(response, "status", None) != "completed"
                or not getattr(response, "is_complete", False)
                or not str(getattr(response, "text", "")).strip()
            ):
                pytest.fail(f"{code}_perspective_incomplete", pytrace=False)
        if len(synthesis_results) != 1:
            pytest.fail(f"{code}_synthesis_count_invalid", pytrace=False)
        summary = synthesis_results[0]
        if (
            getattr(summary, "status", None) != "completed"
            or not getattr(summary, "is_complete", False)
            or not str(getattr(summary, "text", "")).strip()
        ):
            pytest.fail(f"{code}_synthesis_incomplete", pytrace=False)

    run_and_require_round(
        lambda **callbacks: service.start_new_discussion(
            material=material,
            question="Identify the central tension in one concise paragraph.",
            agents=agents,
            title="Authorized External Reliability",
            material_context=context,
            synthesis_config=synthesis,
            sequential_mode=True,
            **callbacks,
        ),
        "authorized_round_one",
    )
    run_and_require_round(
        lambda **callbacks: service.continue_discussion(
            user_input="What alternative interpretation should be considered? Answer concisely.",
            agents=agents,
            sequential_mode=True,
            **callbacks,
        ),
        "authorized_round_two",
    )

    file_id = service.current_session_file_id()
    if not file_id:
        pytest.fail("authorized_session_id_missing", pytrace=False)
    reopened = DiscussionService(
        settings=settings,
        llm_manager=manager,
        prompt_repo=PromptRepository(base_path=prompt_root),
        storage_dir=tmp_path / "discussions",
        session_context_dir=prompt_root / "session_contexts",
    )
    if not reopened.open_session(file_id):
        pytest.fail("authorized_session_reopen_failed", pytrace=False)
    if reopened.state.round_number != 2 or reopened.state.round_status != "completed":
        pytest.fail("authorized_session_terminal_state_invalid", pytrace=False)
    completed_agents = [
        message
        for message in reopened.state.messages
        if message.role == "agent" and message.status == "completed" and message.content.strip()
    ]
    completed_syntheses = [
        message
        for message in reopened.state.messages
        if message.role == "synthesis" and message.status == "completed" and message.content.strip()
    ]
    if len(completed_agents) != 6 or len(completed_syntheses) != 2:
        pytest.fail("authorized_session_persisted_results_invalid", pytrace=False)


def test_authorized_service_cancellation_and_recovery(tmp_path: Path) -> None:
    _require_enabled()
    config = load_authorized_external_config()
    host_id = "authorized-test-host"
    prompt_root = Path("data/prompts").resolve()
    settings = Settings(
        known_llm_hosts={
            host_id: {
                "url": config.api_base,
                "api_key": config.api_key,
                "model": config.model,
                "models": [config.model],
                "is_favorite": True,
                "context_tokens": 32_768,
            }
        },
        prompt_library_path=str(prompt_root),
        prompt_defaults_path=str(prompt_root),
        llm_timeout=180,
        llm_connect_timeout=10,
        llm_health_timeout=10,
        llm_health_retries=0,
        llm_max_retries=0,
    )
    manager = LLMManager(settings)
    llm = manager.get_llm(
        host=config.api_base,
        model_name=config.model,
        host_configuration_id=host_id,
    )
    if not isinstance(llm, OpenAICompatibleLLM):
        pytest.fail("authorized_adapter_type_invalid", pytrace=False)
    # Keep the authorized live-test ceiling separate from product behavior.
    llm.stream_timeout = (10, 300)
    llm.session = BudgetedSession(config, load_authorized_external_budget())
    service = DiscussionService(
        settings=settings,
        llm_manager=manager,
        prompt_repo=PromptRepository(base_path=prompt_root),
        storage_dir=tmp_path / "discussions",
        session_context_dir=prompt_root / "session_contexts",
    )
    perspectives = service.get_available_perspectives()
    if not perspectives:
        pytest.fail("authorized_perspective_catalog_empty", pytrace=False)
    prompt_id, label = perspectives[0]
    agent = AgentConfig(
        name=label,
        client_id="authorized-cancellation-perspective",
        prompt_id=prompt_id,
        color="#2563eb",
        temperature=0,
        llm_id=config.model,
        api_host=config.api_base,
        host_configuration_id=host_id,
        host_label=host_id,
        max_tokens=2048,
        perspective_number=1,
    )
    context = MaterialContext(
        material_type="document",
        session_type="exploration",
        target_language="English",
    )
    material = (
        "A research team adopted a shared planning tool. Some members welcomed the "
        "visibility, while others worried that decisions were becoming opaque."
    )
    first_chunk = threading.Event()
    cancelled_done = threading.Event()
    service.start_new_discussion(
        material=material,
        question="Develop a detailed five-part analysis of the central tension.",
        agents=[agent],
        material_context=context,
        synthesis_config=SynthesisConfig(enabled=False, api_host=None, llm_id=None),
        on_chunk=lambda _response: first_chunk.set(),
        on_all_complete=cancelled_done.set,
    )
    if not first_chunk.wait(timeout=300):
        service.cancel_active_generation()
        pytest.fail("authorized_cancellation_no_visible_output", pytrace=False)
    if not service.cancel_active_generation():
        pytest.fail("authorized_cancellation_not_active", pytrace=False)
    if not cancelled_done.wait(timeout=5):
        pytest.fail("authorized_cancellation_timeout", pytrace=False)
    if service.state.round_status != "interrupted":
        pytest.fail("authorized_cancellation_state_invalid", pytrace=False)

    interrupted_id = service.current_session_file_id()
    reopened = DiscussionService(
        settings=settings,
        llm_manager=manager,
        prompt_repo=PromptRepository(base_path=prompt_root),
        storage_dir=tmp_path / "discussions",
        session_context_dir=prompt_root / "session_contexts",
    )
    if not interrupted_id or not reopened.open_session(interrupted_id):
        pytest.fail("authorized_cancelled_session_reopen_failed", pytrace=False)
    if reopened.state.round_status != "interrupted":
        pytest.fail("authorized_cancelled_session_state_invalid", pytrace=False)

    recovery_done = threading.Event()
    recovery_results: list[object] = []
    service.start_new_discussion(
        material=material,
        question="Explain one constructive response in a concise paragraph.",
        agents=[agent],
        material_context=context,
        synthesis_config=SynthesisConfig(enabled=False, api_host=None, llm_id=None),
        on_agent_complete=recovery_results.append,
        on_all_complete=recovery_done.set,
    )
    if not recovery_done.wait(timeout=300):
        service.cancel_active_generation()
        pytest.fail("authorized_recovery_timeout", pytrace=False)
    if len(recovery_results) != 1:
        pytest.fail("authorized_recovery_count_invalid", pytrace=False)
    recovered = recovery_results[0]
    if (
        getattr(recovered, "status", None) != "completed"
        or not str(getattr(recovered, "text", "")).strip()
    ):
        pytest.fail("authorized_recovery_incomplete", pytrace=False)
