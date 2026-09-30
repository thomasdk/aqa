"""Tests for the Markdown export endpoint."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.prompts.storage import PromptRepository
from src.service.context import AppContext
from src.service.discussion import DiscussionService
from src.service.discussion_storage import StoredDiscussion
from tests.router_test_support import override_context

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    from src.api_server import app

    return TestClient(app)


@pytest.fixture
def discussion_context(tmp_path: Path) -> AppContext:
    """Build an isolated real discussion service without the app bootstrap."""
    settings = Settings()
    prompts = PromptRepository(base_path=PROJECT_ROOT / "data" / "prompts")
    discussion = DiscussionService(
        settings=settings,
        llm_manager=MagicMock(),
        prompt_repo=prompts,
        storage_dir=tmp_path / "conversations",
    )
    return AppContext(
        settings=settings,
        llm_manager=discussion.llm_manager,
        prompts=prompts,
        discussion=discussion,
    )


@pytest.fixture
def discussion_with_messages(discussion_context: AppContext):
    """Prepare an active stored discussion for export."""
    from src.api_server import app

    context = discussion_context
    context.discussion._current_stored = StoredDiscussion(
        id="test-export-id",
        created="2025-07-11T10:00:00",
        updated="2025-07-11T10:00:00",
        title="Test-Diskussion",
        material="Testmaterial",
        initial_question="Was fällt auf?",
    )
    context.discussion.state.messages = []
    with override_context(app, context):
        yield context
    # Cleanup
    context.discussion._current_stored = None


class TestExportMarkdown:
    def test_export_returns_markdown_not_json(self, client, discussion_with_messages):
        resp = client.get("/api/discussions/export")
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers.get("content-type", "")
        content = resp.text
        # Markdown header — would not appear in JSON
        assert "# Test-Diskussion" in content
        # Must not be JSON
        assert not content.strip().startswith("{")

    def test_export_returns_400_without_discussion(self, client, discussion_context):
        from src.api_server import app

        context = discussion_context
        context.discussion._current_stored = None
        with override_context(app, context):
            resp = client.get("/api/discussions/export")
        assert resp.status_code == 400

    def test_export_content_disposition_has_md_filename(self, client, discussion_with_messages):
        resp = client.get("/api/discussions/export")
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert ".md" in cd
        assert "Test-Diskussion" in cd or "diskussion" in cd

    def test_export_english_returns_english_shell(self, client, discussion_with_messages):
        resp = client.get("/api/discussions/export?locale=en")

        assert resp.status_code == 200
        assert "**Created:** 07/11/2025 10:00" in resp.text
        assert "**Rounds:** 0" in resp.text
        assert "## Analysis context" in resp.text
        assert "## Discussion transcript" in resp.text
        # Authored data is untouched by export localization.
        assert "Testmaterial" in resp.text


def test_get_markdown_syncs_rounds(discussion_with_messages):
    from src.service.discussion import DiscussionMessage

    context = discussion_with_messages
    # Simulate a user message in state that hasn't been synced
    context.discussion.state.messages = [
        DiscussionMessage(
            id="msg-test-1",
            role="user",
            content="Testfrage",
            round_number=1,
        ),
    ]
    md = context.discussion.get_markdown()
    assert md is not None
    assert "Testfrage" in md
    assert "### Runde 1" in md


@pytest.fixture
def discussion_with_line_numbers(discussion_context: AppContext):
    """Sets up a discussion with numbered material for export testing."""
    from src.api_server import app
    from src.service.discussion import add_line_numbers_to_material

    context = discussion_context
    numbered = add_line_numbers_to_material("Testmaterial Satz 1. Satz 2.\n\nZeile 3")
    context.discussion._current_stored = StoredDiscussion(
        id="test-ln-export",
        created="2025-07-11T10:00:00",
        updated="2025-07-11T10:00:00",
        title="LN Export Test",
        material=numbered,
        initial_question="Was faellt auf?",
    )
    context.discussion.state.messages = []
    with override_context(app, context):
        yield context
    context.discussion._current_stored = None


def test_export_contains_line_numbers(client, discussion_with_line_numbers):
    resp = client.get("/api/discussions/export")
    assert resp.status_code == 200
    assert "Z0001: Testmaterial Satz 1. Satz 2." in resp.text
    assert "Z0002: Zeile 3" in resp.text
