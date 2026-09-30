"""Contracts for the prompt set shipped with AQA.

These tests intentionally validate structure and references, not the wording of
the research prompts. Prompt content remains a product decision and should not
be frozen in large text snapshots.
"""

from pathlib import Path

from src.prompts.session_types import SessionTypeRepository
from src.prompts.storage import PromptRepository

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_PROMPTS = PROJECT_ROOT / "data" / "prompts"
DEFAULT_PROMPTS = PROJECT_ROOT / "data" / "prompt_defaults"


def _relative_file_bytes(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in {".poml", ".md"}
    }


def test_shipped_prompt_defaults_match_the_active_prompt_set() -> None:

    active = _relative_file_bytes(ACTIVE_PROMPTS)
    defaults = _relative_file_bytes(DEFAULT_PROMPTS)

    assert active == defaults


def test_all_shipped_roles_are_parseable_and_match_their_filenames() -> None:
    repository = PromptRepository(base_path=ACTIVE_PROMPTS)
    roles = repository.list_templates()
    role_files = sorted((ACTIVE_PROMPTS / "roles").glob("*.poml"))

    assert {role.id for role in roles} == {"conceptualization", "precision", "skepticism"}
    assert len(roles) == 3
    assert {role.id for role in roles} == {path.stem for path in role_files}
    assert len({role.id for role in roles}) == len(roles)

    for role in roles:
        assert role.label
        assert role.description
        assert role.role
        assert role.task
        assert role.output_format
        assert Path(str(role.metadata["source_file"])).stem == role.id


def test_shipped_globals_are_parseable_and_unique() -> None:
    repository = PromptRepository(base_path=ACTIVE_PROMPTS)
    blocks = repository.list_globals()

    assert {block.id for block in blocks} == {
        "principles",
        "response_contract",
        "roundtable_norms",
        "round_synthesis",
    }
    assert len({block.id for block in blocks}) == len(blocks)
    assert all(block.label and block.content for block in blocks)


def test_shipped_roles_match_the_current_prompt_brief() -> None:
    roles = {role.id: role for role in PromptRepository(base_path=ACTIVE_PROMPTS).list_templates()}

    assert roles["conceptualization"].task == (
        "Analyze the material and develop grounded, easy-to-understand concepts that capture what "
        "matters most. Clearly distinguish what is explicit in the material from your "
        "interpretations and inferences."
    )
    assert roles["precision"].task == (
        "Check interpretations and claims against the material. Focus on the most important "
        "claims already made and explain how well the material supports them. Do not introduce "
        "new interpretations. If a claim is too broad or too certain, offer a version that stays "
        "closer to the material. Reference the relevant passage, or ask for it when it is missing."
    )
    assert roles["precision"].output_format == (
        "When referring to another contribution, clearly state which `Perspective N` and which "
        "claim you are referring to exactly."
    )
    assert roles["skepticism"].task == (
        "Look for ambiguity, tension, contrast, and signs that point in different directions. "
        "Identify the strongest interpretation so far, then develop a credible alternative. "
        "Reference a specific passage whenever fitting. If your proposed alternative goes beyond "
        "the available material, clearly label it as speculation. End by explaining what kind of "
        "material or test could help decide between the competing interpretations."
    )
    assert roles["skepticism"].output_format == (
        "Present the alternative reading as one connected argument."
    )


def test_round_synthesis_prompt_requires_literal_markdown_bullets() -> None:
    repository = PromptRepository(base_path=ACTIVE_PROMPTS)
    synthesis = repository.get_global("round_synthesis")

    assert synthesis is not None
    assert 'Every item must begin with "- "' in synthesis.content
    assert "- **[localized label for one permitted category type]:**" in synthesis.content
    assert "same physical line" in synthesis.content
    assert "SHARED_FINDING, DIFFERENCE, QUALIFICATION, or OPEN_QUESTION" in synthesis.content
    assert "Do not create additional category types" in synthesis.content
    assert "Translate the meaning of the selected internal category type" in synthesis.content
    for english_label in (
        "**Shared finding:**",
        "**Difference:**",
        "**Qualification:**",
        "**Open question:**",
    ):
        assert english_label not in synthesis.content
    assert "Synthesize the current-round contributions in your own words" in synthesis.content
    assert "Do not reproduce direct quotations" in synthesis.content
    assert "all material line references supporting one synthesized statement" in synthesis.content
    assert "(`Z0002`, `Z0010`) or (`Z0014-Z0016`)" in synthesis.content
    assert "Never write adjacent citation groups" in synthesis.content
    assert "source-specific concepts or terms" not in synthesis.content
    assert '*"exact wording"* (`Z0035`)' not in synthesis.content
    assert "Name a perspective only as `Perspective N`" in synthesis.content
    assert "Use Markdown bold only for category lead-ins" in synthesis.content
    assert "Do not use italic or bold-italic text" in synthesis.content
    assert "State each finding directly" in synthesis.content
    assert (
        "Never announce, preview, or describe what you are going to write, synthesize"
        in synthesis.content
    )


