"""Pure prompt-assembly helpers used by the DiscussionService facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.prompts.session_types import effective_session_input_value
from src.service.discussion_domain import MaterialContext

RESEARCHER_NOTE_SYSTEM_RULE = (
    "Included researcher notes provide the researcher’s interpretations and guidance for the "
    "discussion. Consider them when developing your response, distinguishing them from evidence "
    "in the source material."
)
RESEARCHER_NOTE_REMINDER_HEADING = "=== RESEARCHER NOTES REMINDER ==="
RESEARCHER_NOTE_REMINDER_TEXT = (
    "Address the included researcher notes from Round {N} where relevant to the current question."
)


def perspective_prompt_layout() -> str:
    """Document the current assembly policy captured with new discussions."""

    return (
        "Perspective system: discussion setting, session context, research task, session guidance, "
        "shared instructions, researcher-note rule, perspective prompt, language rule. "
        f"Researcher-note rule: {RESEARCHER_NOTE_SYSTEM_RULE} "
        "Perspective user: material, included transcript (notes beside their associated Perspective "
        "responses), current user input, a conditional request-local researcher-note reminder, "
        "and the final request-local language reminder. "
        "The reminder appears only when selected discussion context includes an opted-in note on "
        "an included Perspective response from the immediately preceding round; it follows the "
        "current moderator input and precedes the language reminder. "
        f"Reminder template: {RESEARCHER_NOTE_REMINDER_HEADING}\n"
        f"{RESEARCHER_NOTE_REMINDER_TEXT} Replace {{N}} with that round’s actual number. "
        "This layout describes current prompt rules, not historical request payloads. "
        "Synthesis: frozen synthesis instructions plus current-round contributions."
    )


def _template_part(template: Any, name: str) -> str | None:
    """Return one non-empty template field from a mapping or model."""

    value = template.get(name) if isinstance(template, Mapping) else getattr(template, name, None)
    return value if isinstance(value, str) and value else None


def _research_task(material_context: MaterialContext) -> str | None:
    """Render populated session inputs that belong in the model context."""

    research: list[str] = []
    for item in material_context.session_inputs:
        value = effective_session_input_value(
            item.key,
            material_context.session_input_values.get(item.key, ""),
            item.default_text,
            material_context.include_unchanged_research_material_context_in_prompt,
        )
        if item.key == "research_material_context":
            if not value:
                continue
        elif item.key == "additional_instructions" and not value:
            continue
        research.append(f"{item.prompt_heading}:\n{value}")
    return "=== RESEARCH TASK ===\n" + "\n\n".join(research) if research else None


def _perspective_sections(template: Any) -> str | None:
    """Render the role, task, and format sections for one perspective."""

    labels = {
        "role": "ROLE",
        "task": "UNIQUE PERSPECTIVE TASK",
        "output_format": "OUTPUT FORMAT",
    }
    sections = [
        f"{labels[name]}:\n{value}" for name in labels if (value := _template_part(template, name))
    ]
    return "=== YOUR PERSPECTIVE ===\n" + "\n\n".join(sections) if sections else None


def _response_language_instruction(target_language: str) -> str:
    return f"Write all prose in {target_language}."


def append_response_language_reminder(prompt: str, target_language: str) -> str:
    """Append a request-local language reminder without mutating the transcript."""

    language = target_language.strip()
    if not language:
        return prompt
    return (
        f"{prompt}\n\n=== CURRENT RESPONSE LANGUAGE REMINDER ===\n"
        f"{_response_language_instruction(language)}"
    )


def append_previous_round_note_reminder(prompt: str, round_number: int) -> str:
    """Add a request-local reminder for included notes from the preceding round."""

    return (
        f"{prompt}\n\n{RESEARCHER_NOTE_REMINDER_HEADING}\n"
        f"{RESEARCHER_NOTE_REMINDER_TEXT.replace('{N}', str(round_number))}"
    )


def append_perspective_user_reminders(
    prompt: str, *, target_language: str, previous_round: int, has_previous_round_note: bool
) -> str:
    """Keep conditional note and final language reminders in request order."""

    if has_previous_round_note:
        prompt = append_previous_round_note_reminder(prompt, previous_round)
    return append_response_language_reminder(prompt, target_language)


def build_system_prompt(
    *,
    template: Any,
    common_instructions: str,
    session_requirement: str = "",
    agent_index: int = 0,
    perspective_number: int | None = None,
    total_agents: int = 1,
    other_agents: list[tuple[str, str]] | None = None,
    material_context: MaterialContext | None = None,
    session_label: str | None = None,
) -> str | None:
    """Assemble the stable system-prompt contract for one perspective.

    ``perspective_number`` is a durable identity, not an execution position.
    The prompt deliberately exposes neither the roster order nor another
    perspective's semantic orientation.
    """

    # A single-perspective invocation still has a stable identity. This keeps
    # role output and attribution consistent across all
    # orchestration modes. Put the discussion setting first so the model has
    # its collaboration role before it receives session-specific context.
    number = perspective_number or agent_index + 1
    parts: list[str] = [
        "=== DISCUSSION SETTING ===\n"
        "You are part of a qualitative research team conducting collaborative data analysis. "
        "The team includes a human user and several AI systems called `Perspectives`.\n"
        f"You are `Perspective {number}`.\n"
        "Other perspectives may appear in the discussion as `Perspective N`."
    ]
    if material_context:
        session_type = session_label or material_context.session_label
        material_type = material_context.type_label
        parts.append(
            f"=== SESSION CONTEXT ===\nSESSION TYPE: {session_type}\nMATERIAL TYPE: {material_type}"
        )

        if research := _research_task(material_context):
            parts.append(research)

        requirement = session_requirement.strip()
        if requirement:
            parts.append(f"=== BEHAVIOR FOR '{session_type.upper()}' MODE ===\n{requirement}")

    if common_instructions:
        parts.append(common_instructions)

    parts.append(f"=== RESEARCHER NOTES ===\n{RESEARCHER_NOTE_SYSTEM_RULE}")

    if perspective := _perspective_sections(template):
        parts.append(perspective)
    # Keep this requirement last: role/global prompt assets may be English,
    # but they must never override the explicitly configured response language.
    if material_context and material_context.target_language:
        parts.append(
            "=== FINAL RESPONSE LANGUAGE REQUIREMENT ===\n"
            f"{_response_language_instruction(material_context.target_language)} "
            "Before returning the response, "
            "verify that it contains no quotation marks, that every material-based claim is "
            "paraphrased, and that every line reference appears inside one parenthesized citation "
            "group immediately after its claim."
        )
    return "\n\n".join(parts) if parts else None


def build_user_prompt(
    material: str,
    question: str,
    material_context: MaterialContext | None = None,
) -> str:
    """Build the deterministic first-round envelope for direct callers.

    Live discussions use :meth:`DiscussionState.get_context_for_agents` so
    that prior rounds and sequential responses are available as well.  This
    pure fallback preserves the same round-one boundary for synchronous and
    test callers that have no discussion state.
    """

    parts: list[str] = []
    if material:
        parts.append(f"=== RESEARCH MATERIAL (AUTHORITATIVE SOURCE) ===\n{material}")
    parts.append(f"=== CURRENT ROUND USER INPUT (ROUND 1) ===\n{question}")
    return append_response_language_reminder(
        "\n\n".join(parts),
        material_context.target_language if material_context else "",
    )


def build_synthesis_user_prompt(
    *,
    session_label: str,
    session_description: str,
    material_type_label: str,
    target_language: str = "",
    session_inputs: list[tuple[str, str]],
    participants: list[tuple[str, str]],
    question: str,
    contributions: list[tuple[str, str, str, str | None]],
) -> str:
    """Build the deliberately round-scoped synthesis input.

    Source material, prior rounds, notes, and prior syntheses are never
    accepted by this API. That keeps the context boundary auditable.
    """
    orientation = [
        f"Session type: {session_label}",
        f"Session description: {session_description}" if session_description else "",
        f"Material type: {material_type_label}",
    ]
    orientation.extend(f"{heading}: {value}" for heading, value in session_inputs if value)
    if participants:
        orientation.append(
            "Participants:\n" + "\n".join(f"- {name}" for name, _label in participants)
        )

    rendered_contributions: list[str] = []
    for name, _label, text, error in contributions:
        status = "\nStatus: partial response" if error and text.strip() else ""
        if not text.strip():
            status = "\nStatus: no usable contribution"
        rendered_contributions.append(
            f"[{name}]\n{text.strip() or '(no usable contribution)'}{status}"
        )

    prompt = (
        "=== ORIENTATION — NOT YOUR TASK ===\n"
        + "\n".join(item for item in orientation if item)
        + "\n\n=== CURRENT ROUND — CONTENT TO SYNTHESIZE ===\n"
        + f"Moderator question:\n{question}\n\n"
        + "\n\n".join(rendered_contributions)
    )
    return append_response_language_reminder(prompt, target_language)


__all__ = [
    "RESEARCHER_NOTE_REMINDER_HEADING",
    "RESEARCHER_NOTE_REMINDER_TEXT",
    "RESEARCHER_NOTE_SYSTEM_RULE",
    "append_perspective_user_reminders",
    "append_previous_round_note_reminder",
    "append_response_language_reminder",
    "build_synthesis_user_prompt",
    "build_system_prompt",
    "build_user_prompt",
    "perspective_prompt_layout",
]
