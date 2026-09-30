"""Opt-in integration tests against a local OpenAI-compatible model host.

Set ``AQA_RUN_LIVE_LLM_TESTS=1`` only when a local host with a loaded model is
available. The ordinary suite must never contact a provider endpoint.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest
import requests

from src.config.settings import Settings
from src.llm.llm_manager import LLMManager
from src.prompts.storage import PromptRepository
from src.service.discussion import (
    AgentConfig,
    DiscussionService,
    MaterialContext,
)
from tests.live_llm_support import (
    LiveLLMConfig,
    LiveLLMConfigurationError,
    discover_live_llm_config,
)

# Every test in this module is an opt-in integration test.
pytestmark = pytest.mark.integration


# Opt-in and configuration: no live host is contacted unless explicitly enabled.
def _fetch_live_model_ids(host: str) -> list[str] | None:
    """Return advertised model IDs, or ``None`` when a host is unreachable."""
    try:
        resp = requests.get(f"{host}/v1/models", timeout=3)
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data", []) if isinstance(data, dict) else []
        return [str(model["id"]) for model in models if isinstance(model, dict) and model.get("id")]
    except Exception:
        return None


_LIVE_TESTS_ENABLED = os.getenv("AQA_RUN_LIVE_LLM_TESTS", "").strip() == "1"
_LIVE_CONFIG: LiveLLMConfig | None = None
_LIVE_CONFIG_ERROR: str | None = None
if _LIVE_TESTS_ENABLED:
    try:
        _LIVE_CONFIG = discover_live_llm_config(_fetch_live_model_ids)
    except LiveLLMConfigurationError as exc:
        _LIVE_CONFIG_ERROR = str(exc)


# Test material
INTERVIEW_MATERIAL = """
Interviewer: Wie hat sich Ihre Arbeit in den letzten Jahren verändert?

Befragter: Also, die Digitalisierung hat natürlich alles verändert. Früher
hatten wir klare Abläufe, jeder wusste was zu tun ist. Jetzt kommen ständig
neue Tools, neue Prozesse. Manche Kollegen kommen damit gut klar, andere
fühlen sich abgehängt. Das erzeugt Spannungen im Team.

Interviewer: Können Sie ein konkretes Beispiel nennen?

