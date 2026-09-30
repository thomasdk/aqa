"""Tests for the prompt repository."""

from pathlib import Path

import pytest

from src.prompts import PromptContextBlock, PromptRepository


@pytest.fixture()
def prompt_repo(tmp_path: Path) -> PromptRepository:
    """Create a ``PromptRepository`` with a test POML file."""

    library_dir = tmp_path / "prompts"
    library_dir.mkdir()

    source_poml = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "prompts"
        / "roles"
        / "conceptualization.poml"
    )
    target_poml = library_dir / "conceptualization.poml"
    target_poml.write_text(source_poml.read_text(encoding="utf-8"), encoding="utf-8")

    source_globals = (
        Path(__file__).resolve().parent.parent / "data" / "prompts" / "prompts_globals.poml"
    )
    target_globals = library_dir / "prompts_globals.poml"
    target_globals.write_text(source_globals.read_text(encoding="utf-8"), encoding="utf-8")

    return PromptRepository(base_path=library_dir)


def test_list_templates_contains_known_id(prompt_repo: PromptRepository):
    templates = prompt_repo.list_templates()
    identifiers = {template.id for template in templates}
    assert "conceptualization" in identifiers


def test_render_template_produces_valid_output(prompt_repo: PromptRepository):
    result = prompt_repo.render_template("conceptualization")

    # Rendering must resolve every placeholder.
    assert "{{" not in result.prompt_text
    # Role and task content are required.
    assert "role" in result.segments
    assert "task" in result.segments
    assert len(result.prompt_text) > 50


def test_render_template_with_overrides(prompt_repo: PromptRepository):
    fragment = prompt_repo.save_prompt(
        name="Eigene Rolle",
        content="Custom Rolle",
        slot="role",
        template_id="conceptualization",
    )

    block = PromptContextBlock(label="Zusatz", content="{{text_excerpt}} (extra)")

    result = prompt_repo.render_template(
        "conceptualization",
        placeholders={
            "text_excerpt": "Snippet",
            "discussion_summary": "Diskussion",
            "moderator_prompt": "Moderator",
        },
        overrides={
            "role": fragment.id,
            "contexts": [block],
        },
        additional_fragments=[
            prompt_repo.save_prompt(
                name="Extra",
                content="Zusatzhinweise",
                slot="suffix",
            )
        ],
    )

    assert result.segments["role"] == "Custom Rolle"
    assert "Zusatz:\nSnippet (extra)" in result.segments["contexts"]
    assert "Zusatzhinweise" in result.segments["custom"]


def test_template_description_is_catalogue_metadata_not_prompt_content(
    prompt_repo: PromptRepository,
):
    template = prompt_repo.get_template("conceptualization")
    assert template is not None
    assert template.description == (
        "Identifies overarching patterns, arguments, social dynamics, and tensions while staying "
        "close to the material."
    )
    assert template.description not in prompt_repo.render_template("conceptualization").prompt_text


def test_save_and_list_user_prompts(prompt_repo: PromptRepository):
    fragment = prompt_repo.save_prompt(
        name="Kontext",
        content="Eigenes Fragment",
        slot="context",
    )

    stored = prompt_repo.get_prompt(fragment.id)
    assert stored is not None
    assert stored.slot == "context"

    all_prompts = prompt_repo.list_prompts()
    assert fragment.id in {item.id for item in all_prompts}


def test_common_instructions_include_compact_response_contract(prompt_repo: PromptRepository):
    common = prompt_repo.get_common_instructions()

    assert "RESPONSE CONTRACT" in common
    assert "one continuous paragraph of 5-8 complete sentences" in common
    assert "Do not use quotation marks anywhere in the response" in common
    assert "Paraphrase every material-based claim in your own words" in common
    assert "cite only exact references to existing numbered lines" in common
    assert "all references supporting one claim in one pair of parentheses" in common
    assert "(`Z0002`, `Z0010`) or (`Z0014-Z0016`)" in common
    assert "write adjacent citation groups such as (`Z0002`), (`Z0010`)" in common
    assert "invent a reference" in common
    assert "use `Z0000`" not in common
    assert "cite speaker or participant identifiers" in common
    assert "Use only `Z0000` line references" not in common
    assert "only in the format `Perspective N`" in common
    assert '"As `Perspective 1` argued' not in common
    assert "Do not use italic or bold-italic text" in common
    assert "State your finished analytical contribution directly" in common
    assert "Keep sentences short, with a simple structure" in common
    assert "Always quote full sentences" not in common
    assert "dominant language" not in common


def test_common_instruction_fallback_is_english(tmp_path: Path):
    repository = PromptRepository(base_path=tmp_path)

    assert repository.get_common_instructions() == (
        "=== TECHNICAL REQUIREMENTS ===\nDO NOT use Markdown tables."
    )
