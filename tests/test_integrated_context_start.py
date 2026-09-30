"""Managed pre-start budget rejects without creating a failed discussion."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from src.service.api_schemas import StartDiscussionRequest
from src.service.routers.discussions import start_discussion


def _request() -> StartDiscussionRequest:
    return StartDiscussionRequest.model_validate(
        {
            "material": "Synthetic material",
            "agents": [],
            "material_context": {
                "material_type": "document",
                "session_type": "exploration",
                "target_language": "English",
                "input_values": {
                    "main_input": "Synthetic question",
                    "research_material_context": "",
                    "additional_instructions": "",
                },
            },
            "synthesis": {"enabled": False, "api_host": None, "llm_id": None, "temperature": None},
        }
    )


@pytest.mark.parametrize(
    "known,overflow,expected_status",
    [
        (True, True, 422),
        (False, False, 503),
    ],
)
def test_managed_start_rejects_before_discussion_creation(
    known: bool,
    overflow: bool,
    expected_status: int,
) -> None:
    context = MagicMock()
    context.discussion.estimate_start_context_budget.return_value = {
        "known": known,
        "overflow": overflow,
        "estimated_input_tokens": 22_500,
        "context_window_tokens": 8_192,
        "available_input_tokens": 4_096,
        "reserved_output_tokens": 4_096,
    }
    with patch(
        "src.service.routers.discussions._managed_local_ai_preflight", return_value="gemma-4-e2b"
    ):
        with pytest.raises(HTTPException) as excinfo:
            start_discussion(_request(), context, MagicMock())
    assert excinfo.value.status_code == expected_status
    if not known:
        assert excinfo.value.error_code == "input_estimate_unavailable"
    context.discussion.start_new_discussion.assert_not_called()


def test_external_known_overflow_rejects_before_discussion_creation() -> None:
    context = MagicMock()
    context.discussion.estimate_start_context_budget.return_value = {
        "known": True,
        "overflow": True,
        "estimated_input_tokens": 21_029,
        "context_window_tokens": 12_288,
        "available_input_tokens": 8_192,
        "reserved_output_tokens": 4_096,
    }
    with patch("src.service.routers.discussions._managed_local_ai_preflight", return_value=None):
        with pytest.raises(HTTPException) as excinfo:
            start_discussion(_request(), context, MagicMock())
    assert excinfo.value.status_code == 422
    assert excinfo.value.error_code == "context_limit_exceeded"
    context.discussion.start_new_discussion.assert_not_called()


@pytest.mark.parametrize("known", [True, False])
def test_external_valid_or_unknown_estimate_keeps_start_available(known: bool) -> None:
    context = MagicMock()
    context.discussion.estimate_start_context_budget.return_value = {
        "known": known,
        "overflow": False,
        "estimated_input_tokens": 500 if known else None,
        "context_window_tokens": 12_288 if known else None,
        "available_input_tokens": 8_192 if known else None,
        "reserved_output_tokens": 4_096,
    }
    context.discussion.current_session_file_id.return_value = None
    with patch("src.service.routers.discussions._managed_local_ai_preflight", return_value=None):
        start_discussion(_request(), context, MagicMock())
    context.discussion.start_new_discussion.assert_called_once()
