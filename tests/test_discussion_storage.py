"""Tests for discussion snapshot serialization and filesystem persistence."""

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from src.service.discussion_storage import (
    DiscussionStorage,
    StoredAgent,
    StoredDiscussion,
    StoredMessage,
    StoredPromptSnapshot,
    StoredProviderProvenance,
    StoredRound,
)

_SESSION_INPUTS = [
    {
        "key": "research_material_context",
        "label": "Research Material Context",
        "prompt_heading": "RESEARCH MATERIAL CONTEXT",
        "required": False,
    },
    {
        "key": "main_input",
        "label": "Interpretation",
        "prompt_heading": "USER INPUT",
        "required": True,
    },
    {
        "key": "additional_instructions",
        "label": "Additional Instructions",
        "prompt_heading": "ADDITIONAL USER INSTRUCTIONS",
        "required": False,
    },
]


def _sample_discussion() -> StoredDiscussion:
    return StoredDiscussion(
        id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        created="2025-06-15T10:00:00",
        updated="2025-06-15T10:05:00",
        title="Interview Müller",
        material="Ein beispielhafter Interview-Text.",
        initial_question="Was fällt auf?",
        material_type="interview",
        session_type="critique",
        session_input_values={
            "research_material_context": "Leitfadeninterview mit Berufseinsteigerin",
            "main_input": "Ich lese eine Spannung zwischen Sicherheitsbedürfnis und Aufstiegsorientierung.",
            "additional_instructions": "Bitte zuerst Gegenargumente, dann stützende Evidenz.",
        },
        session_inputs=list(_SESSION_INPUTS),
        include_unchanged_research_material_context_in_prompt=True,
        agents=[
            StoredAgent(
                name="Agent 1",
                client_id="storage-agent-1",
                prompt_id="sys_theory",
                prompt_label="Systemtheorie",
                temperature=0.7,
                perspective_number=1,
            ),
        ],
        rounds=[
            StoredRound(
                round_number=1,
                messages=[
                    StoredMessage(id="msg-user-1", role="user", content="Was fällt auf?"),
                    StoredMessage(
                        id="msg-agent-1",
                        role="agent",
                        content="Aus systemtheoretischer Sicht...",
                        agent_name="Agent 1",
                        theory_label="Systemtheorie",
                        client_id="storage-agent-1",
                        color="#333333",
                        agent_index=0,
                        note="Später für Theorievergleich aufgreifen.",
                        perspective_number=1,
                    ),
                ],
            ),
        ],
    )


