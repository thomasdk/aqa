"""CLI utilities for rendering discussion prompts without an LLM request.

Preview rendering uses the same prompt-assembly path as a live discussion.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .models import PromptTemplate
from .storage import PromptRepository

if TYPE_CHECKING:
    from src.service.discussion import MaterialContext
    from src.service.discussion_domain import DiscussionState


_SEPARATOR = "=" * 72
_THIN_SEP = "-" * 72

# Preview placeholders prevent fixture values from being mistaken for user input.
PREVIEW_PLACEHOLDER = "[Preview: set during the discussion]"
PREVIEW_TARGET_LANGUAGE = "[Preview: selected response language]"
PREVIEW_RESEARCHER_NOTE = "[Preview: synthetic researcher note, opted in for Perspective context]"
PREVIEW_SCENARIOS = (
    "first_round",
    "first_round_sequential",
    "continuation",
    "continuation_sequential",
)


def _discover_base_path() -> Path:
    """Locate the project's ``data/prompts`` directory."""

    project_root = Path(__file__).resolve().parents[2]
    candidates = [
        project_root / "data" / "prompts",
        Path("./data/prompts"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _build_material_context_for_preview(
    session_type: str,
    *,
    service: Any = None,
) -> MaterialContext:
    """Build a deterministic ``MaterialContext`` for preview rendering."""

    # Avoid importing the discussion module before the preview helpers load.
    from src.service.discussion import MaterialContext

    if service is not None and hasattr(service, "_normalize_session_type"):
        normalized = service._normalize_session_type(session_type)
    else:
        normalized = session_type

    definitions = []
    if service is not None:
        definition = service.session_type_repo.get(normalized)
        definitions = list(definition.session_inputs) if definition is not None else []
    return MaterialContext(
        material_type="document",
        session_type=normalized,
        target_language=PREVIEW_TARGET_LANGUAGE,
        session_input_values={item.key: PREVIEW_PLACEHOLDER for item in definitions},
        session_inputs=definitions,
    )


def build_preview_rendered(
    service: Any,
    template: PromptTemplate,
    material_context: MaterialContext,
    *,
    multi_agent: bool = False,
    total_agents: int = 1,
    other_agents: Sequence[tuple[str, str]] | None = None,
) -> tuple[str, dict]:
    """Render a preview through the production prompt-assembly path."""

    # A live multi-agent discussion always provides the other perspectives.
    # The preview has no selected agent roster, therefore use explicit generic
    # placeholders instead of silently rendering a single-agent scaffold.
    if multi_agent and other_agents is None:
        other_agents = [
            ("Agent 2", "[Preview: second perspective]"),
            ("Agent 3", "[Preview: third perspective]"),
        ]
    if multi_agent:
        # Multi-agent previews always require the complete three-perspective setup.
        total_agents = max(total_agents, 3)

    rendered = service.build_system_prompt(
        prompt_id=template.id,
        agent_config=None,
        agent_index=0,
        total_agents=total_agents if multi_agent else 1,
        other_agents=other_agents,
        material_context=material_context,
        use_prompt_snapshot=False,
    )
    rendered = rendered or ""

    segments: dict = {}
    if template.role:
        segments["role"] = template.role
    if template.task:
        segments["task"] = template.task
    if template.output_format:
        segments["output_format"] = template.output_format

    globals_text = service.prompt_repo.get_common_instructions(multi_agent=multi_agent)
    if globals_text:
        segments["globals"] = globals_text

    context_section = _extract_section(rendered, "=== RESEARCH TASK ===")
    if context_section:
        segments["context"] = context_section

    return rendered, segments


def build_preview_user_prompt(
    material_context: MaterialContext,
    *,
    scenario: str = "first_round",
    multi_agent: bool = False,
    discussion_state: DiscussionState | None = None,
) -> str:
    """Build a deterministic user-message example through the live renderer.

    Multi-perspective continuations include completed contributions from all
    three preview perspectives.
    """

    from src.service.discussion_domain import AgentResponse, DiscussionState
    from src.service.discussion_prompts import append_perspective_user_reminders

    if scenario not in PREVIEW_SCENARIOS:
        raise ValueError(f"Unknown preview scenario: {scenario}")

    if discussion_state is not None:
        prompt = discussion_state.get_context_for_agents()
        previous_round = discussion_state.round_number - 1
        return append_perspective_user_reminders(
            prompt,
            target_language=material_context.target_language,
            previous_round=previous_round,
            has_previous_round_note=previous_round > 0
            and discussion_state.has_included_researcher_note_in_round(previous_round),
        )

    main_input = material_context.session_input_values.get("main_input", PREVIEW_PLACEHOLDER)
    state = DiscussionState(material="[Preview: original material]", round_number=1)
    state.add_user_message(main_input)

    if scenario in {"continuation", "continuation_sequential"}:
        if multi_agent:
            for perspective_number in range(1, 4):
                contribution = state.add_agent_response(
                    AgentResponse(
                        message_id=f"preview-r1-p{perspective_number}",
                        agent_index=perspective_number - 1,
                        agent_name=f"Preview perspective {perspective_number}",
                        theory_label="",
                        color="#000000",
                        perspective_number=perspective_number,
                        text=(
                            "[Preview: earlier round contribution from "
                            f"Perspective {perspective_number}]"
                        ),
                    )
                )
                if perspective_number == 1:
                    contribution.note = PREVIEW_RESEARCHER_NOTE
                    contribution.include_note_in_agent_context = True
        else:
            contribution = state.add_agent_response(
                AgentResponse(
                    message_id="preview-r1-p3",
                    agent_index=0,
                    agent_name="Preview perspective",
                    theory_label="",
                    color="#000000",
                    perspective_number=3,
                    text="[Preview: earlier round contribution]",
                )
            )
            contribution.note = PREVIEW_RESEARCHER_NOTE
            contribution.include_note_in_agent_context = True
        state.round_number = 2
        state.add_user_message("[Preview: current moderator task]")
    if scenario in {"first_round_sequential", "continuation_sequential"}:
        state.add_agent_response(
            AgentResponse(
                message_id="preview-current-p3",
                agent_index=0,
                agent_name="Preview perspective",
                theory_label="",
                color="#000000",
                perspective_number=3,
                text="[Preview: earlier same-round contribution]",
            )
        )

    return build_preview_user_prompt(material_context, discussion_state=state)


def _extract_section(rendered: str, header: str) -> str | None:
    """Extract a header-delimited section from rendered prompt text."""

    if header not in rendered:
        return None
    start = rendered.index(header)
    tail = rendered[start + len(header) :]
    end = len(tail)
    marker = "\n=== "
    next_idx = tail.find(marker)
    if next_idx != -1:
        end = next_idx
    return (header + tail[:end]).strip()


def _build_preview(
    template: PromptTemplate,
    common_instructions: str,
    *,
    multi_agent: bool = False,
    total_agents: int = 1,
) -> str:
    """Build a preview directly from a template and global instructions."""

    if multi_agent:
        parts: list[str] = ["=== CONTEXT ===", "\nDISCUSSION CONTEXT:"]
        parts.append(f"You are perspective 1 of {total_agents} in this analysis round.")
        parts.append(f"Your perspective: {template.label}")
        parts.append("Other perspectives in this round: (set at runtime)")
        parts.append(
            "Each perspective examines the material differently — be specific to YOUR perspective."
        )
        context_block = "\n".join(parts)
    else:
        context_block = None

    parts_all: list[str] = []
    if context_block:
        parts_all.append(context_block)
    if common_instructions:
        parts_all.append(common_instructions)
    if template.role:
        parts_all.append(f"ROLE:\n{template.role}")
    if template.task:
        parts_all.append(f"UNIQUE PERSPECTIVE TASK:\n{template.task}")
    if template.output_format:
        parts_all.append(f"OUTPUT FORMAT:\n{template.output_format}")

    return "\n\n".join(parts_all) if parts_all else "(empty prompt)"


def print_template_list(repo: PromptRepository) -> None:
    """Print a compact list of available templates."""

    templates = repo.list_templates()
    globals_ = repo.list_globals()

    print(f"\n{_SEPARATOR}")
    print(f"  PROMPT-BIBLIOTHEK  ({len(templates)} Templates, {len(globals_)} Globals)")
    print(_SEPARATOR)

    print("\n  Templates:")
    for tpl in templates:
        source = tpl.metadata.get("source_file", "?")
        source_short = Path(str(source)).name if source != "?" else "?"
        print(f"    {tpl.id:<35s} {tpl.label:<30s} [{source_short}]")

    print("\n  Globale Bloecke:")
    for block in globals_:
        scope_info = f"scope={block.scope}" if block.scope else "immer"
        print(f"    {block.id:<35s} {block.label:<30s} [{scope_info}]")

    print()


def print_globals(repo: PromptRepository) -> None:
    """Print every global instruction block."""

    globals_ = repo.list_globals()
    print(f"\n{_SEPARATOR}")
    print(f"  GLOBALE PROMPT-BLOECKE  ({len(globals_)} Stueck)")
    print(_SEPARATOR)

    for block in globals_:
        scope_info = f"(scope: {block.scope})" if block.scope else "(immer aktiv)"
        print(f"\n{_THIN_SEP}")
        print(f"  [{block.id}] {block.label} {scope_info}")
        print(_THIN_SEP)
        print(block.content)

    print()


def print_preview(
    repo: PromptRepository,
    template_id: str,
    *,
    multi_agent: bool = False,
    session_type: str = "",
    base_path: Path | None = None,
) -> bool:
    """Render and print one template preview, returning whether it exists."""

    template = repo.get_template(template_id)
    if template is None:
        print(f"\n  FEHLER: Template '{template_id}' nicht gefunden.\n")
        print("  Verfuegbare IDs:")
        for tpl in repo.list_templates():
            print(f"    - {tpl.id}")
        print()
        return False

    from src.service.discussion import DiscussionService

    resolved_base = Path(base_path) if base_path is not None else _discover_base_path()
    settings = _build_preview_settings(prompt_library_path=resolved_base)
    llm_manager = _build_preview_llm_manager()
    session_context_dir = resolved_base / "session_contexts"
    service = DiscussionService(
        settings=settings,
        llm_manager=llm_manager,
        prompt_repo=repo,
        session_context_dir=session_context_dir,
    )

    selected_session_type = session_type or service.get_default_session_type()
    material_context = _build_material_context_for_preview(selected_session_type, service=service)

    total_agents = 3 if multi_agent else 1
    preview_text, _segments = build_preview_rendered(
        service=service,
        template=template,
        material_context=material_context,
        multi_agent=multi_agent,
        total_agents=total_agents,
    )

    mode_label = "Multi-agent (3 perspectives)" if multi_agent else "Single perspective"
    session_definition = service.session_type_repo.get(material_context.session_type)
    if session_definition is not None:
        session_label = session_definition.label
    else:
        session_label = material_context.session_label

    print(f"\n{_SEPARATOR}")
    print(f"  PROMPT PREVIEW: {template.label}")
    print(f"  ID: {template_id}  |  Mode: {mode_label}  |  Session: {session_label}")
    print(f"  Length: {len(preview_text)} characters  |  ~{len(preview_text) // 4} tokens")
    print(_SEPARATOR)
    print()
    print(preview_text)
    print()
    print(_SEPARATOR)
    print(f"  End preview: {template.label}")
    print(_SEPARATOR)
    print()

    return True


def print_all_previews(
    repo: PromptRepository,
    *,
    multi_agent: bool = False,
    session_type: str = "",
    base_path: Path | None = None,
) -> None:
    """Render and print every available template."""

    templates = repo.list_templates()
    mode_label = "Multi-agent" if multi_agent else "Single perspective"

    print(f"\n{'#' * 72}")
    print(f"  ALL TEMPLATES  ({len(templates)} total, mode: {mode_label})")
    print(f"{'#' * 72}")

    for tpl in templates:
        print_preview(
            repo,
            tpl.id,
            multi_agent=multi_agent,
            session_type=session_type,
            base_path=base_path,
        )


def _build_preview_settings(prompt_library_path: Path | None = None) -> Any:
    """Build the minimal settings object required by preview rendering."""

    if prompt_library_path is None:
        prompt_library_path = _discover_base_path()
    return _PreviewSettingsStub(prompt_library_path=Path(prompt_library_path))


def _build_preview_llm_manager() -> Any:
    """Build the no-op LLM manager required by preview rendering."""

    try:
        return _PreviewLLMManagerStub()
    except Exception:
        return _PreviewLLMManagerStub()


class _PreviewSettingsStub:
    """Minimal settings surface required by ``DiscussionService``."""

    def __init__(self, prompt_library_path: Path | None = None) -> None:
        self.prompt_library_path = (
            str(prompt_library_path) if prompt_library_path is not None else ""
        )


class _PreviewLLMManagerStub:
    """No-op LLM manager because preview rendering makes no LLM request."""

    def __init__(self) -> None:
        pass


def main(argv: list[str] | None = None) -> int:
    """Run the prompt-preview CLI."""

    parser = argparse.ArgumentParser(
        description="Prompt-Preview: Zeigt System-Prompts so an wie sie der LLM erhaelt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "template_id",
        nargs="?",
        default=None,
        help="ID des zu rendernden Templates (z.B. symbolic_interactionism)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Alle Templates nacheinander rendern",
    )
    parser.add_argument(
        "--multi-agent",
        action="store_true",
        help="Multi-Agent-Modus simulieren (inkl. Diskussionsnormen)",
    )
    parser.add_argument(
        "--session-type",
        type=str,
        default="",
        help=(
            "Session type for the research context (for example exploration or critique). "
            "The value must match a configured session type."
        ),
    )
    parser.add_argument(
        "--globals",
        action="store_true",
        help="Nur die globalen Bloecke anzeigen",
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="Pfad zum Prompt-Verzeichnis (Standard: data/prompts)",
    )

    args = parser.parse_args(argv)

    base_path = Path(args.path) if args.path else _discover_base_path()
    if not base_path.exists():
        print(f"FEHLER: Prompt-Verzeichnis nicht gefunden: {base_path}")
        return 1

    repo = PromptRepository(base_path=base_path)

    if args.globals:
        print_globals(repo)
        return 0

    try:
        if args.all:
            print_all_previews(
                repo,
                multi_agent=args.multi_agent,
                session_type=args.session_type,
                base_path=base_path,
            )
            return 0

        if args.template_id:
            ok = print_preview(
                repo,
                args.template_id,
                multi_agent=args.multi_agent,
                session_type=args.session_type,
                base_path=base_path,
            )
            return 0 if ok else 1
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print_template_list(repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