def test_regular_response_contract_is_compact_and_canonical() -> None:
    repository = PromptRepository(base_path=ACTIVE_PROMPTS)
    contract = repository.get_global("response_contract")

    assert contract is not None
    assert "one continuous paragraph of 5-8 complete sentences" in contract.content
    assert "Choose the exact length according to complexity of the argument" in contract.content
    assert "the number of references" in contract.content
    assert "MUST bold exactly 2-4 central analytical terms" in contract.content
    assert "Do not use italic or bold-italic text" in contract.content
    assert "Use Markdown bold only for the required central analytical terms" in contract.content
    assert "Do not use quotation marks anywhere in the response" in contract.content
    assert "Paraphrase every material-based claim in your own words" in contract.content
    assert "cite only exact references to existing numbered lines" in contract.content
    assert "all references supporting one claim in one pair of parentheses" in contract.content
    assert "(`Z0002`, `Z0010`) or (`Z0014-Z0016`)" in contract.content
    assert "write adjacent citation groups such as (`Z0002`), (`Z0010`)" in contract.content
    assert "invent a reference" in contract.content
    assert "use `Z0000`" not in contract.content
    assert "cite speaker or participant identifiers" in contract.content
    assert "Use only `Z0000` line references" not in contract.content
    assert "directly quote a segment" not in contract.content
    assert "Always quote full sentences" not in contract.content
    assert "only in the format `Perspective N`" in contract.content
    assert '"As `Perspective 1` argued' not in contract.content
    assert "State your finished analytical contribution directly" in contract.content
    assert (
        "Never announce, preview, or describe what you are going to write, argue, develop"
        in contract.content
    )
    assert "Get to the point" in contract.content
    assert "Keep sentences short, with a simple structure" in contract.content
    assert contract.content.endswith("Avoid academic jargon, fillers, and formality.")
    assert not contract.content.startswith("LANGUAGE:")
    assert "dominant language" not in contract.content


def test_shipped_session_types_reference_existing_roles() -> None:
    roles = {role.id for role in PromptRepository(base_path=ACTIVE_PROMPTS).list_templates()}
    sessions = SessionTypeRepository(ACTIVE_PROMPTS / "session_contexts").list()

    assert {session.key for session in sessions} == {
        "critique",
        "exploration",
    }
    for session in sessions:
        assert session.body
        assert session.default_agent_prompt_ids
        assert set(session.default_agent_prompt_ids) <= roles


def test_shipped_session_types_include_the_default_research_material_context_scaffold() -> None:
    sessions = SessionTypeRepository(ACTIVE_PROMPTS / "session_contexts").list()
    expected = (
        "**Research Topic and Question**\n\n…\n\n"
        "**Information on the Case / Material, Speaker Assignment, etc.**\n\n…\n\n"
        "**Important Terms and Background Knowledge**\n\n…"
    )
    for session in sessions:
        research_material_context = session.input_for_key("research_material_context")
        assert research_material_context is not None
        assert research_material_context.label == "Research Material Context"
        assert research_material_context.default_text == expected
        assert session.include_unchanged_research_material_context_in_prompt is False
        assert research_material_context.prompt_heading == "RESEARCH MATERIAL CONTEXT"
        main_input = session.input_for_key("main_input")
        additional = session.input_for_key("additional_instructions")
        assert main_input is not None
        assert additional is not None
        assert main_input.prompt_heading == "USER INPUT"
        assert additional.prompt_heading == "ADDITIONAL USER INSTRUCTIONS"


def test_shipped_operational_prompts_are_english() -> None:

    content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in ACTIVE_PROMPTS.rglob("*")
        if path.suffix in {".poml", ".md"}
    )
    assert 'id="response_contract"' in content
    assert "Use USER INPUT as your starting point." in content
    assert "=== BEHAVIOR FOR 'OPEN EXPLORATION' MODE ===" not in content
    for german_marker in (
        "GRUNDHALTUNG",
        "ZEILENREFERENZEN",
        "ANFORDERUNG IM MODUS",
        "FREIE EXPLORATION",
    ):
        assert german_marker not in content


def test_shipped_global_copy_matches_the_canonical_formulations() -> None:
    repository = PromptRepository(base_path=ACTIVE_PROMPTS)
    principles = repository.get_global("principles")
    norms = repository.get_global("roundtable_norms")

    assert principles is not None
    assert norms is not None
    assert (
        "COLLABORATIVE: Act as a thoughtful research partner. Build on ideas and engage "
        "constructively and critically."
    ) in principles.content
    assert "SITUATED: Make your personal stance and reasoning explicit." in principles.content
    assert (
        "EVIDENCE-BASED: Ground interpretation in the material. Follow the EVIDENCE "
        "rules in the response contract exactly."
    ) in principles.content
    assert "short, focused quotations or line references" not in principles.content
    assert (
        "ENGAGE: When a prior contribution in the current round is available, respond "
        "explicitly: agree, refine, or disagree, and explain why."
    ) in norms.content
    assert (
        "CONSTRUCTIVE: When you disagree, offer a better formulation or alternative."
    ) in norms.content
    assert "TRANSPARENT: If you change your position, briefly state your reasoning." in (
        norms.content
    )
    assert (
        "RESPONSIVE: Connect your contribution to the discussion without repeating points "
        "made prior. Remember that the user has already read all previous responses."
    ) in norms.content