Befragter: Ja, letztes Jahr haben wir ein neues Projektmanagement-Tool
eingeführt. Die Jüngeren waren sofort dabei, aber einige ältere Kollegen
haben sich geweigert es zu nutzen. Das hat zu echten Konflikten geführt,
weil Informationen nicht mehr ankamen.
"""

INITIAL_QUESTION = (
    "Welche sozialen Dynamiken und Spannungsfelder lassen sich in diesem "
    "Interview-Ausschnitt identifizieren?"
)

FOLLOWUP_QUESTION = (
    "Inwiefern könnte die beschriebene Situation als Ausdruck eines "
    "generationalen Konflikts interpretiert werden?"
)


@pytest.fixture(scope="module")
def live_config() -> LiveLLMConfig:
    """Require explicit, unambiguous configuration for an opted-in live run."""
    if not _LIVE_TESTS_ENABLED:
        pytest.skip("Live-LLM-Tests benötigen AQA_RUN_LIVE_LLM_TESTS=1.")
    if _LIVE_CONFIG_ERROR:
        pytest.fail(f"Ungültige Live-LLM-Testkonfiguration: {_LIVE_CONFIG_ERROR}")
    assert _LIVE_CONFIG is not None
    return _LIVE_CONFIG


@pytest.fixture(scope="module")
def live_settings(live_config: LiveLLMConfig) -> Settings:
    """Use settings matching the configured model and backend."""
    return Settings(
        llm_backend=live_config.backend,
        llm_host=live_config.host,
        llm_model=live_config.model,
        max_tokens=live_config.max_tokens,
        temperature=0.7,
    )


@pytest.fixture(scope="module")
def live_llm_manager(live_settings) -> LLMManager:
    """Use a real ``LLMManager`` connected to LM Studio."""
    return LLMManager(live_settings)


@pytest.fixture(scope="module")
def live_prompt_repo(live_settings) -> PromptRepository:
    """Build a PromptRepository from the configured POML assets."""
    return PromptRepository(base_path=Path(live_settings.prompt_library_path))


@pytest.fixture
def live_service(tmp_path, live_settings, live_llm_manager, live_prompt_repo) -> DiscussionService:
    """Build a DiscussionService backed by the configured local host."""
    return DiscussionService(
        settings=live_settings,
        llm_manager=live_llm_manager,
        prompt_repo=live_prompt_repo,
        storage_dir=tmp_path / "discussions",
    )


def _get_available_prompt_ids(service: DiscussionService) -> list[str]:
    """Return all available perspective ids."""
    return [pid for pid, _ in service.get_available_perspectives()]


def _pick_agents(service: DiscussionService, count: int = 3) -> list[AgentConfig]:
    """Select the first N available perspectives as agents."""
    perspectives = service.get_available_perspectives()
    agents = []
    colors = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c"]
    for i, (pid, label) in enumerate(perspectives[:count]):
        agents.append(
            AgentConfig(
                name=label,
                prompt_id=pid,
                color=colors[i % len(colors)],
                temperature=0.7,
            )
        )
    return agents


def _self_reference_patterns(agent_name: str) -> list[re.Pattern[str]]:
    escaped = re.escape(agent_name)
    verbs = r"(meint|sagt|sieht|argumentiert|glaubt|findet|würde sagen|vertritt)"
    return [
        re.compile(rf"\b{escaped}\b\s+{verbs}", re.IGNORECASE),
        re.compile(rf"\blaut\s+{escaped}\b", re.IGNORECASE),
        re.compile(rf"\baus\s+sicht\s+von\s+{escaped}\b", re.IGNORECASE),
    ]


class TestLive_Scenario1_SingleRoundSingleAgent:
    def test_agent_returns_substantive_response(self, live_service):
        agents = _pick_agents(live_service, count=1)
        if not agents:
            pytest.skip("Keine Prompt-Templates verfügbar")

        results = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=agents,
            on_agent_start=lambda r: None,
        )

        assert len(results) == 1
        r = results[0]
        assert r.is_complete
        assert r.error is None
        assert len(r.text) > 100, f"Antwort zu kurz ({len(r.text)} Zeichen): {r.text[:200]}"

    def test_streaming_returns_chunks(self, live_service):
        agents = _pick_agents(live_service, count=1)
        if not agents:
            pytest.skip("Keine Prompt-Templates verfügbar")

        chunks: list[str] = []
        results = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=agents,
            on_chunk=lambda r: chunks.append(r.text),
            on_agent_start=lambda r: None,
        )

        assert len(chunks) > 3, f"Nur {len(chunks)} Chunks — Streaming aktiv?"
        reconstructed = "".join(chunks)
        assert results[0].text == reconstructed

    def test_response_refers_to_material(self, live_service):
        agents = _pick_agents(live_service, count=1)
        if not agents:
            pytest.skip("Keine Prompt-Templates verfügbar")

        results = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=agents,
            on_agent_start=lambda r: None,
        )

        text = results[0].text.lower()
        keywords = [
            "digitalisierung",
            "tool",
            "konflikt",
            "team",
            "kollegen",
            "jüngere",
            "ältere",
            "spannung",
        ]
        matches = [kw for kw in keywords if kw in text]
        assert len(matches) >= 2, (
            f"Antwort scheint sich nicht aufs Material zu beziehen. "
            f"Gefundene Keywords: {matches}\nAntwort: {text[:300]}"
        )


class TestLive_Scenario2_MultiAgent:
    def test_all_agents_return_responses(self, live_service):
        agents = _pick_agents(live_service, count=3)
        if len(agents) < 2:
            pytest.skip("Weniger als 2 Prompt-Templates verfügbar")

        results = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=agents,
            on_agent_start=lambda r: None,
        )

        assert len(results) == len(agents)
        for r in results:
            assert r.is_complete
            assert r.error is None
            assert len(r.text) > 50

    def test_responses_are_distinct(self, live_service):
        agents = _pick_agents(live_service, count=2)
        if len(agents) < 2:
            pytest.skip("Weniger als 2 Prompt-Templates verfügbar")

        results = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=agents,
            on_agent_start=lambda r: None,
        )

        assert len(results) >= 2
        # Responses must not be identical.
        assert results[0].text != results[1].text

    def test_callback_order(self, live_service):
        agents = _pick_agents(live_service, count=2)
        if len(agents) < 2:
            pytest.skip("Weniger als 2 Prompt-Templates verfügbar")

        events: list[tuple[str, str]] = []
        live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=agents,
            on_agent_start=lambda r: events.append(("start", r.agent_name)),
            on_chunk=lambda r: events.append(("chunk", r.agent_name)),
            on_agent_complete=lambda r: events.append(("complete", r.agent_name)),
            on_all_complete=lambda: events.append(("all_done", "")),
        )

        event_types = [e[0] for e in events]
        assert event_types[0] == "start"
        assert event_types[-1] == "all_done"
        assert "chunk" in event_types
        assert event_types.count("complete") == len(agents)

    def test_agents_do_not_refer_to_themselves_in_third_person(self, live_service):
        prompt_ids = _get_available_prompt_ids(live_service)
        if len(prompt_ids) < 3:
            pytest.skip("Weniger als 3 Prompt-Templates verfügbar")

        agents = [
            AgentConfig(name="Agent 1", prompt_id=prompt_ids[0], color="#2563eb", temperature=0.7),
            AgentConfig(name="Agent 2", prompt_id=prompt_ids[1], color="#dc2626", temperature=0.7),
            AgentConfig(name="Agent 3", prompt_id=prompt_ids[2], color="#16a34a", temperature=0.7),
        ]

        results = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=(
                "Diskutiert die Passage knapp miteinander. "
                "Bezieht euch auf Unterschiede zwischen euren Lesarten."
            ),
            agents=agents,
            on_agent_start=lambda r: None,
        )

        assert len(results) == 3
        for result in results:
            assert result.is_complete
            assert result.error is None
            assert len(result.text) > 50

            own_name = result.agent_name
            hits = [
                pattern.pattern
                for pattern in _self_reference_patterns(own_name)
                if pattern.search(result.text)
            ]
            assert not hits, (
                f"{own_name} spricht in dritter Person über sich selbst. "
                f"Treffer: {hits}\nAntwort:\n{result.text}"
            )


class TestLive_Scenario3_MultiRound:
    def test_two_round_flow(self, live_service):
        agents = _pick_agents(live_service, count=2)
        if len(agents) < 2:
            pytest.skip("Weniger als 2 Prompt-Templates verfügbar")

        material_ctx = MaterialContext(
            material_type="interview",
            material_label="Proband 42",
        )

        live_service.state.material = INTERVIEW_MATERIAL
        live_service.state.initial_question = INITIAL_QUESTION
        live_service.state.round_number = 1
        live_service.state.add_user_message(INITIAL_QUESTION)
        live_service._current_agents = agents

        r1 = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=agents,
            material_context=material_ctx,
            on_agent_start=lambda r: None,
        )
        for r in r1:
            live_service.state.add_agent_response(r)

        assert len(r1) == 2
        assert all(r.is_complete and not r.error for r in r1)

        live_service.state.round_number = 2
        live_service.state.add_user_message(FOLLOWUP_QUESTION)

        r2 = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=FOLLOWUP_QUESTION,
            agents=agents,
            material_context=material_ctx,
            on_agent_start=lambda r: None,
        )
        for r in r2:
            live_service.state.add_agent_response(r)

        assert len(r2) == 2
        assert all(r.is_complete and not r.error for r in r2)

        # State contains two moderator and four agent messages.
        assert len(live_service.state.messages) == 6

    def test_round_two_addresses_follow_up(self, live_service):
        agents = _pick_agents(live_service, count=1)
        if not agents:
            pytest.skip("Keine Prompt-Templates verfügbar")

        live_service.state.clear()
        live_service.state.material = INTERVIEW_MATERIAL
        live_service.state.initial_question = INITIAL_QUESTION
        live_service.state.round_number = 1
        live_service.state.add_user_message(INITIAL_QUESTION)

        r1 = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=agents,
            on_agent_start=lambda r: None,
        )
        for r in r1:
            live_service.state.add_agent_response(r)

        live_service.state.round_number = 2
        live_service.state.add_user_message(FOLLOWUP_QUESTION)

        r2 = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=FOLLOWUP_QUESTION,
            agents=agents,
            on_agent_start=lambda r: None,
        )

        text = r2[0].text.lower()
        # The follow-up asks about generational dynamics.
        generation_keywords = [
            "generation",
            "alter",
            "jung",
            "alt",
            "generational",
            "altersgruppe",
            "kohorte",
        ]
        matches = [kw for kw in generation_keywords if kw in text]
        assert len(matches) >= 1, (
            f"Runde-2-Antwort geht nicht auf generationale Frage ein. "
            f"Gefundene Keywords: {matches}\nAntwort: {text[:300]}"
        )


class TestLive_Scenario4_SequentialMode:
    def test_sequential_returns_results(self, live_service):
        agents = _pick_agents(live_service, count=2)
        if len(agents) < 2:
            pytest.skip("Weniger als 2 Prompt-Templates")

        results = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=agents,
            on_agent_start=lambda r: None,
            sequential_mode=True,
        )

        assert len(results) == 2
        assert all(r.is_complete for r in results)


class TestLive_Scenario5_Persistence:
    def test_save_load_real_responses(self, live_service):
        agents = _pick_agents(live_service, count=1)
        if not agents:
            pytest.skip("Keine Prompt-Templates")

        live_service.state.material = INTERVIEW_MATERIAL
        live_service.state.initial_question = INITIAL_QUESTION
        live_service.state.round_number = 1
        live_service.state.add_user_message(INITIAL_QUESTION)
        live_service._current_agents = agents

        results = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=agents,
            on_agent_start=lambda r: None,
        )
        for r in results:
            live_service.state.add_agent_response(r)

        filepath = live_service.save_discussion(title="Live-Test")
        assert filepath is not None
        assert filepath.exists()

        listing = live_service.list_saved_discussions()
        assert len(listing) >= 1

        stored = live_service.storage.load(listing[0]["filename"])
        assert stored is not None
        assert stored.title == "Live-Test"

        md = stored.to_markdown()
        assert "# Live-Test" in md
        # The exported markdown contains the model response.
        assert len(md) > 200


class TestLive_Scenario6_MaterialContext:
    def test_interview_context_is_included(self, live_service):
        agents = _pick_agents(live_service, count=1)
        if not agents:
            pytest.skip("Keine Prompt-Templates")

        material_ctx = MaterialContext(
            material_type="interview",
            material_label="Proband 42, Erstinterview",
            researcher_note="Besonders die Passage über die Weigerung beachten.",
        )

        results = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=agents,
            material_context=material_ctx,
            on_agent_start=lambda r: None,
        )

        assert results[0].is_complete
        assert len(results[0].text) > 100


class TestLive_Scenario7_CompleteWorkflow:
    def test_end_to_end(self, live_service):
        agents = _pick_agents(live_service, count=2)
        if len(agents) < 2:
            pytest.skip("Weniger als 2 Prompt-Templates")

        material_ctx = MaterialContext(
            material_type="interview",
            material_label="Proband 42",
            researcher_note="Digitalisierungskonflikt im Team",
        )
        events: list[str] = []

        live_service.state.clear()
        live_service.state.material = INTERVIEW_MATERIAL
        live_service.state.initial_question = INITIAL_QUESTION
        live_service.state.round_number = 1
        live_service.state.add_user_message(INITIAL_QUESTION)
        live_service._current_agents = agents

        r1 = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=agents,
            material_context=material_ctx,
            on_agent_start=lambda r: events.append(f"R1:start:{r.agent_name}"),
            on_agent_complete=lambda r: events.append(f"R1:done:{r.agent_name}"),
            on_all_complete=lambda: events.append("R1:all_done"),
        )
        for r in r1:
            live_service.state.add_agent_response(r)

        assert len(r1) == 2
        assert all(r.is_complete and not r.error for r in r1)
        assert "R1:all_done" in events

        live_service.state.round_number = 2
        live_service.state.add_user_message(FOLLOWUP_QUESTION)

        r2 = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=FOLLOWUP_QUESTION,
            agents=agents,
            material_context=material_ctx,
            on_agent_start=lambda r: events.append(f"R2:start:{r.agent_name}"),
            on_agent_complete=lambda r: events.append(f"R2:done:{r.agent_name}"),
            on_all_complete=lambda: events.append("R2:all_done"),
        )
        for r in r2:
            live_service.state.add_agent_response(r)

        assert len(r2) == 2
        assert "R2:all_done" in events

        filepath = live_service.save_discussion(title="E2E Live-Test")
        assert filepath.exists()

        listing = live_service.list_saved_discussions()
        entry = next(e for e in listing if e["title"] == "E2E Live-Test")

        stored = live_service.storage.load(entry["filename"])
        assert stored is not None

        md = stored.to_markdown()
        assert "# E2E Live-Test" in md
        assert "Runde 1" in md

        all_responses = r1 + r2
        for r in all_responses:
            assert len(r.text) > 50, f"{r.agent_name} hat zu kurz geantwortet"


class TestLive_Scenario8_Performance:
    def test_single_agent_responds_within_60_seconds(self, live_service):
        agents = _pick_agents(live_service, count=1)
        if not agents:
            pytest.skip("Keine Prompt-Templates")

        start = time.time()
        results = live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=agents,
            on_agent_start=lambda r: None,
        )
        elapsed = time.time() - start

        assert results[0].is_complete
        assert elapsed < 60, f"Agent brauchte {elapsed:.1f}s — zu langsam"

    def test_first_chunk_arrives_within_5_seconds(self, live_service):
        agents = _pick_agents(live_service, count=1)
        if not agents:
            pytest.skip("Keine Prompt-Templates")

        first_chunk_time = None
        start = time.time()

        def on_chunk(r):
            nonlocal first_chunk_time
            if first_chunk_time is None:
                first_chunk_time = time.time() - start

        live_service.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=agents,
            on_chunk=on_chunk,
            on_agent_start=lambda r: None,
        )

        assert first_chunk_time is not None, "Kein Chunk empfangen"
        assert first_chunk_time < 5.0, f"Erster Chunk nach {first_chunk_time:.1f}s — TTFT zu hoch"