class TestStoredDiscussionSerialization:
    def test_to_dict_structure(self):
        d = _sample_discussion().to_dict()
        assert d["id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert d["title"] == "Interview Müller"
        assert d["session_type"] == "critique"
        assert len(d["agents"]) == 1
        assert len(d["rounds"]) == 1
        assert len(d["rounds"][0]["messages"]) == 2
        assert d["rounds"][0]["messages"][1]["id"] == "msg-agent-1"
        assert d["rounds"][0]["messages"][1]["note"] == "Später für Theorievergleich aufgreifen."

    def test_roundtrip(self):
        original = _sample_discussion()
        data = original.to_dict()
        restored = StoredDiscussion.from_dict(data)
        assert restored.id == original.id
        assert restored.title == original.title
        assert restored.material == original.material
        assert restored.session_type == original.session_type
        assert restored.material_type == original.material_type
        assert restored.session_input_values == original.session_input_values
        assert restored.session_inputs == original.session_inputs
        assert restored.include_unchanged_research_material_context_in_prompt is True
        assert len(restored.rounds) == 1
        assert restored.rounds[0].messages[1].agent_name == "Agent 1"
        assert restored.rounds[0].messages[1].note == "Später für Theorievergleich aufgreifen."

    def test_roundtrip_preserves_optional_provider_usage(self):
        original = _sample_discussion()
        message = original.rounds[0].messages[1]
        message.usage_available = True
        message.prompt_tokens = 12
        message.completion_tokens = 3
        message.total_tokens = 15

        restored = StoredDiscussion.from_dict(original.to_dict())
        usage = restored.rounds[0].messages[1]
        assert usage.usage_available is True
        assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (12, 3, 15)

    def test_from_dict_rejects_missing_input_schema(self):
        data = _sample_discussion().to_dict()
        data.pop("input_values", None)
        data.pop("input_definitions", None)
        with pytest.raises(ValueError, match="input_definitions"):
            StoredDiscussion.from_dict(data)

    def test_from_dict_rejects_missing_agent_temperature(self):
        data = _sample_discussion().to_dict()
        del data["agents"][0]["temperature"]
        with pytest.raises(ValueError, match="temperature"):
            StoredDiscussion.from_dict(data)

    def test_from_dict_preserves_explicit_temperature(self):
        data = _sample_discussion().to_dict()
        data["agents"][0]["temperature"] = 0.42
        restored = StoredDiscussion.from_dict(data)
        assert restored.agents[0].temperature == 0.42

    def test_from_dict_explicit_null_temperature_becomes_none(self):
        data = _sample_discussion().to_dict()
        data["agents"][0]["temperature"] = None
        restored = StoredDiscussion.from_dict(data)
        assert restored.agents[0].temperature is None

    def test_to_dict_emits_explicit_null_when_temperature_is_none(self):
        agent = StoredAgent(
            name="Agent 1",
            prompt_id="sys_theory",
            prompt_label="Systemtheorie",
            temperature=None,
            perspective_number=1,
        )
        d = StoredDiscussion(
            id="x",
            created="2025-01-01T00:00:00",
            updated="2025-01-01T00:00:00",
            title="T",
            material="M",
            initial_question="Q",
            agents=[agent],
        ).to_dict()
        assert d["agents"][0]["temperature"] is None
        # JSON round-trip must keep the null, not invent a number
        assert json.loads(json.dumps(d))["agents"][0]["temperature"] is None

    def test_json_roundtrip(self):
        original = _sample_discussion()
        json_str = json.dumps(original.to_dict(), ensure_ascii=False)
        data = json.loads(json_str)
        restored = StoredDiscussion.from_dict(data)
        assert restored.id == original.id
        assert restored.rounds[0].messages[0].content == "Was fällt auf?"

    def test_from_dict_rejects_missing_message_id(self):
        data = _sample_discussion().to_dict()
        del data["rounds"][0]["messages"][0]["id"]
        with pytest.raises(ValueError, match="id"):
            StoredDiscussion.from_dict(data)

    def test_from_dict_rejects_missing_note(self):
        data = _sample_discussion().to_dict()
        del data["rounds"][0]["messages"][1]["note"]
        with pytest.raises(ValueError, match="note"):
            StoredDiscussion.from_dict(data)


class TestStoredMessageContextInclusion:
    def test_stored_message_default_is_included(self):
        m = StoredMessage(id="m1", role="user", content="Hallo")
        assert m.include_in_agent_context is True

    def test_to_dict_emits_include_in_agent_context(self):
        d = _sample_discussion().to_dict()
        for msg in d["rounds"][0]["messages"]:
            assert "include_in_agent_context" in msg
            assert msg["include_in_agent_context"] is True

    def test_to_dict_emits_false_when_excluded(self):
        d = _sample_discussion().to_dict()
        d["rounds"][0]["messages"][1]["include_in_agent_context"] = False
        assert d["rounds"][0]["messages"][1]["include_in_agent_context"] is False

    def test_roundtrip_preserves_excluded_message(self):
        data = _sample_discussion().to_dict()
        data["rounds"][0]["messages"][1]["include_in_agent_context"] = False
        restored = StoredDiscussion.from_dict(data)
        assert restored.rounds[0].messages[0].include_in_agent_context is True
        assert restored.rounds[0].messages[1].include_in_agent_context is False

    def test_from_dict_rejects_missing_context_inclusion(self):
        data = _sample_discussion().to_dict()
        for msg in data["rounds"][0]["messages"]:
            del msg["include_in_agent_context"]
        with pytest.raises(ValueError, match="include_in_agent_context"):
            StoredDiscussion.from_dict(data)

    def test_json_roundtrip_via_dump_and_load(self):
        original = _sample_discussion()
        original.rounds[0].messages[1].include_in_agent_context = False
        encoded = json.dumps(original.to_dict(), ensure_ascii=False)
        decoded = json.loads(encoded)
        restored = StoredDiscussion.from_dict(decoded)
        assert restored.rounds[0].messages[0].include_in_agent_context is True
        assert restored.rounds[0].messages[1].include_in_agent_context is False


class TestStoredAgentEnabled:
    def test_stored_agent_default_enabled_is_true(self):
        a = StoredAgent(name="A", prompt_id="sys_theory", prompt_label="L")
        assert a.enabled is True

    def test_to_dict_emits_enabled_field(self):
        d = _sample_discussion().to_dict()
        assert "enabled" in d["agents"][0]
        assert d["agents"][0]["enabled"] is True

    def test_to_dict_emits_disabled_when_enabled_false(self):
        a = StoredAgent(
            name="Off",
            prompt_id="sys_theory",
            prompt_label="L",
            enabled=False,
        )
        d = StoredDiscussion(
            id="x",
            created="2025-01-01T00:00:00",
            updated="2025-01-01T00:00:00",
            title="T",
            material="M",
            initial_question="Q",
            agents=[a],
        ).to_dict()
        assert d["agents"][0]["enabled"] is False

    def test_roundtrip_preserves_disabled_agent(self):
        original = _sample_discussion()
        original.agents.append(
            StoredAgent(
                name="Disabled",
                client_id="client-disabled",
                prompt_id="sys_theory",
                prompt_label="Systemtheorie",
                color="#000000",
                enabled=False,
                perspective_number=2,
            )
        )
        data = original.to_dict()
        assert data["agents"][-1]["enabled"] is False

        restored = StoredDiscussion.from_dict(data)
        assert len(restored.agents) == len(original.agents)
        disabled = [a for a in restored.agents if a.name == "Disabled"][0]
        assert disabled.enabled is False
        assert disabled.prompt_id == "sys_theory"
        assert disabled.client_id == "client-disabled"

    def test_from_dict_rejects_missing_enabled_field(self):
        data = _sample_discussion().to_dict()
        del data["agents"][0]["enabled"]
        with pytest.raises(ValueError, match="enabled"):
            StoredDiscussion.from_dict(data)

    def test_from_dict_rejects_incomplete_agent(self):
        data = _sample_discussion().to_dict()
        del data["agents"][0]["enabled"]
        with pytest.raises(ValueError, match="enabled"):
            StoredDiscussion.from_dict(data)

    def test_explicit_false_enabled_is_preserved(self):
        data = _sample_discussion().to_dict()
        data["agents"][0]["enabled"] = False
        restored = StoredDiscussion.from_dict(data)
        assert restored.agents[0].enabled is False

    def test_json_roundtrip_via_dump_and_load(self):
        original = _sample_discussion()
        original.agents[0].enabled = False
        encoded = json.dumps(original.to_dict(), ensure_ascii=False)
        decoded = json.loads(encoded)
        restored = StoredDiscussion.from_dict(decoded)
        assert restored.agents[0].enabled is False
        assert restored.agents[0].prompt_id == "sys_theory"


class TestStoredDiscussionMarkdown:
    def test_markdown_contains_title(self):
        md = _sample_discussion().to_markdown()
        assert "# Interview Müller" in md

    @pytest.mark.parametrize("locale", ["en", "de"])
    def test_saved_assembly_policy_is_retained_in_snapshot_but_not_exported(self, locale):
        discussion = _sample_discussion()
        policy = "Historical assembly policy sentinel"
        discussion.prompt_snapshot = StoredPromptSnapshot(layout=policy)

        md = discussion.to_markdown(locale=locale)

        assert discussion.prompt_snapshot.layout == policy
        assert discussion.to_dict()["prompt_snapshot"]["layout"] == policy
        assert "Saved Assembly Policy" not in md
        assert "Gespeicherte Assemblierungsregeln" not in md
        assert policy not in md
        assert (
            "### Saved Prompt Definitions"
            if locale == "en"
            else "### Gespeicherte Prompt-Definitionen"
        ) in md

    def test_saved_instruction_fence_exceeds_embedded_backtick_runs(self):
        discussion = _sample_discussion()
        embedded = "Before\n```python\nvalue = `code`\n```\nAfter"
        discussion.prompt_snapshot = StoredPromptSnapshot(
            layout="Historical assembly policy sentinel",
            globals=[{"id": "shared", "label": "Shared rule", "content": embedded}],
            used_global_ids=["shared"],
        )

        md = discussion.to_markdown(locale="en")

        assert f"##### Shared rule\n\n````text\n{embedded}\n````\n" in md
        assert "Historical assembly policy sentinel" not in md

    def test_saved_prompt_subsections_follow_heading_hierarchy(self):
        discussion = _sample_discussion()
        discussion.prompt_snapshot = StoredPromptSnapshot(
            layout="Historical assembly policy",
            globals=[{"id": "shared", "label": "Research stance", "content": "Frozen rule"}],
            used_global_ids=["shared"],
            roles=[{"id": "sys_theory", "label": "Theory", "role": "Frozen role"}],
            used_role_ids=["sys_theory"],
            synthesis={"label": "Synthesis", "content": "Frozen synthesis"},
            synthesis_used=True,
        )

        md = discussion.to_markdown(locale="en")

        assert md.index("### Saved Prompt Definitions") < md.index("#### Shared Instructions")
        assert md.index("#### Shared Instructions") < md.index("##### Research stance")
        assert md.index("#### Perspective Prompts") < md.index("##### Theory")
        assert md.index("#### Synthesis Guidance") < md.index("##### Synthesis")

    def test_current_reconstruction_retains_multiple_perspectives_then_synthesis(self):
        discussion = _sample_discussion()
        discussion.prompt_snapshot = StoredPromptSnapshot(layout="Older saved policy")
        prompts = [
            ("Perspective 1", "System for first", "User for first"),
            ("Perspective 2", "System for second", "User for second"),
            ("Round Synthesis", "Synthesis system", "Synthesis user"),
        ]

        md = discussion.to_markdown(locale="en", prompt_documentation=prompts)

        assert (
            md.index("#### Perspective 1")
            < md.index("#### Perspective 2")
            < md.index("#### Round Synthesis")
        )
        for _label, system, user in prompts:
            assert f"```text\n{system}\n```" in md
            assert f"```text\n{user}\n```" in md
        assert md.index("#### Perspective Prompting") < md.index("#### Synthesis Prompting")
        assert md.index("### Current Prompt Organization") < md.index(
            "### Current-State Prompt Reconstruction"
        )

    def test_markdown_contains_agents(self):
        md = _sample_discussion().to_markdown()
        assert "Perspective 1" in md
        assert "Systemtheorie" in md

    def test_markdown_contains_material(self):
        md = _sample_discussion().to_markdown()
        assert "beispielhafter Interview-Text" in md

    def test_markdown_contains_round_header(self):
        md = _sample_discussion().to_markdown()
        assert "### Runde 1" in md

    def test_markdown_round_configuration_is_compact_localized_and_url_free(self):
        discussion = _sample_discussion()
        discussion.prompt_snapshot = StoredPromptSnapshot(
            layout="Layout",
            roles=[
                {
                    "id": "sys_theory",
                    "label": "Systemtheorie",
                    "role": "Frozen role body",
                    "task": "Frozen task body",
                    "output_format": "Frozen format body",
                }
            ],
        )
        discussion.rounds[0].provider_provenance = [
            StoredProviderProvenance(
                kind="perspective",
                client_id="storage-agent-1",
                prompt_id="sys_theory",
                prompt_label="Systemtheorie",
                perspective_number=1,
                temperature=0.7,
                host_configuration_id="host-a",
                host_label="Visible Host",
                api_host="https://private-network.example/v1",
                model_id="model-a",
            )
        ]

        md = discussion.to_markdown(locale="en")

        assert "#### Configuration for this round" in md
        assert "**Perspective 1:** Role: Systemtheorie (`sys_theory`)" in md
        assert "Temp. 0.7 · Host: Visible Host · Model: model-a" in md
        assert "private-network.example" not in md
        assert "Frozen role body" in md
        assert "Frozen task body" in md
        assert "Frozen format body" in md

    def test_markdown_labels_interrupted_round_without_complete_language(self):
        discussion = _sample_discussion()
        discussion.rounds[0].status = "interrupted"
        discussion.rounds[0].messages[1].status = "interrupted"

        md = discussion.to_markdown()

        assert "**Status:** Unterbrochen" in md
        assert "Runde 1 abgeschlossen" not in md

    def test_markdown_contains_agent_response(self):
        md = _sample_discussion().to_markdown()
        assert "systemtheoretischer Sicht" in md

    def test_markdown_contains_message_note(self):
        md = _sample_discussion().to_markdown()
        assert "Notiz zur Nachricht" in md
        assert "Theorievergleich" in md

    def test_markdown_contains_analysis_context_blocks(self):
        md = _sample_discussion().to_markdown()
        assert "## Analysekontext" in md
        assert "### Research Material Context" in md
        assert "### Interpretation" in md
        assert "### Additional Instructions" in md

    @pytest.mark.parametrize("locale", ["de", "en"])
    def test_markdown_uses_effective_research_context(self, locale):
        discussion = _sample_discussion()
        scaffold = "Research Topic and Question\n\n..."
        discussion.session_inputs[0] = {**discussion.session_inputs[0], "default_text": scaffold}
        discussion.session_input_values["research_material_context"] = scaffold.replace(
            "\n", "\r\n"
        )
        discussion.include_unchanged_research_material_context_in_prompt = False

        assert "### Research Material Context" not in discussion.to_markdown(locale)
        assert discussion.session_input_values["research_material_context"].startswith(
            "Research Topic"
        )

        discussion.include_unchanged_research_material_context_in_prompt = True
        assert "### Research Material Context" in discussion.to_markdown(locale)

        discussion.include_unchanged_research_material_context_in_prompt = False
        discussion.session_input_values["research_material_context"] = (
            scaffold + "\nEdited case detail"
        )
        assert "Edited case detail" in discussion.to_markdown(locale)

    def test_markdown_defaults_to_complete_german_shell(self):
        md = _sample_discussion().to_markdown()

        assert "**Erstellt:** 2025-06-15 10:00" in md
        assert "**Runden:** 1" in md
        assert "**Session-Typ:** critique" in md
        assert "**Material-Typ:** interview" in md
        assert "## Beteiligte Perspektiven" in md
        assert "(Temp: 0.7)" in md
        assert "## Startauftrag (erste Runde)" in md
        assert "## Diskussionsverlauf" in md
        assert "### Runde 1" in md
        assert "#### 👤 Moderator" in md
        assert "**Notiz zur Nachricht:**" in md
        assert "*Exportiert aus AQA | ID: aaaaaaaa*" in md

    def test_markdown_english_localizes_shell_and_preserves_content(self):
        discussion = _sample_discussion()
        discussion.rounds[0].messages[1].include_in_agent_context = False

        md = discussion.to_markdown(locale="en")

        assert "**Created:** 06/15/2025 10:00" in md
        assert "**Rounds:** 1" in md
        assert "**Session type:** critique" in md
        assert "**Material type:** interview" in md
        assert "## Analysis context" in md
        assert "### Research Material Context" in md
        assert "### Interpretation" in md
        assert "### Additional Instructions" in md
        assert "## Participating perspectives" in md
        assert "(Temp. 0.7)" in md
        assert "## Initial instruction (first round)" in md
        assert "## Discussion transcript" in md
        assert "### Round 1" in md
        assert "#### 👤 Moderator" in md
        assert ("> **Context status:** not included in subsequent agent rounds.") in md
        assert "**Message note:**" in md
        assert "*Exported from AQA | ID: aaaaaaaa*" in md

        # The export shell is localized, but research content and stored
        # metadata values are reproduced exactly as supplied.
        assert "Interview Müller" in md
        assert "Leitfadeninterview mit Berufseinsteigerin" in md
        assert "Ich lese eine Spannung zwischen Sicherheitsbedürfnis" in md
        assert "Bitte zuerst Gegenargumente" in md
        assert "Ein beispielhafter Interview-Text." in md
        assert "Was fällt auf?" in md
        assert "Systemtheorie" in md
        assert "Aus systemtheoretischer Sicht..." in md
        assert "Später für Theorievergleich aufgreifen." in md

    def test_markdown_english_localizes_missing_values(self):
        discussion = StoredDiscussion(
            id="x",
            created="2025-01-02T03:04:00+02:00",
            updated="2025-01-02T03:04:00+02:00",
            title="Untitled",
            material="",
            initial_question="",
        )

        md = discussion.to_markdown(locale="en")

        assert "**Created:** 01/02/2025 03:04" in md
        assert "*No material provided*" in md
        assert md.count("*Not provided*") == 1

    def test_markdown_empty_material(self):
        d = _sample_discussion()
        d.material = ""
        md = d.to_markdown()
        assert "Kein Material angegeben" in md

    def test_markdown_keeps_and_marks_excluded_message(self):
        discussion = _sample_discussion()
        discussion.rounds[0].messages[1].include_in_agent_context = False
        md = discussion.to_markdown()
        assert "Aus systemtheoretischer Sicht" in md
        assert ("> **Kontextstatus:** nicht in nachfolgende Agentenrunden eingespeist.") in md

    def test_markdown_annotates_each_excluded_message(self):
        discussion = StoredDiscussion(
            id="x",
            created="2026-07-14T10:00:00",
            updated="2026-07-14T10:00:00",
            title="Mehrfach ausgeschlossen",
            material="M",
            initial_question="Q",
            rounds=[
                StoredRound(
                    round_number=1,
                    messages=[
                        StoredMessage(id="u1", role="user", content="User 1"),
                        StoredMessage(
                            id="a1",
                            role="agent",
                            content="Agent 1",
                            agent_name="A",
                            theory_label="T",
                            include_in_agent_context=False,
                        ),
                        StoredMessage(id="u2", role="user", content="User 2"),
                        StoredMessage(
                            id="a2",
                            role="agent",
                            content="Agent 2",
                            agent_name="A",
                            theory_label="T",
                            include_in_agent_context=False,
                        ),
                    ],
                ),
            ],
        )
        md = discussion.to_markdown()
        annotation = "> **Kontextstatus:** nicht in nachfolgende Agentenrunden eingespeist."
        assert md.count(annotation) == 2
        assert md.index("Agent 1") < md.index(annotation)
        assert md.index("Agent 2") < md.index(annotation, md.index("Agent 2"))

    def test_markdown_does_not_annotate_included_messages(self):
        md = _sample_discussion().to_markdown()
        assert "Kontextstatus" not in md

    def test_markdown_annotation_appears_before_notes(self):
        discussion = _sample_discussion()
        discussion.rounds[0].messages[1].include_in_agent_context = False
        discussion.rounds[0].messages[1].note = "Eine Notiz"
        md = discussion.to_markdown()
        content_idx = md.index("Aus systemtheoretischer Sicht")
        annotation_idx = md.index("Kontextstatus")
        note_idx = md.index("Eine Notiz")
        assert content_idx < annotation_idx < note_idx


class TestDiscussionStorage:
    def test_create_new(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = storage.create_new("Test-Diskussion")
        assert d.title == "Test-Diskussion"
        assert d.id  # UUID gesetzt
        assert d.created

    def test_create_new_default_title(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = storage.create_new()
        assert d.title == "Unbenannte Diskussion"

    def test_save_and_load(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        original = _sample_discussion()
        filepath = storage.save(original)
        assert filepath.exists()

        loaded = storage.load(filepath.stem)
        assert loaded is not None
        assert loaded.id == original.id
        assert loaded.title == original.title
        assert len(loaded.rounds) == 1
        assert loaded.rounds[0].messages[1].note == "Später für Theorievergleich aufgreifen."

    def test_save_creates_json(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        fp = storage.save(d)
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert data["title"] == "Interview Müller"

    def test_sessions_referencing_host_include_current_and_historical_safe_identity(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        discussion = _sample_discussion()
        discussion.agents[0].api_host = "https://current.example/v1/"
        discussion.agents[0].host_configuration_id = "Current"
        discussion.agents[0].host_label = "Current"
        discussion.rounds[0].provider_provenance = [
            StoredProviderProvenance(
                kind="perspective",
                client_id="storage-agent-1",
                prompt_id="sys_theory",
                prompt_label="Systemtheorie",
                perspective_number=1,
                temperature=0.7,
                host_configuration_id="Historical",
                host_label="Historical",
                api_host="https://historical.example/v1",
                model_id="old-model",
            )
        ]
        filepath = storage.save(discussion)
        alias = _sample_discussion()
        alias.id = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
        alias.title = "Same URL, Different Host"
        alias.agents[0].api_host = "https://current.example/v1/"
        alias.agents[0].host_configuration_id = "Alias"
        alias.agents[0].host_label = "Alias"
        storage.save(alias)

        assert storage.sessions_referencing_host("Current", "https://current.example/v1") == [
            {"file_id": filepath.stem, "title": discussion.title}
        ]
        assert storage.sessions_referencing_host(
            "Historical", "https://historical.example/v1/"
        ) == [{"file_id": filepath.stem, "title": discussion.title}]
        assert storage.sessions_referencing_host("Unrelated", "https://unrelated.example/v1") == []

    def test_load_by_exact_file_id(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        storage.save(d)
        exact_stem = storage._generate_filename(d).removesuffix(".json")
        loaded = storage.load(exact_stem)
        assert loaded is not None
        assert loaded.id == d.id

    def test_load_nonexistent(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        assert storage.load("nope") is None

    def test_list_all(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d1 = _sample_discussion()
        d2 = _sample_discussion()
        d2.id = "11111111-2222-3333-4444-555555555555"
        d2.created = "2025-07-01T12:00:00"
        d2.title = "Zweite Diskussion"
        storage.save(d1)
        storage.save(d2)

        listing = storage.list_all()
        assert len(listing) == 2
        titles = {item["title"] for item in listing}
        assert "Interview Müller" in titles
        assert "Zweite Diskussion" in titles

    def test_list_all_empty(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        assert storage.list_all() == []

    def test_storage_dir_created(self, tmp_path):
        target = tmp_path / "sub" / "deep"
        DiscussionStorage(target)
        assert target.exists()


class TestSessionPersistenceContract:
    def test_stored_discussion_keeps_sequential_mode(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        d.sequential_mode = True

        data = d.to_dict()
        assert data["sequential_mode"] is True

        fp = storage.save(d)
        restored = storage.load(fp.stem)
        assert restored is not None
        assert restored.sequential_mode is True

    def test_stored_agent_keeps_full_safe_config_roundtrip(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        d.agents = [
            StoredAgent(
                name="A",
                client_id="client-abc",
                prompt_id="sys_theory",
                prompt_label="Systemtheorie",
                color="#123456",
                temperature=0.42,
                llm_id="qwen2.5",
                api_host="http://127.0.0.1:1234",
                max_tokens=1024,
                perspective_number=1,
            )
        ]

        data = d.to_dict()
        agent_data = data["agents"][0]
        assert agent_data["name"] == "A"
        assert agent_data["client_id"] == "client-abc"
        assert agent_data["prompt_id"] == "sys_theory"
        assert agent_data["prompt_label"] == "Systemtheorie"
        assert agent_data["color"] == "#123456"
        assert agent_data["temperature"] == 0.42
        assert agent_data["llm_id"] == "qwen2.5"
        assert agent_data["api_host"] == "http://127.0.0.1:1234"
        assert agent_data["max_tokens"] == 1024
        # Credentials must never cross the persistence boundary.
        assert "api_key" not in agent_data

        fp = storage.save(d)
        restored = storage.load(fp.stem)
        assert restored is not None
        ra = restored.agents[0]
        assert ra.name == "A"
        assert ra.client_id == "client-abc"
        assert ra.prompt_id == "sys_theory"
        assert ra.prompt_label == "Systemtheorie"
        assert ra.color == "#123456"
        assert ra.temperature == 0.42
        assert ra.llm_id == "qwen2.5"
        assert ra.api_host == "http://127.0.0.1:1234"
        assert ra.max_tokens == 1024
        assert not hasattr(ra, "api_key") or getattr(ra, "api_key", None) in (None, "")

    def test_list_all_returns_canonical_metadata_no_filepath(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        d.created = "2025-06-15T10:00:00"
        storage.save(d)

        listing = storage.list_all()
        assert len(listing) == 1
        item = listing[0]
        for key in ("file_id", "title", "created", "updated", "session_type", "round_count"):
            assert key in item, f"missing canonical key: {key}"
        assert item["session_type"] == d.session_type
        assert item["file_id"] == item["file_id"].strip()
        assert "/" not in item["file_id"]
        assert "\\" not in item["file_id"]
        assert ".json" not in item["file_id"]
        assert "content" not in item
        assert item["created"] == "2025-06-15T10:00:00"
        # updated is non-empty (save() always rewrites it to now())
        assert item["updated"]
        # The storage boundary publishes no path aliases.
        assert "filename" not in item
        assert "filepath" not in item
        assert "id" not in item

    def test_list_all_updated_falls_back_to_created(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        d.created = "2025-01-01T00:00:00"
        # Bypass save() to drop 'updated' from the JSON
        fp = storage._generate_filename(d)
        d.updated = d.created
        d.agents = []
        d.rounds = []
        (tmp_path / "disc").mkdir(parents=True, exist_ok=True)
        (tmp_path / "disc" / fp).write_text(
            json.dumps(d.to_dict() | {"updated": ""}),
            encoding="utf-8",
        )
        listing = storage.list_all()
        assert len(listing) == 1
        assert listing[0]["updated"] == "2025-01-01T00:00:00"

    def test_resolve_file_id_rejects_path_traversal(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        # Direct traversal patterns
        for bad in (
            "../etc/passwd",
            "..",
            ".",
            "/absolute/path",
            "..\\windows",
            "sub/dir",
            "sub\\dir",
            "a/b",
        ):
            with pytest.raises(ValueError):
                storage.resolve_file_id(bad)

    def test_resolve_file_id_returns_exact_stem(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        fp = storage.save(d)
        resolved = storage.resolve_file_id(fp.stem)
        assert resolved == fp
        # And explicit absolute paths are not used as ids
        with pytest.raises(ValueError):
            storage.resolve_file_id(str(fp))

    def test_rename_changes_metadata_only_not_filename(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        d.title = "Alt"
        fp = storage.save(d)
        original_file_id = fp.stem

        ok = storage.rename(original_file_id, "Neu")
        assert ok is True

        # Filename is unchanged (rename is metadata-only)
        assert fp.exists()
        # A new file with the new title in its name does NOT appear
        assert not (tmp_path / "disc" / "Neu.json").exists()

        # Metadata reflects the new title
        listing = storage.list_all()
        assert len(listing) == 1
        assert listing[0]["title"] == "Neu"
        assert listing[0]["file_id"] == original_file_id

        # Loading by the unchanged file_id returns the new title
        reloaded = storage.load(original_file_id)
        assert reloaded is not None
        assert reloaded.title == "Neu"

    def test_rename_rejects_unsafe_id(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        fp = storage.save(d)
        with pytest.raises(ValueError):
            storage.rename("../escape", "X")
        # Original file is still untouched
        assert fp.exists()

    def test_rename_unknown_file_returns_false(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        assert storage.rename("does-not-exist", "X") is False

    def test_session_path_for_reveal_returns_exact_path(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        fp = storage.save(d)
        revealed = storage.session_path_for_reveal(fp.stem)
        assert revealed == fp
        with pytest.raises(ValueError):
            storage.session_path_for_reveal("../escape")
        # Unknown but safe ids yield None
        assert storage.session_path_for_reveal("definitely-not-here") is None

    def test_save_is_atomic_no_leftover_temp_on_success(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        fp = storage.save(d)
        assert fp.exists()
        # No temp file should remain
        tmp_files = list((tmp_path / "disc").glob("*.json.tmp"))
        assert tmp_files == []

    def test_save_atomic_preserves_existing_file_on_failure(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        fp = storage.save(d)
        # Capture the existing on-disk content
        original_bytes = fp.read_bytes()

        # Now monkey-patch json.dump to fail.  Save should propagate
        # the error, but the original file must remain untouched,
        # and no ``.json.tmp`` file may be left behind.
        with patch(
            "src.service.discussion_storage.json.dump",
            side_effect=RuntimeError("simulated crash mid-serialise"),
        ):
            with pytest.raises(RuntimeError):
                storage.save(d)

        # The existing file is still there and unchanged.
        assert fp.exists()
        assert fp.read_bytes() == original_bytes
        # And no temp file is left behind
        tmp_files = list((tmp_path / "disc").glob("*.json.tmp"))
        assert tmp_files == []

    def test_rename_failure_cleans_temp_file_via_atomic_helper(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        d.title = "Vorher"
        fp = storage.save(d)
        original_bytes = fp.read_bytes()
        file_id = fp.stem

        # Force the shared atomic-write helper to fail.  The
        # canonical file must survive unchanged, the rename must
        # return False (or raise), and no ``.json.tmp`` may remain.
        with patch(
            "src.service.discussion_storage.json.dump",
            side_effect=RuntimeError("simulated crash during rename"),
        ):
            with pytest.raises(RuntimeError):
                storage.rename(file_id, "Nachher")

        # The canonical file is untouched and retains its title.
        assert fp.exists()
        assert fp.read_bytes() == original_bytes
        loaded = storage.load(file_id)
        assert loaded is not None
        assert loaded.title == "Vorher"
        # No leftover temp file
        tmp_files = list((tmp_path / "disc").glob("*.json.tmp"))
        assert tmp_files == []

    def test_storage_init_cleans_stale_tmp_files(self, tmp_path):
        target = tmp_path / "disc"
        target.mkdir(parents=True, exist_ok=True)
        # Seed temporary files from interrupted writes.
        (target / "2025-01-01_00-00_abcdef01.json.tmp").write_text("{partial", encoding="utf-8")
        (target / "another.json.tmp").write_text("", encoding="utf-8")

        # Constructing the storage should remove the temporary files.
        DiscussionStorage(target)

        assert list(target.glob("*.json.tmp")) == []


# Default-title generation for new sessions
class TestDefaultDiscussionTitle:
    def test_generate_title_with_material_excerpt(self):
        from src.service.discussion import generate_default_discussion_title

        ts = datetime(2026, 7, 13, 14, 32)
        title = generate_default_discussion_title(
            ts, "Erste Zeile\n\n   Dritte Zeile  mit   Lücken."
        )
        assert title.startswith("2026-07-13 14:32 ")
        assert "Erste Zeile" in title
        # Whitespace is collapsed inside the excerpt
        assert "   " not in title.split("2026-07-13 14:32 ", 1)[1]
        # Newlines are normalised away inside the excerpt
        assert "\n" not in title

    def test_generate_title_empty_material_returns_diskussion(self):
        from src.service.discussion import generate_default_discussion_title

        ts = datetime(2026, 7, 13, 14, 32)
        assert generate_default_discussion_title(ts, "") == "2026-07-13 14:32 Discussion"
        assert generate_default_discussion_title(ts, "   \n  \t  ") == "2026-07-13 14:32 Discussion"

    def test_generate_title_excerpt_is_bounded(self):
        from src.service.discussion import (
            DEFAULT_TITLE_EXCERPT_MAX_CHARS,
            generate_default_discussion_title,
        )

        ts = datetime(2026, 7, 13, 14, 32)
        huge = "A" * 5000
        title = generate_default_discussion_title(ts, huge)
        excerpt = title.split("2026-07-13 14:32 ", 1)[1]
        # The excerpt cap should be respected (allowing a tiny safety
        # margin for trailing ellipsis / whitespace).
        assert len(excerpt) <= DEFAULT_TITLE_EXCERPT_MAX_CHARS + 5
        assert len(excerpt) <= 200  # sanity: never absurdly long

    def test_generate_title_strips_edge_whitespace(self):
        from src.service.discussion import generate_default_discussion_title

        ts = datetime(2026, 7, 13, 14, 32)
        title = generate_default_discussion_title(ts, "  \n  Hallo Welt  \n  ")
        assert title == "2026-07-13 14:32 Hallo Welt"


# Session persistence — persistent favorite flag
#
# A session stores ``is_favorite`` through an atomic exact-file-ID mutation.
class TestSessionFavoritePersistenceContract:
    def test_new_stored_discussion_defaults_is_favorite_false(self):
        d = _sample_discussion()
        assert d.is_favorite is False

    def test_to_dict_includes_is_favorite(self):
        d = _sample_discussion()
        d.is_favorite = True
        data = d.to_dict()
        assert data["is_favorite"] is True

    def test_from_dict_explicit_is_favorite_roundtrip(self):
        original = _sample_discussion()
        original.is_favorite = True
        data = original.to_dict()
        restored = StoredDiscussion.from_dict(data)
        assert restored.is_favorite is True

    def test_list_all_exposes_canonical_is_favorite(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        d.is_favorite = True
        storage.save(d)
        listing = storage.list_all()
        assert len(listing) == 1
        assert listing[0]["is_favorite"] is True
        for removed_key in ("filename", "filepath", "id"):
            assert removed_key not in listing[0]

    def test_set_favorite_atomic_changes_only_boolean_not_updated(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        d.title = "Original"
        fp = storage.save(d)
        original_file_id = fp.stem

        # Snapshot every persisted value before mutating so we can
        # diff it value-for-value afterwards.  ``updated`` in
        # particular must remain *value*-equal.
        original_data = json.loads(fp.read_text(encoding="utf-8"))

        # Brief delay so an implementation that rewrites
        # ``updated`` would produce a different timestamp.
        import time

        time.sleep(0.01)
        ok = storage.set_favorite(original_file_id, True)
        assert ok is True

        # Filename and atomic-write invariant: original path still
        # exists, no leftover sibling temp file.
        assert fp.exists()
        assert not (tmp_path / "disc" / f"{original_file_id}.json.tmp").exists()

        # Re-read raw JSON to confirm exactly one key changed.
        new_data = json.loads(fp.read_text(encoding="utf-8"))

        # The favorite boolean flipped.
        assert new_data["is_favorite"] is True

        # The ``updated`` timestamp is a recency field owned by
        # substantive edits (save, rename, …) and MUST NOT move on a
        # favorite toggle. This is the single-field mutation contract.
        assert new_data["updated"] == original_data["updated"]

        # No other persisted field may change either.  We compare
        # the full key sets and the value of every other key to make
        # the contract explicit: this is a single-key mutation.
        new_data_without_fav = {k: v for k, v in new_data.items() if k != "is_favorite"}
        original_data_without_fav = {k: v for k, v in original_data.items() if k != "is_favorite"}
        assert new_data_without_fav == original_data_without_fav
        # Title and a couple of representative fields stay equal
        # to make the intent obvious in failure output.
        assert new_data["title"] == "Original"
        assert new_data["created"] == original_data["created"]
        assert new_data["id"] == original_data["id"]

        # The list metadata exposes the new boolean and the
        # unchanged timestamp.
        listing = storage.list_all()
        assert listing[0]["is_favorite"] is True
        assert listing[0]["updated"] == original_data["updated"]

    def test_set_favorite_can_toggle_back_to_false(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        fp = storage.save(d)
        file_id = fp.stem
        assert storage.set_favorite(file_id, True) is True
        assert storage.set_favorite(file_id, False) is True
        assert json.loads(fp.read_text(encoding="utf-8"))["is_favorite"] is False

    def test_set_favorite_unknown_file_returns_false(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        assert storage.set_favorite("does-not-exist", True) is False

    def test_set_favorite_unsafe_id_raises_value_error(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        fp = storage.save(d)
        with pytest.raises(ValueError):
            storage.set_favorite("../escape", True)
        with pytest.raises(ValueError):
            storage.set_favorite("a/b", True)
        # Original file untouched
        assert json.loads(fp.read_text(encoding="utf-8"))["is_favorite"] is False

    def test_set_favorite_does_not_use_prefix_match(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        d = _sample_discussion()
        d.id = "00000000-aaaa-bbbb-cccc-dddddddddddd"
        d.created = "2025-01-15T10:00:00"
        storage.save(d)
        # Stem is ``2025-01-15_10-00_00000000``; ``_10-00_00000000``
        # is a substring (not a prefix) and must NOT be a valid id.
        assert storage.set_favorite("_10-00_00000000", True) is False
        # The original file remains untouched
        on_disk = json.loads(
            (tmp_path / "disc" / "2025-01-15_10-00_00000000.json").read_text(encoding="utf-8")
        )
        assert on_disk["is_favorite"] is False


# Terminal agent message metadata
#
# Terminal agent-message metadata must round-trip through stored sessions.
class TestStoredMessageTerminalMetadata:
    def test_stored_message_defaults_to_none_for_optional_fields(self):
        # Bare construction: the four new fields are optional, default None.
        msg = StoredMessage(id="m", role="agent", content="x")
        assert msg.client_id is None
        assert msg.color is None
        assert msg.agent_index is None
        assert msg.error is None

    def test_to_dict_writes_all_four_fields_when_set(self):
        msg = StoredMessage(
            id="m1",
            role="agent",
            content="Erste Antwort.",
            agent_name="Agent 1",
            client_id="client-abc",
            color="#ff00aa",
            agent_index=2,
            error="Anbieter-Fehler",
            perspective_number=1,
        )
        data = StoredDiscussion(
            id="d1",
            created="2025-06-15T10:00:00",
            updated="2025-06-15T10:00:00",
            title="t",
            material="",
            initial_question="",
            rounds=[StoredRound(round_number=1, messages=[msg])],
        ).to_dict()
        m = data["rounds"][0]["messages"][0]
        assert m["client_id"] == "client-abc"
        assert m["color"] == "#ff00aa"
        assert m["agent_index"] == 2
        assert m["error"] == "Anbieter-Fehler"

    def test_to_dict_omits_optional_fields_when_none(self):
        # ``None`` means "absent" for non-required metadata; the on-disk
        # representation must still be safe to read back.  We deliberately
        # *do* write the keys with ``None`` so the on-disk shape is
        # Stable for fresh writes; malformed payloads are covered separately.
        msg = StoredMessage(id="m1", role="agent", content="x")
        data = StoredDiscussion(
            id="d1",
            created="2025-06-15T10:00:00",
            updated="2025-06-15T10:00:00",
            title="t",
            material="",
            initial_question="",
            rounds=[StoredRound(round_number=1, messages=[msg])],
        ).to_dict()
        m = data["rounds"][0]["messages"][0]
        # The fields exist (keys are part of the contract) but hold None
        # for a freshly written default.
        assert m.get("client_id") is None
        assert m.get("color") is None
        assert m.get("agent_index") is None
        assert m.get("error") is None

    def test_from_dict_roundtrips_all_four_fields(self):
        msg = StoredMessage(
            id="m1",
            role="agent",
            content="x",
            agent_name="Agent 1",
            client_id="client-abc",
            color="#ff00aa",
            agent_index=2,
            error="Anbieter-Fehler",
            perspective_number=1,
        )
        d = _sample_discussion()
        d.rounds = [StoredRound(round_number=1, messages=[msg])]
        restored = StoredDiscussion.from_dict(d.to_dict())
        m = restored.rounds[0].messages[0]
        assert m.client_id == "client-abc"
        assert m.color == "#ff00aa"
        assert m.agent_index == 2
        assert m.error == "Anbieter-Fehler"

    def test_structured_error_metadata_roundtrips(self):
        message = StoredMessage(
            id="m1",
            role="agent",
            content="[Fehler: Anbieter-Fehler]",
            agent_name="Agent 1",
            client_id="client-abc",
            color="#333333",
            agent_index=0,
            error="Anbieter-Fehler",
            error_code="agent_generation_failed",
            error_params={"provider": "local_ai"},
            perspective_number=1,
        )
        discussion = _sample_discussion()
        discussion.rounds = [StoredRound(round_number=1, messages=[message])]

        restored = StoredDiscussion.from_dict(discussion.to_dict())
        restored_message = restored.rounds[0].messages[0]
        assert restored_message.error_code == "agent_generation_failed"
        assert restored_message.error_params == {"provider": "local_ai"}

        incomplete = discussion.to_dict()
        incomplete["rounds"][0]["messages"][0].pop("error_code")
        with pytest.raises(ValueError, match="error_code"):
            StoredDiscussion.from_dict(incomplete)

    def test_storage_roundtrip_preserves_terminal_metadata(self, tmp_path):
        storage = DiscussionStorage(tmp_path / "disc")
        msg = StoredMessage(
            id="m1",
            role="agent",
            content="x",
            agent_name="Agent 1",
            client_id="client-roundtrip",
            color="#112233",
            agent_index=1,
            error=None,
            perspective_number=1,
        )
        d = _sample_discussion()
        d.id = "d1"
        d.title = "Roundtrip"
        d.rounds = [StoredRound(round_number=1, messages=[msg])]
        fp = storage.save(d)
        # Read the raw JSON to confirm the keys are actually on disk
        on_disk = json.loads(fp.read_text(encoding="utf-8"))
        m_raw = on_disk["rounds"][0]["messages"][0]
        assert m_raw["client_id"] == "client-roundtrip"
        assert m_raw["color"] == "#112233"
        assert m_raw["agent_index"] == 1
        assert m_raw["error"] is None

        # And re-load through the public ``load`` entry point.
        restored = storage.load(fp.stem)
        assert restored is not None
        m_loaded = restored.rounds[0].messages[0]
        assert m_loaded.client_id == "client-roundtrip"
        assert m_loaded.color == "#112233"
        assert m_loaded.agent_index == 1
        assert m_loaded.error is None
