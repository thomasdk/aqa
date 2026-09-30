"""Tests for ``src.prompts.session_types``.

Focus on the repository's core security guarantees:

* deterministic ordering,
* robust validation (missing or invalid frontmatter),
* unique IDs (duplicate creation is rejected),
* path-traversal protection,
* immutable IDs during updates,
* atomic writes with round-trip coverage,
* ID-format validation for ``key`` and ``default_agent_prompt_ids``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.prompts.session_types import (
    SessionTypeDefinition,
    SessionTypeError,
    SessionTypeRepository,
)


def _write_md(
    path: Path,
    *,
    key: str,
    label: str = "L",
    body: str = "BODY",
    agent_ids: list[str] | None = None,
    extra_frontmatter: str = "",
) -> Path:
    agents = agent_ids if agent_ids is not None else ["rt_skeptiker"]
    agents_yaml = "\n".join(f"  - {a}" for a in agents)
    fm_extra = f"\n{extra_frontmatter}" if extra_frontmatter else ""
    text = (
        f"---\n"
        f"key: {key}\n"
        f"label: {label}\n"
        f"description: D\n"
        f"default_agent_prompt_ids:\n{agents_yaml}\n"
        f'default_interpretation: ""\n'
        f'interpretation_hint: ""{fm_extra}\n'
        f"---\n"
        f"{body}\n"
    )
    path.write_text(text, encoding="utf-8")
    return path


class TestSessionTypeDefinition:
    def test_minimal_definition_is_valid(self):
        definition = SessionTypeDefinition(
            key="exploration",
            label="Exploration",
            description="Breit explorativ.",
            body="BODY",
        )
        assert definition.key == "exploration"
        assert definition.default_agent_prompt_ids == []
        assert [item.key for item in definition.session_inputs] == [
            "research_material_context",
            "main_input",
            "additional_instructions",
        ]
        assert definition.include_unchanged_research_material_context_in_prompt is False

    def test_key_must_match_id_regex(self):
        with pytest.raises(ValidationError):
            SessionTypeDefinition(
                key="Offene_Exploration",
                label="L",
                description="D",
                body="B",
            )

    def test_key_must_start_with_letter(self):
        with pytest.raises(ValidationError):
            SessionTypeDefinition(
                key="2_session",
                label="L",
                description="D",
                body="B",
            )

    def test_invalid_agent_id_rejected(self):
        with pytest.raises(ValidationError):
            SessionTypeDefinition(
                key="offene_exploration",
                label="L",
                description="D",
                body="B",
                default_agent_prompt_ids=["Bad-ID"],
            )

    def test_empty_body_rejected(self):
        with pytest.raises(ValidationError):
            SessionTypeDefinition(
                key="offene_exploration",
                label="L",
                description="D",
                body="",
            )


class TestSessionTypeRepositoryList:
    def test_list_is_sorted_by_key(self, tmp_path: Path):
        _write_md(tmp_path / "z_late.md", key="z_late", label="Z")
        _write_md(tmp_path / "a_early.md", key="a_early", label="A")
        _write_md(tmp_path / "m_mid.md", key="m_mid", label="M")

        repo = SessionTypeRepository(base_path=tmp_path)
        keys = [definition.key for definition in repo.list()]

        assert keys == ["a_early", "m_mid", "z_late"]

    def test_list_returns_definitions_with_expected_fields(self, tmp_path: Path):
        _write_md(
            tmp_path / "offene_exploration.md",
            key="offene_exploration",
            label="Freie Exploration",
            body="Leitfaden-Text",
            agent_ids=["rt_skeptiker", "rt_praezise"],
        )
        repo = SessionTypeRepository(base_path=tmp_path)
        definition = repo.list()[0]

        assert definition.label == "Freie Exploration"
        assert definition.body == "Leitfaden-Text"
        assert definition.default_agent_prompt_ids == [
            "rt_skeptiker",
            "rt_praezise",
        ]
        assert definition.include_unchanged_research_material_context_in_prompt is False

    def test_frontmatter_round_trip_preserves_research_material_context_policy(
        self, tmp_path: Path
    ):
        repo = SessionTypeRepository(base_path=tmp_path)
        repo.create(
            SessionTypeDefinition(
                key="configured",
                label="Configured",
                description="D",
                body="B",
                include_unchanged_research_material_context_in_prompt=True,
            )
        )

        text = (tmp_path / "configured.md").read_text(encoding="utf-8")
        assert "include_unchanged_research_material_context_in_prompt: true" in text
        assert repo.get("configured").include_unchanged_research_material_context_in_prompt is True

    def test_invalid_frontmatter_is_skipped(self, tmp_path: Path):
        (tmp_path / "broken.md").write_text("Kein Frontmatter, nur Text.\n", encoding="utf-8")
        _write_md(tmp_path / "offene_exploration.md", key="offene_exploration", body="OK")

        repo = SessionTypeRepository(base_path=tmp_path)
        assert [d.key for d in repo.list()] == ["offene_exploration"]

    def test_invalid_yaml_frontmatter_is_skipped(self, tmp_path: Path):
        (tmp_path / "broken.md").write_text(
            '---\nkey: "offene_exploration\nlabel: L\n---\nB\n',
            encoding="utf-8",
        )
        _write_md(tmp_path / "interpretation_review.md", key="interpretation_review", body="OK")

        repo = SessionTypeRepository(base_path=tmp_path)
        assert [d.key for d in repo.list()] == ["interpretation_review"]

    def test_duplicate_create_rejected_by_repository(self, tmp_path: Path):

        repo = SessionTypeRepository(base_path=tmp_path)
        first = SessionTypeDefinition(
            key="offene_exploration",
            label="L",
            description="D",
            body="B",
        )
        repo.create(first)

        with pytest.raises(SessionTypeError):
            repo.create(first.model_copy(update={"body": "B2"}))

    def test_key_must_match_filename_is_skipped(self, tmp_path: Path):

        _write_md(
            tmp_path / "offene_exploration.md",
            key="interpretation_review",
            body="B",
        )
        _write_md(tmp_path / "interpretation_review.md", key="interpretation_review", body="OK")

        repo = SessionTypeRepository(base_path=tmp_path)
        assert [d.key for d in repo.list()] == ["interpretation_review"]

    def test_default_fallback_when_empty(self, tmp_path: Path):
        repo = SessionTypeRepository(base_path=tmp_path)
        assert repo.default() == "exploration"

    def test_default_uses_first_alphabetically(self, tmp_path: Path):
        _write_md(tmp_path / "offene_exploration.md", key="offene_exploration", body="B")
        repo = SessionTypeRepository(base_path=tmp_path)
        assert repo.default() == "offene_exploration"

    def test_get_returns_none_for_missing(self, tmp_path: Path):
        repo = SessionTypeRepository(base_path=tmp_path)
        assert repo.get("nope") is None


class TestSessionTypeRepositoryTraversal:
    def test_path_traversal_on_create_rejected(self, tmp_path: Path):
        repo = SessionTypeRepository(base_path=tmp_path)
        with pytest.raises(SessionTypeError):
            repo._safe_path("../escape")  # type: ignore[attr-defined]

    def test_path_traversal_with_dot_prefix_rejected(self, tmp_path: Path):
        repo = SessionTypeRepository(base_path=tmp_path)
        with pytest.raises(SessionTypeError):
            repo._safe_path("./../escape")  # type: ignore[attr-defined]


class TestSessionTypeRepositoryWrite:
    def test_create_then_update_changes_body(self, tmp_path: Path):
        repo = SessionTypeRepository(base_path=tmp_path)
        initial = SessionTypeDefinition(
            key="offene_exploration",
            label="Freie Exploration",
            description="D",
            body="Erster Body",
        )
        repo.create(initial)

        updated = initial.model_copy(update={"body": "Zweiter Body"})
        repo.update(updated)

        assert repo.get("offene_exploration").body == "Zweiter Body"
        on_disk = (tmp_path / "offene_exploration.md").read_text(encoding="utf-8")
        assert "Zweiter Body" in on_disk
        assert "Erster Body" not in on_disk

    def test_delete_removes_existing_definition_and_cache(self, tmp_path: Path):
        repo = SessionTypeRepository(base_path=tmp_path)
        definition = SessionTypeDefinition(
            key="eigener_typ",
            label="Eigener Typ",
            description="D",
            body="B",
        )
        repo.create(definition)

        repo.delete("eigener_typ")

        assert repo.get("eigener_typ") is None
        assert not (tmp_path / "eigener_typ.md").exists()

    def test_create_writes_file_with_frontmatter_and_body(self, tmp_path: Path):
        repo = SessionTypeRepository(base_path=tmp_path)
        definition = SessionTypeDefinition(
            key="exploration",
            label="Exploration",
            description="D",
            body="Leitfaden-Text",
            default_agent_prompt_ids=["rt_skeptiker", "rt_praezise"],
        )
        repo.create(definition)

        target = tmp_path / "exploration.md"
        assert target.is_file()
        on_disk = target.read_text(encoding="utf-8")
        assert "key: exploration" in on_disk
        assert "label: Exploration" in on_disk
        assert "Leitfaden-Text" in on_disk
        assert "rt_skeptiker" in on_disk
        assert "rt_praezise" in on_disk

    def test_create_round_trips_explicit_setup_inputs(self, tmp_path: Path):
        repo = SessionTypeRepository(base_path=tmp_path)
        definition = SessionTypeDefinition(
            key="critique",
            label="Critique",
            description="D",
            session_inputs=[
                {
                    "key": "research_material_context",
                    "label": "Research Material Context",
                    "prompt_heading": "RESEARCH MATERIAL CONTEXT",
                    "required": False,
                },
                {
                    "key": "main_input",
                    "label": "Main input",
                    "prompt_heading": "USER INPUT",
                    "required": True,
                },
                {
                    "key": "additional_instructions",
                    "label": "Additional instructions",
                    "prompt_heading": "ADDITIONAL USER INSTRUCTIONS",
                    "required": False,
                },
            ],
            body="Leitfaden-Text",
        )

        repo.create(definition)

        assert repo.get("critique").session_inputs[1].required is True
        assert "session_inputs:" in (tmp_path / "critique.md").read_text(encoding="utf-8")

    def test_duplicate_create_raises(self, tmp_path: Path):
        repo = SessionTypeRepository(base_path=tmp_path)
        definition = SessionTypeDefinition(
            key="offene_exploration",
            label="L",
            description="D",
            body="B",
        )
        repo.create(definition)
        with pytest.raises(SessionTypeError):
            repo.create(definition)

    def test_update_unknown_key_raises(self, tmp_path: Path):
        repo = SessionTypeRepository(base_path=tmp_path)
        definition = SessionTypeDefinition(
            key="offene_exploration",
            label="L",
            description="D",
            body="B",
        )
        with pytest.raises(SessionTypeError):
            repo.update(definition)

    def test_update_with_changed_id_rejected(self, tmp_path: Path):

        repo = SessionTypeRepository(base_path=tmp_path)
        original = SessionTypeDefinition(
            key="offene_exploration",
            label="L",
            description="D",
            body="B",
        )
        repo.create(original)

        # ``model_copy(update={"key": ...})`` keeps the ID format valid, but
        # ``update`` rejects the changed key because it is not in the cache.
        renamed = original.model_copy(update={"key": "interpretation_review", "body": "Neuer Body"})
        with pytest.raises(SessionTypeError):
            repo.update(renamed)

        assert repo.get("offene_exploration").body == "B"
