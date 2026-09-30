"""Integration tests for simulated discussion flows.

These tests simulate realistic multi-agent discussions. All LLM calls are
mocked; the tests verify orchestration, state management, persistence, and
information flow between rounds.

Scenarios:
    1. Single round, one agent
    2. Single round, multiple agents
    3. Multi-round discussion
    4. Sequential mode
    5. Save and reload
    6. Material context
    7. Error isolation
    8. Complete material-to-export workflow
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.service.discussion import (
    AgentConfig as _AgentConfig,
)
from src.service.discussion import (
    AgentResponse,
    DiscussionService,
    MaterialContext,
)


def AgentConfig(*args, **kwargs):
    """Build current-contract agent fixtures."""

    kwargs.setdefault("client_id", f"flow-{kwargs.get('name', 'agent')}")
    if kwargs.get("perspective_number", 0) <= 0:
        kwargs["perspective_number"] = 1
    return _AgentConfig(*args, **kwargs)


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

FOCUS_SEGMENT = (
    "Die Jüngeren waren sofort dabei, aber einige ältere Kollegen "
    "haben sich geweigert es zu nutzen."
)


AGENTS_TRIO = [
    AgentConfig(
        name="Systemtheorie",
        prompt_id="sys_theory",
        color="#2563eb",
        temperature=0.7,
        perspective_number=1,
    ),
    AgentConfig(
        name="Kritische Theorie",
        prompt_id="crit_theory",
        color="#dc2626",
        temperature=0.8,
        perspective_number=2,
    ),
    AgentConfig(
        name="Pragmatismus",
        prompt_id="pragmatism",
        color="#16a34a",
        temperature=0.6,
        perspective_number=3,
    ),
]

AGENTS_SINGLE = [AGENTS_TRIO[0]]

AGENTS_WITH_INACTIVE = [
    AGENTS_TRIO[0],
    AgentConfig(name="Deaktiviert", prompt_id=None, color="#999", perspective_number=2),
    AGENTS_TRIO[2],
]


SIMULATED_RESPONSES: dict[str, dict[int, str]] = {
    "Systemtheorie": {
        1: (
            "Aus systemtheoretischer Perspektive zeigt sich hier eine klassische "
            "Differenzierung zwischen System und Umwelt. Die Einführung des neuen "
            "Tools erzeugt eine Perturbation, auf die das soziale System Team "
            "mit Inklusion (jüngere Mitarbeiter) und Exklusion (ältere Kollegen) "
            "reagiert. Die Kommunikation bricht an der Schnittstelle zusammen."
        ),
        2: (
            "Die generationale Lesart greift zu kurz. Was wir beobachten ist eine "
            "Differenz in der Anschlussfähigkeit von Kommunikation. Die 'Weigerung' "
            "ist funktional: Sie stabilisiert bestehende Erwartungsstrukturen. Der "
            "Konflikt entsteht nicht durch Alter, sondern durch inkompatible "
            "Anschlussoperationen."
        ),
    },
    "Kritische Theorie": {
        1: (
            "Hier manifestiert sich eine Machtasymmetrie: Die Digitalisierung wird "
            "als unhintergehbare Sachlogik präsentiert, die keine Widerrede duldet. "
            "Die 'Weigerung' älterer Kollegen kann als Widerstand gegen eine "
            "technokratische Rationalität gelesen werden, die ihre Erfahrungswissen "
            "entwertet. Wer das Tool beherrscht, gewinnt symbolisches Kapital."
        ),
        2: (
            "Exakt — der generationale Rahmen verschleiert die eigentliche "
            "Dimension: Es geht um die Verteilung von Definitionsmacht. Die "
            "'Jüngeren' profitieren nicht aufgrund ihres Alters, sondern weil "
            "ihre Kompetenzen im aktuellen Verwertungszusammenhang höher bewertet "
            "werden. Das ist ideology in Aktion."
        ),
    },
    "Pragmatismus": {
        1: (
            "Pragmatisch betrachtet zeigt der Fall ein Handlungsproblem: Die "
            "Einführung des Tools wurde offenbar ohne ausreichende Einbindung "
            "aller Beteiligten durchgeführt. Die 'Spannungen' entstehen aus "
            "unterschiedlichen Problemdefinitionen — nicht aus Technikfeindlichkeit. "
            "Entscheidend wäre: Was brauchen die Betroffenen, um handlungsfähig "
            "zu bleiben?"
        ),
        2: (
            "Der generationale Rahmen bietet zwar eine alltagsweltliche Erklärung, "
            "lenkt aber von der konkreten Situation ab. Pragmatisch relevant ist: "
            "Wurde ein gemeinsamer Problemlösungsprozess initiiert? Die 'Weigerung' "
            "signalisiert ungelöste praktische Probleme, nicht Verweigerungshaltung."
        ),
    },
}


def _make_llm_mock(responses: dict[str, dict[int, str]]):
    """Create an LLM mock that returns agent-specific responses.

    The mock counts calls internally and returns the response for each
    agent and round.
    """
    call_counter: dict[str, int] = {}

    def generate_stream(prompt, temperature=0.7, max_tokens=2048, system_prompt=None, **_kwargs):
        """Return the simulated response selected by the system prompt."""
        # Derive the agent name from the system prompt or call order.
        matched_agent = None
        if system_prompt:
            for agent_name in responses:
                if agent_name.lower() in system_prompt.lower():
                    matched_agent = agent_name
                    break

        if matched_agent is None:
            # Fallback: count completed rounds.
            matched_agent = list(responses.keys())[len(call_counter) % len(responses)]

        call_counter.setdefault(matched_agent, 0)
        call_counter[matched_agent] += 1
        round_num = call_counter[matched_agent]

        text = responses.get(matched_agent, {}).get(
            round_num, f"[{matched_agent} Runde {round_num}]"
        )

        words = text.split()
        chunk_size = max(1, len(words) // 3)
        for i in range(0, len(words), chunk_size):
            yield " ".join(words[i : i + chunk_size]) + " "

    return generate_stream


def _make_prompt_templates():
    """Build mock templates for the three standard perspectives."""
    templates = {}
    for entry in [
        ("sys_theory", "Systemtheorie", "Du bist Systemtheoretiker nach Luhmann."),
        (
            "crit_theory",
            "Kritische Theorie",
            "Du vertrittst die Kritische Theorie nach Adorno/Horkheimer.",
        ),
        ("pragmatism", "Pragmatismus", "Du analysierst aus pragmatistischer Sicht nach Dewey."),
    ]:
        t = MagicMock()
        t.id, t.label, t.role = entry
        t.task = "Analysiere das Material aus deiner Perspektive."
        t.output_format = "Strukturierte Analyse mit Kernthesen."
        templates[t.id] = t
    return templates


def _build_service(tmp_path, responses=None) -> DiscussionService:
    """Build a fully mocked DiscussionService."""
    settings = MagicMock()
    settings.max_tokens = 2048

    llm_manager = MagicMock()
    llm = MagicMock()
    llm.generate_stream = _make_llm_mock(responses or SIMULATED_RESPONSES)
    llm_manager.llm = llm
    llm_manager.get_llm.return_value = llm

    prompt_repo = MagicMock()
    templates = _make_prompt_templates()
    prompt_repo.list_templates.return_value = list(templates.values())
    prompt_repo.get_common_instructions.return_value = (
        "ALLGEMEINE PRINZIPIEN:\n- Wissenschaftliche Argumentation\n"
        "- Respektvoller Diskurs\n- Belege aus dem Material"
    )

    service = DiscussionService(
        settings=settings,
        llm_manager=llm_manager,
        prompt_repo=prompt_repo,
        storage_dir=tmp_path / "discussions",
        session_context_dir=Path("data/prompts/session_contexts"),
    )
    # The production discussion contract requires an explicit response
    # language before a model call. These direct service tests model a prepared
    # discussion rather than bypassing that invariant.
    service._material_context = MaterialContext(target_language="German")
    return service


class TestScenario1_SingleRoundSingleAgent:
    def test_agent_answers_from_material(self, tmp_path):
        svc = _build_service(tmp_path)
        results = svc.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=AGENTS_SINGLE,
            on_agent_start=lambda r: None,
        )
        assert len(results) == 1
        assert results[0].agent_name == "Systemtheorie"
        assert results[0].is_complete
        assert len(results[0].text) > 50  # Substantive response.

    def test_callbacks_are_invoked(self, tmp_path):
        svc = _build_service(tmp_path)
        events = []
        svc.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=AGENTS_SINGLE,
            on_agent_start=lambda r: events.append(("start", r.agent_name)),
            on_chunk=lambda r: events.append(("chunk", r.agent_name)),
            on_agent_complete=lambda r: events.append(("complete", r.agent_name)),
            on_all_complete=lambda: events.append(("all_done",)),
        )
        event_types = [e[0] for e in events]
        assert "start" in event_types
        assert "chunk" in event_types
        assert "complete" in event_types
        assert "all_done" in event_types

    def test_system_prompt_contains_role(self, tmp_path):
        svc = _build_service(tmp_path)
        prompt = svc.build_system_prompt("sys_theory")
        assert "Systemtheoretiker" in prompt


class TestScenario2_SingleRoundMultiAgent:
    def test_three_agents_answer(self, tmp_path):
        svc = _build_service(tmp_path)
        results = svc.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=AGENTS_TRIO,
            on_agent_start=lambda r: None,
        )
        assert len(results) == 3
        names = {r.agent_name for r in results}
        assert names == {"Systemtheorie", "Kritische Theorie", "Pragmatismus"}

    def test_inactive_agents_are_skipped(self, tmp_path):
        svc = _build_service(tmp_path)
        results = svc.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=AGENTS_WITH_INACTIVE,
            on_agent_start=lambda r: None,
        )
        names = {r.agent_name for r in results}
        assert "Deaktiviert" not in names
        assert len(results) == 2

    def test_jeder_agent_keeps_only_its_numeric_identity(self, tmp_path):
        svc = _build_service(tmp_path)
        agent = AGENTS_TRIO[0]
        prompt = svc.build_system_prompt(
            prompt_id=agent.prompt_id,
            agent_config=agent,
            agent_index=0,
            total_agents=3,
            other_agents=[
                ("Kritische Theorie", "Kritische Theorie"),
                ("Pragmatismus", "Pragmatismus"),
            ],
        )
        assert "You are `Perspective 1`." in prompt
        assert "Kritische Theorie" not in prompt

    def test_responses_are_distinct(self, tmp_path):
        svc = _build_service(tmp_path)
        results = svc.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=AGENTS_TRIO,
            on_agent_start=lambda r: None,
        )
        texts = [r.text.strip() for r in results]
        assert len(set(texts)) == 3

    def test_result_order_matches_agent_list(self, tmp_path):
        svc = _build_service(tmp_path)
        results = svc.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=AGENTS_TRIO,
            on_agent_start=lambda r: None,
        )
        assert results[0].agent_name == "Systemtheorie"
        assert results[1].agent_name == "Kritische Theorie"
        assert results[2].agent_name == "Pragmatismus"


class TestScenario3_MultiRoundDiscussion:
    def test_state_after_round_one(self, tmp_path):
        svc = _build_service(tmp_path)
        svc.state.material = INTERVIEW_MATERIAL
        svc.state.initial_question = INITIAL_QUESTION
        svc.state.round_number = 1
        svc.state.add_user_message(INITIAL_QUESTION)

        results = svc.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=AGENTS_TRIO,
            on_agent_start=lambda r: None,
        )

        # Add responses to state, as the public start path does.
        for r in results:
            svc.state.add_agent_response(r)

        assert svc.state.round_number == 1
        assert len(svc.state.messages) == 4
        assert svc.state.messages[0].role == "user"
        assert svc.state.messages[1].role == "agent"

    def test_round_two_context_contains_round_one(self, tmp_path):
        svc = _build_service(tmp_path)
        svc.state.material = INTERVIEW_MATERIAL
        svc.state.initial_question = INITIAL_QUESTION
        svc.state.round_number = 1

        svc.state.add_user_message(INITIAL_QUESTION)
        for agent in AGENTS_TRIO:
            resp = AgentResponse(
                message_id=f"msg-{agent.name}",
                agent_index=0,
                agent_name=agent.name,
                theory_label=agent.name,
                color=agent.color,
                text=SIMULATED_RESPONSES[agent.name][1],
                is_complete=True,
            )
            svc.state.add_agent_response(resp)

        svc.state.round_number = 2
        svc.state.add_user_message(FOLLOWUP_QUESTION)

        context = svc.state.get_context_for_agents()

        assert "Digitalisierung" in context or "Interview" in context
        assert "Systemtheorie" in context or "Perturbation" in context

    def test_two_round_discussion_completes(self, tmp_path):
        svc = _build_service(tmp_path)
        llm = svc.llm_manager.get_llm.return_value
        original_generate_stream = llm.generate_stream
        sent_prompts: list[str] = []

        def capture_prompt(*args, **kwargs):
            sent_prompts.append(kwargs["prompt"])
            yield from original_generate_stream(*args, **kwargs)

        llm.generate_stream = capture_prompt

        svc.state.material = INTERVIEW_MATERIAL
        svc.state.initial_question = INITIAL_QUESTION
        svc.state.round_number = 1
        svc.state.add_user_message(INITIAL_QUESTION)

        r1_results = svc.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=AGENTS_TRIO,
            on_agent_start=lambda r: None,
        )
        for r in r1_results:
            svc.state.add_agent_response(r)

        assert len(r1_results) == 3

        svc.state.round_number = 2
        svc.state.add_user_message(FOLLOWUP_QUESTION)

        r2_results = svc.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=FOLLOWUP_QUESTION,
            agents=AGENTS_TRIO,
            on_agent_start=lambda r: None,
        )
        for r in r2_results:
            svc.state.add_agent_response(r)

        assert len(r2_results) == 3
        assert len(svc.state.messages) == 8
        round_two_prompts = sent_prompts[-3:]
        assert all(
            prompt.count("=== CURRENT RESPONSE LANGUAGE REMINDER ===") == 1
            for prompt in round_two_prompts
        )
        assert all(
            message.content.find("CURRENT RESPONSE LANGUAGE REMINDER") < 0
            for message in svc.state.messages
        )

    def test_reset_clears_state(self, tmp_path):
        svc = _build_service(tmp_path)
        svc.state.material = INTERVIEW_MATERIAL
        svc.state.round_number = 2
        svc.state.add_user_message("Test")

        svc.reset_discussion()

        assert svc.state.round_number == 0
        assert svc.state.messages == []
        assert svc.state.material == ""


class TestScenario4_SequentialMode:
    def test_sequential_flag_is_accepted(self, tmp_path):
        svc = _build_service(tmp_path)
        results = svc.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=AGENTS_TRIO,
            on_agent_start=lambda r: None,
            sequential_mode=True,
        )
        assert len(results) == 3

    def test_second_agent_sees_first(self, tmp_path):
        svc = _build_service(tmp_path)
        prompts: list[str] = []

        def generate_stream(*, prompt, **_kwargs):
            prompts.append(prompt)
            yield f"Antwort {len(prompts)}"

        svc.llm_manager.get_llm.return_value.generate_stream = generate_stream
        svc.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=AGENTS_TRIO,
            on_agent_start=lambda r: None,
            sequential_mode=True,
        )

        assert "Antwort 1" in prompts[1]
        assert all(
            prompt.endswith(
                "=== CURRENT RESPONSE LANGUAGE REMINDER ===\nWrite all prose in German."
            )
            for prompt in prompts
        )
        assert all(prompt.count("CURRENT RESPONSE LANGUAGE REMINDER") == 1 for prompt in prompts)


class TestScenario6_MaterialContext:
    @pytest.mark.parametrize(
        "material_type,expected_label",
        [
            ("interview", "Interview"),
            ("focus_group", "Focus Group"),
            ("document", "Text Document"),
            ("media", "Multimedia Transcript"),
            ("fieldnotes", "Field Notes"),
            ("memo", "Research Memo"),
            ("other", "Other"),
        ],
    )
    def test_material_type_in_prompt(self, tmp_path, material_type, expected_label):
        svc = _build_service(tmp_path)
        mc = MaterialContext(material_type=material_type)
        prompt = svc.build_system_prompt("sys_theory", material_context=mc)
        assert f"MATERIAL TYPE: {expected_label}" in prompt

    def test_research_material_context_in_prompt(self, tmp_path):
        svc = _build_service(tmp_path)
        mc = MaterialContext(
            material_type="interview",
            session_input_values={"research_material_context": "Ab Minute 12 wird emotional"},
        )
        prompt = svc.build_system_prompt("sys_theory", material_context=mc)
        assert "Ab Minute 12 wird emotional" in prompt

    def test_exploration_task_im_prompt(self, tmp_path):
        svc = _build_service(tmp_path)
        mc = MaterialContext(
            material_type="interview",
            session_input_values={"main_input": "Proband 42, Erstinterview"},
        )
        prompt = svc.build_system_prompt("sys_theory", material_context=mc)
        assert "Proband 42" in prompt


class TestScenario7_ErrorIsolation:
    def test_one_agent_error_does_not_stop_others(self, tmp_path):
        svc = _build_service(tmp_path)

        call_count = {"n": 0}
        original_stream = svc.llm_manager.llm.generate_stream

        def flaky_stream(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise ConnectionError("LM Studio timeout")
            return original_stream(*args, **kwargs)

        svc.llm_manager.llm.generate_stream = flaky_stream

        results = svc.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=AGENTS_TRIO,
            on_agent_start=lambda r: None,
        )

        assert len(results) == 3
        errors = [r for r in results if r.error]
        successes = [r for r in results if not r.error]
        assert len(errors) == 1
        assert len(successes) == 2
        assert "timeout" in errors[0].error

    def test_empty_material_does_not_crash(self, tmp_path):
        svc = _build_service(tmp_path)
        results = svc.run_discussion(
            material="",
            question="Was sagen Sie dazu?",
            agents=AGENTS_SINGLE,
            on_agent_start=lambda r: None,
        )
        assert len(results) == 1
        assert results[0].is_complete


class TestScenario8_CompleteWorkflow:
    def test_complete_workflow(self, tmp_path):
        svc = _build_service(tmp_path)
        events_log: list[str] = []

        material_ctx = MaterialContext(
            material_type="interview",
            target_language="German",
            session_input_values={
                "research_material_context": "Zeile 5-8 besonders emotional",
                "main_input": "Proband 42, Erstinterview",
            },
        )

        svc.state.material = INTERVIEW_MATERIAL
        svc.state.initial_question = INITIAL_QUESTION
        svc.state.round_number = 1
        svc.state.add_user_message(INITIAL_QUESTION)
        svc._current_agents = AGENTS_TRIO

        r1 = svc.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=INITIAL_QUESTION,
            agents=AGENTS_TRIO,
            material_context=material_ctx,
            on_agent_start=lambda r: events_log.append(f"R1:start:{r.agent_name}"),
            on_agent_complete=lambda r: events_log.append(f"R1:done:{r.agent_name}"),
            on_all_complete=lambda: events_log.append("R1:all_done"),
        )
        for r in r1:
            svc.state.add_agent_response(r)

        assert len(r1) == 3
        assert "R1:all_done" in events_log

        svc.state.round_number = 2
        svc.state.add_user_message(FOLLOWUP_QUESTION)

        r2 = svc.run_discussion(
            material=INTERVIEW_MATERIAL,
            question=FOLLOWUP_QUESTION,
            agents=AGENTS_TRIO,
            material_context=material_ctx,
            on_agent_start=lambda r: events_log.append(f"R2:start:{r.agent_name}"),
            on_agent_complete=lambda r: events_log.append(f"R2:done:{r.agent_name}"),
            on_all_complete=lambda: events_log.append("R2:all_done"),
        )
        for r in r2:
            svc.state.add_agent_response(r)

        assert len(r2) == 3
        assert "R2:all_done" in events_log
        # 2 User + 6 Agent = 8 Messages
        assert len(svc.state.messages) == 8
