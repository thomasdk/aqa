"""Coverage for the fixed three-field session setup contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.prompts.session_types import (
    SESSION_INPUT_KEYS,
    SessionInputDefinition,
    SessionTypeDefinition,
)
from src.service.api_schemas import StartDiscussionRequest
from src.service.discussion_domain import MaterialContext
from src.service.discussion_prompts import (
    build_synthesis_user_prompt,
    build_system_prompt,
    build_user_prompt,
)


def test_session_type_uses_the_fixed_ordered_setup_schema() -> None:
    definition = SessionTypeDefinition(
        key="custom",
        label="Custom",
        description="Custom session type",
        body="BODY",
    )
    assert tuple(item.key for item in definition.session_inputs) == SESSION_INPUT_KEYS
    main_input = definition.input_for_key("main_input")
    assert main_input is not None
    assert main_input.required is True


def test_session_type_rejects_non_string_ui_metadata() -> None:
    with pytest.raises(ValidationError):
        SessionTypeDefinition(
            key="custom",
            label={"translations": {"en": "Custom"}},
            description="Custom session type",
            body="BODY",
        )


def test_noncanonical_setup_input_keys_are_rejected() -> None:
    with pytest.raises(ValidationError, match="session_inputs muss genau"):
        SessionTypeDefinition(
            key="custom_type",
            label="Custom",
            description="Custom schema",
            session_inputs=[
                SessionInputDefinition(
                    key="custom",
                    label="Custom",
                    prompt_heading="CUSTOM",
                )
            ],
            body="BODY",
        )


def test_removed_data_context_key_is_rejected_without_an_alias() -> None:
    canonical = SessionTypeDefinition(
        key="custom",
        label="Custom",
        description="Custom session type",
        body="BODY",
    ).session_inputs
    removed_key_inputs = [
        item.model_copy(update={"key": "data_context"})
        if item.key == "research_material_context"
        else item
        for item in canonical
    ]

    with pytest.raises(ValidationError, match="session_inputs muss genau"):
        SessionTypeDefinition(
            key="old_custom",
            label="Old custom",
            description="Uses the removed input key",
            session_inputs=removed_key_inputs,
            body="BODY",
        )


def test_session_type_rejects_reordered_or_optional_main_input() -> None:
    canonical = SessionTypeDefinition(
        key="custom",
        label="Custom",
        description="Custom session type",
        body="BODY",
    ).session_inputs

    with pytest.raises(ValidationError, match="session_inputs muss genau"):
        SessionTypeDefinition(
            key="reordered",
            label="Custom",
            description="Custom session type",
            session_inputs=list(reversed(canonical)),
            body="BODY",
        )
    optional_main_input = [
        item.model_copy(update={"required": False}) if item.key == "main_input" else item
        for item in canonical
    ]
    with pytest.raises(ValidationError, match="Nur main_input ist erforderlich"):
        SessionTypeDefinition(
            key="optional_main_input",
            label="Custom",
            description="Custom session type",
            session_inputs=optional_main_input,
            body="BODY",
        )


def test_discussion_setting_precedes_session_context() -> None:
    context = MaterialContext(
        session_type="exploration",
        material_type="interview",
        session_input_values={"main_input": "Look for contradictions."},
    )
    prompt = build_system_prompt(
        template=type(
            "Template",
            (),
            {"label": "Perspective", "role": None, "task": None, "output_format": None},
        )(),
        common_instructions="",
        material_context=context,
    )

    assert prompt is not None
    assert prompt.startswith("=== DISCUSSION SETTING ===")
    assert "qualitative research team conducting collaborative data analysis" in prompt
    assert "human user and several AI systems called `Perspectives`" in prompt
    assert prompt.index("=== DISCUSSION SETTING ===") < prompt.index("=== SESSION CONTEXT ===")


def test_start_request_has_no_duplicate_question_or_arbitrary_values() -> None:
    request = StartDiscussionRequest.model_validate(
        {
            "material": "Material",
            "agents": [],
            "material_context": {
                "material_type": "document",
                "session_type": "exploration",
                "target_language": " German ",
                "input_values": {
                    "main_input": "Analyse this.",
                    "research_material_context": "",
                    "additional_instructions": "",
                },
            },
            "synthesis": {"enabled": True, "api_host": None, "llm_id": None, "temperature": None},
        }
    )
    assert request.material_context.input_values.main_input == "Analyse this."
    assert request.material_context.target_language == "German"

    with pytest.raises(ValidationError):
        StartDiscussionRequest.model_validate(
            {
                "material": "Material",
                "question": "Duplicate task",
                "agents": [],
                "material_context": {
                    "target_language": "German",
                    "input_values": {"main_input": "Analyse this."},
                },
                "synthesis": {
                    "enabled": True,
                    "api_host": None,
                    "llm_id": None,
                    "temperature": None,
                },
            }
        )


def test_main_input_has_distinct_system_and_current_task_placements() -> None:
    marker = "MAIN_INPUT_MUST_APPEAR_ONCE"
    context = MaterialContext(
        target_language="German",
        session_input_values={"main_input": marker},
    )
    system_prompt = build_system_prompt(
        template=type(
            "Template",
            (),
            {"label": "Perspective", "role": None, "task": None, "output_format": None},
        )(),
        common_instructions="",
        material_context=context,
    )
    user_prompt = build_user_prompt("Original material", marker, context)

    assert (system_prompt or "").count(marker) == 1
    assert user_prompt.count(marker) == 1
    assert "Original material" in user_prompt
    assert "=== CURRENT ROUND USER INPUT (ROUND 1) ===" in user_prompt
    assert "[USER]" not in user_prompt
    assert user_prompt.endswith(
        "=== CURRENT RESPONSE LANGUAGE REMINDER ===\nWrite all prose in German."
    )
    assert user_prompt.count("CURRENT RESPONSE LANGUAGE REMINDER") == 1
    with pytest.raises(ValidationError):
        StartDiscussionRequest.model_validate(
            {
                "agents": [],
                "material_context": {"input_values": {"focus": "Unknown value"}},
            }
        )


def test_empty_main_input_keeps_the_user_input_section() -> None:
    context = MaterialContext(session_input_values={"main_input": ""})
    system_prompt = build_system_prompt(
        template=type(
            "Template",
            (),
            {"label": "Perspective", "role": None, "task": None, "output_format": None},
        )(),
        common_instructions="",
        material_context=context,
    )

    assert "=== RESEARCH TASK ===\nUSER INPUT:\n" in (system_prompt or "")


def test_empty_perspective_fields_are_removed_from_the_system_prompt() -> None:
    partly_empty = build_system_prompt(
        template=type(
            "Template",
            (),
            {
                "label": "Perspective",
                "role": "Role content",
                "task": "",
                "output_format": None,
            },
        )(),
        common_instructions="",
    )
    fully_empty = build_system_prompt(
        template=type(
            "Template",
            (),
            {"label": "Perspective", "role": "", "task": "", "output_format": ""},
        )(),
        common_instructions="",
    )

    assert "=== YOUR PERSPECTIVE ===\nROLE:\nRole content" in (partly_empty or "")
    assert "UNIQUE PERSPECTIVE TASK:" not in (partly_empty or "")
    assert "OUTPUT FORMAT:" not in (partly_empty or "")
    assert "=== YOUR PERSPECTIVE ===" not in (fully_empty or "")


def test_target_language_appears_once_at_the_end_of_each_model_prompt() -> None:
    context = MaterialContext(
        target_language="German",
        session_input_values={"main_input": "Analyse this."},
    )
    system_prompt = build_system_prompt(
        template=type(
            "Template",
            (),
            {"label": "Perspective", "role": None, "task": None, "output_format": None},
        )(),
        common_instructions="",
        material_context=context,
    )
    assert (system_prompt or "").endswith(
        "Write all prose in German. Before returning the response, verify that it contains no "
        "quotation marks, that every material-based claim is paraphrased, and that every line "
        "reference appears inside one parenthesized citation group immediately after its claim."
    )
    synthesis_prompt = build_synthesis_user_prompt(
        session_label="Open Exploration",
        session_description="",
        material_type_label="Document / Text",
        target_language="German",
        session_inputs=[],
        participants=[],
        question="Analyse this.",
        contributions=[],
    )
    assert synthesis_prompt.endswith(
        "=== CURRENT RESPONSE LANGUAGE REMINDER ===\nWrite all prose in German."
    )
    assert synthesis_prompt.count("CURRENT RESPONSE LANGUAGE REMINDER") == 1
    assert "FINAL RESPONSE LANGUAGE REQUIREMENT" not in synthesis_prompt


def test_empty_target_language_never_infers_a_language_from_material_or_contributions() -> None:
    context = MaterialContext(session_input_values={"main_input": "Analyse this."})
    system_prompt = build_system_prompt(
        template=type(
            "Template",
            (),
            {"label": "Perspective", "role": None, "task": None, "output_format": None},
        )(),
        common_instructions="",
        material_context=context,
    )
    assert "dominant language" not in (system_prompt or "")
    assert "FINAL RESPONSE LANGUAGE REQUIREMENT" not in (system_prompt or "")
    synthesis_prompt = build_synthesis_user_prompt(
        session_label="Open Exploration",
        session_description="",
        material_type_label="Document / Text",
        session_inputs=[],
        participants=[],
        question="Analyse this.",
        contributions=[],
    )
    assert "dominant language" not in synthesis_prompt
    assert "FINAL RESPONSE LANGUAGE REQUIREMENT" not in synthesis_prompt
    assert "CURRENT RESPONSE LANGUAGE REMINDER" not in synthesis_prompt


@pytest.mark.parametrize("value", ["", "   "])
def test_start_request_requires_a_nonempty_trimmed_target_language(value: str) -> None:
    with pytest.raises(ValidationError, match="target_language"):
        StartDiscussionRequest.model_validate(
            {
                "agents": [],
                "material_context": {
                    "target_language": value,
                    "input_values": {"main_input": "Analyse this."},
                },
                "synthesis": {
                    "enabled": False,
                    "api_host": None,
                    "llm_id": None,
                    "temperature": None,
                },
            }
        )
