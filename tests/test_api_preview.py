"""Tests for the preview router's session-aware behavior.

The preview endpoint must:

* accept an optional ``session_type`` query parameter;
* return ``session_type`` (normalized key) and ``session_label`` in the
  ``PreviewResult`` payload;
* normalize invalid session types to the service's ``DEFAULT_SESSION_TYPE``;
* run the real ``DiscussionService.build_system_prompt`` assembly so that
  ``system_prompt`` contains the session-specific guidance and the
  session label, not a template-only approximation.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api_server import app
from src.prompts.preview import PREVIEW_RESEARCHER_NOTE, build_preview_user_prompt
from src.prompts.storage import PromptRepository
from src.service.discussion import (
    DEFAULT_SESSION_TYPE,
    SESSION_TYPES,
    DiscussionService,
)
from src.service.discussion_domain import AgentResponse, DiscussionState, MaterialContext
from src.service.discussion_storage import StoredDiscussion, StoredPromptSnapshot
from src.service.token_estimator import TokenEstimatorUnavailable
from tests.router_test_support import override_context

# Directory containing the shipped session-context files. Copy it into each
# fixture so the live repository lookup in ``DiscussionService`` reads the
# actual frontmatter and bodies.
SHIPPED_SESSION_CONTEXTS = (
    Path(__file__).resolve().parent.parent / "data" / "prompts" / "session_contexts"
)


def _seed_session_contexts(target: Path) -> None:
    """Copy the shipped session-context files into ``target``."""

    target.mkdir(parents=True, exist_ok=True)
    for src in SHIPPED_SESSION_CONTEXTS.glob("*.md"):
        shutil.copy2(src, target / src.name)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def preview_repo(tmp_path: Path) -> PromptRepository:
    """Minimal in-memory prompt repository with one template and globals."""

    library_dir = tmp_path / "prompts"
    library_dir.mkdir()
    roles_dir = library_dir / "roles"
    roles_dir.mkdir()
    (roles_dir / "preview_role.poml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<prompts>
  <prompt id="preview_role" label="Preview Role">
    <role>Du bist ein Preview-Agent.</role>
    <task>Analysiere das Material.</task>
    <output-format>Fliesstext.</output-format>
  </prompt>
</prompts>""",
        encoding="utf-8",
    )
    (library_dir / "prompts_globals.poml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<prompts>
  <global id="principles" label="Grundhaltung">
    <content>Sei reflektiv.</content>
  </global>
  <global id="round_norms" label="Diskussionsnormen" scope="multi_agent">
    <content>Reagiere auf andere.</content>
  </global>
</prompts>""",
        encoding="utf-8",
    )
    return PromptRepository(base_path=library_dir)


def _build_context(preview_repo: PromptRepository) -> MagicMock:
    """A mocked ``AppContext`` with a real ``DiscussionService`` and repo.

    The discussion service is real (so ``build_system_prompt`` /
    ``_normalize_session_type`` behave as in production); everything else
    is a MagicMock because the preview endpoint only needs the prompts
    repo and the discussion service.

    ``settings`` remains a minimal ``MagicMock``, and
    ``session_context_dir`` points to a fixture directory seeded with the
    shipped session-context files.
    """
    settings = MagicMock()
    llm_manager = MagicMock()

    # Use a fixture-local session_context_dir seeded with the shipped Markdown
    # files so the live ``SessionTypeRepository`` follows the production path.
    prompt_base = Path(preview_repo.base_path)
    session_context_dir = prompt_base / "session_contexts"
    _seed_session_contexts(session_context_dir)

    discussion = DiscussionService(
        settings=settings,
        llm_manager=llm_manager,
        prompt_repo=preview_repo,
        session_context_dir=session_context_dir,
    )

    ctx = MagicMock()
    ctx.prompts = preview_repo
    ctx.discussion = discussion
    ctx.settings = settings
    ctx.llm_manager = llm_manager
    return ctx


@pytest.mark.parametrize(
    ("note_round", "included", "opted_in", "expected"),
    [
        (2, True, True, True),
        (2, True, False, False),
        (2, False, True, False),
        (1, True, True, False),
    ],
)
def test_discussion_aware_user_preview_note_reminder(
    note_round: int, included: bool, opted_in: bool, expected: bool
) -> None:
    state = DiscussionState(material="Synthetic material", round_number=note_round)
    state.add_agent_response(
        AgentResponse(
            message_id="synthetic-note",
            agent_index=0,
            agent_name="Synthetic perspective",
            theory_label="",
            color="#000000",
            text="Synthetic contribution",
        )
    )
    note_message = state.messages[-1]
    note_message.note = "Synthetic interpretation"
    note_message.include_note_in_agent_context = opted_in
    note_message.include_in_agent_context = included
    state.round_number = 3
    state.add_user_message("Current moderator input")

    prompt = build_preview_user_prompt(
        MaterialContext(target_language="English"), discussion_state=state
    )
    assert PREVIEW_RESEARCHER_NOTE not in prompt
    reminder = (
        "=== RESEARCHER NOTES REMINDER ===\n"
        "Address the included researcher notes from Round 2 where relevant to the current question."
    )
    assert (reminder in prompt) is expected
    assert ("Synthetic interpretation" in prompt) is (included and opted_in)
    if expected:
        assert prompt.index("Synthetic contribution") < prompt.index("Synthetic interpretation")
        assert prompt.index("Current moderator input") < prompt.index(reminder)
        assert prompt.index(reminder) < prompt.index("=== CURRENT RESPONSE LANGUAGE REMINDER ===")


class TestPreviewEndpointSessionType:
    def test_default_session_type_when_query_param_missing(
        self, client: TestClient, preview_repo: PromptRepository
    ):
        ctx = _build_context(preview_repo)
        with override_context(app, ctx):
            resp = client.get("/api/preview/preview_role")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["session_type"] == DEFAULT_SESSION_TYPE
        assert body["session_label"] == SESSION_TYPES[DEFAULT_SESSION_TYPE]["label"]

    def test_explicit_exploration_session(self, client: TestClient, preview_repo: PromptRepository):
        ctx = _build_context(preview_repo)
        with override_context(app, ctx):
            resp = client.get(
                "/api/preview/preview_role",
                params={"session_type": "exploration"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["session_type"] == "exploration"
        assert body["session_label"] == SESSION_TYPES["exploration"]["label"]
        # Real session-specific guidance from build_system_prompt.
        assert "=== BEHAVIOR FOR 'EXPLORATION' MODE ===" in body["system_prompt"]
        assert "=== RESEARCH TASK ===" in body["system_prompt"]
        assert (
            "=== RESEARCHER NOTES ===\n"
            "Included researcher notes provide the researcher’s interpretations and guidance for "
            "the discussion. Consider them when developing your response, distinguishing them "
            "from evidence in the source material."
        ) in body["system_prompt"]
        assert body["system_prompt"].index("=== GRUNDHALTUNG ===") < body["system_prompt"].index("=== RESEARCHER NOTES ===")
        assert body["system_prompt"].index("=== RESEARCHER NOTES ===") < body["system_prompt"].index("=== YOUR PERSPECTIVE ===")
        assert body["system_prompt"].endswith(
            "=== FINAL RESPONSE LANGUAGE REQUIREMENT ===\n"
            "Write all prose in [Preview: selected response language]. Before returning the "
            "response, verify that it contains no quotation marks, that every material-based claim "
            "is paraphrased, and that every line reference appears inside one parenthesized citation "
            "group immediately after its claim."
        )

    def test_explicit_critique_session(self, client: TestClient, preview_repo: PromptRepository):
        ctx = _build_context(preview_repo)
        with override_context(app, ctx):
            resp = client.get(
                "/api/preview/preview_role",
                params={"session_type": "critique"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["session_type"] == "critique"
        assert body["session_label"] == SESSION_TYPES["critique"]["label"]
        assert "=== BEHAVIOR FOR 'CRITIQUE' MODE ===" in body["system_prompt"]
        for instruction in (
            "Critically examine the interpretation provided as USER INPUT.",
            "Formulate counterarguments and plausible alternative readings.",
            "Identify blind spots, prior assumptions, and counter-evidence in the material.",
        ):
            assert instruction in body["system_prompt"]

    def test_preview_session_type_does_not_use_open_history_snapshot(
        self, client: TestClient, preview_repo: PromptRepository
    ):
        ctx = _build_context(preview_repo)
        ctx.discussion._current_stored = StoredDiscussion(
            id="history",
            created="",
            updated="",
            title="History",
            material="",
            initial_question="",
            prompt_snapshot=StoredPromptSnapshot(
                layout="history",
                session={"label": "History", "behavioral_guidance": "HISTORY SNAPSHOT"},
                globals=[],
                roles=[
                    {
                        "id": "preview_role",
                        "label": "History role",
                        "role": "history role",
                        "task": "history task",
                        "output_format": "history format",
                    }
                ],
            ),
        )

        with override_context(app, ctx):
            resp = client.get(
                "/api/preview/preview_role",
                params={"session_type": "critique"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["session_type"] == "critique"
        assert "=== BEHAVIOR FOR 'CRITIQUE' MODE ===" in body["system_prompt"]
        assert "HISTORY SNAPSHOT" not in body["system_prompt"]

    def test_invalid_session_type_is_rejected(
        self, client: TestClient, preview_repo: PromptRepository
    ):
        ctx = _build_context(preview_repo)
        with override_context(app, ctx):
            resp = client.get(
                "/api/preview/preview_role",
                params={"session_type": "definitely-not-real"},
            )

        assert resp.status_code == 422, resp.text
        assert "unknown session type" in resp.json()["detail"]


# System prompt reflects real assembly, not just template concatenation
class TestPreviewEndpointRenderedContent:
    def test_system_prompt_differs_between_session_types(
        self, client: TestClient, preview_repo: PromptRepository
    ):
        ctx = _build_context(preview_repo)
        with override_context(app, ctx):
            resp_exploration = client.get(
                "/api/preview/preview_role",
                params={"session_type": "exploration"},
            )
            resp_review = client.get(
                "/api/preview/preview_role",
                params={"session_type": "critique"},
            )

        assert resp_exploration.status_code == 200
        assert resp_review.status_code == 200
        rendered_exploration = resp_exploration.json()["system_prompt"]
        rendered_review = resp_review.json()["system_prompt"]

        # The real session-specific block changes the rendered prompt.
        assert rendered_exploration != rendered_review
        assert "=== BEHAVIOR FOR 'EXPLORATION' MODE ===" in rendered_exploration
        assert "=== BEHAVIOR FOR 'CRITIQUE' MODE ===" in rendered_review

    def test_system_prompt_uses_placeholder_for_research_fields(
        self, client: TestClient, preview_repo: PromptRepository
    ):

        ctx = _build_context(preview_repo)
        with override_context(app, ctx):
            resp = client.get(
                "/api/preview/preview_role",
                params={"session_type": "exploration"},
            )

        body = resp.json()
        # The preview must make clear that the actual research context is
        # not hard-coded into the rendered prompt.
        assert "[Preview: set during the discussion]" in body["system_prompt"]
        assert "[Preview: selected response language]" in body["system_prompt"]

    def test_multi_agent_includes_discussion_context(
        self, client: TestClient, preview_repo: PromptRepository
    ):
        ctx = _build_context(preview_repo)
        with override_context(app, ctx):
            resp = client.get(
                "/api/preview/preview_role",
                params={"multi_agent": "true"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "multi_agent"
        assert "=== DISCUSSION SETTING ===" in body["system_prompt"]
        assert "You are `Perspective 1`." in body["system_prompt"]
        assert "Preview: second perspective" not in body["system_prompt"]

    def test_prompt_sources_are_typed_and_in_assembly_order(
        self, client: TestClient, preview_repo: PromptRepository
    ):

        ctx = _build_context(preview_repo)
        with override_context(app, ctx):
            resp = client.get(
                "/api/preview/preview_role",
                params={"session_type": "exploration"},
            )

        body = resp.json()
        sources = body["prompt_sources"]
        assert [source["key"] for source in sources] == [
            "context",
            "globals",
            "role",
            "task",
            "output_format",
        ]
        assert "=== RESEARCH TASK ===" in sources[0]["content"]
        assert all(set(source) == {"key", "content"} for source in sources)


# Current preview contract
class TestPreviewEndpointContract:
    @pytest.mark.parametrize("multi_agent", [False, True])
    @pytest.mark.parametrize("scenario", ["continuation", "continuation_sequential"])
    def test_later_round_example_assembles_note_reminder(
        self, client: TestClient, preview_repo: PromptRepository, multi_agent: bool, scenario: str
    ):
        ctx = _build_context(preview_repo)
        with override_context(app, ctx):
            response = client.get(
                "/api/preview/preview_role",
                params={"multi_agent": multi_agent, "scenario": scenario},
            )

        assert response.status_code == 200, response.text
        prompt = response.json()["user_prompt"]
        preceding_round = re.search(r"=== ROUND (\d+) ===", prompt)
        assert preceding_round is not None
        reminder = (
            "=== RESEARCHER NOTES REMINDER ===\n"
            "Address the included researcher notes from Round "
            f"{preceding_round.group(1)} where relevant to the current question."
        )
        assert prompt.count(PREVIEW_RESEARCHER_NOTE) == 1
        assert prompt.count(reminder) == 1
        assert (
            prompt.index("[Perspective 1]:" if multi_agent else "[Perspective 3]:")
            < prompt.index(PREVIEW_RESEARCHER_NOTE)
            < prompt.index("=== CURRENT ROUND USER INPUT")
        )
        assert (
            prompt.index("[Preview: current moderator task]")
            < prompt.index(reminder)
            < prompt.index("=== CURRENT RESPONSE LANGUAGE REMINDER ===")
        )
        assert prompt.endswith(
            "=== CURRENT RESPONSE LANGUAGE REMINDER ===\n"
            "Write all prose in [Preview: selected response language]."
        )

    @pytest.mark.parametrize("multi_agent", [False, True])
    @pytest.mark.parametrize("scenario", ["first_round", "first_round_sequential"])
    def test_first_round_example_has_no_synthetic_note_or_reminder(
        self, client: TestClient, preview_repo: PromptRepository, multi_agent: bool, scenario: str
    ):
        ctx = _build_context(preview_repo)
        with override_context(app, ctx):
            response = client.get(
                "/api/preview/preview_role",
                params={"multi_agent": multi_agent, "scenario": scenario},
            )
        assert response.status_code == 200, response.text
        prompt = response.json()["user_prompt"]
        assert PREVIEW_RESEARCHER_NOTE not in prompt
        assert "=== RESEARCHER NOTES REMINDER ===" not in prompt

    def test_known_template_returns_expected_fields(
        self, client: TestClient, preview_repo: PromptRepository
    ):
        ctx = _build_context(preview_repo)
        with override_context(app, ctx):
            resp = client.get("/api/preview/preview_role")

        body = resp.json()
        assert body["template_id"] == "preview_role"
        assert body["label"] == "Preview Role"
        assert body["mode"] == "single_agent"
        assert body["char_count"] == len(body["system_prompt"]) + len(body["user_prompt"])
        assert body["estimated_tokens"] is None or body["estimated_tokens"] > 0
        assert body["tokenizer_name"] == "o200k_base"
        assert "approx_tokens" not in body
        assert "rendered_prompt" not in body
        assert "segments" not in body
        assert body["system_prompt"]
        assert "=== CURRENT ROUND USER INPUT (ROUND 1) ===" in body["user_prompt"]
        assert body["user_prompt"].endswith(
            "=== CURRENT RESPONSE LANGUAGE REMINDER ===\n"
            "Write all prose in [Preview: selected response language]."
        )
        assert body["user_prompt"].count("CURRENT RESPONSE LANGUAGE REMINDER") == 1

    def test_unavailable_tokenizer_returns_null_estimate(
        self, client: TestClient, preview_repo: PromptRepository
    ):
        ctx = _build_context(preview_repo)
        with (
            override_context(app, ctx),
            patch(
                "src.service.routers.preview.estimate_tokens",
                side_effect=TokenEstimatorUnavailable("missing"),
            ),
        ):
            resp = client.get("/api/preview/preview_role")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["estimated_tokens"] is None
        assert body["tokenizer_name"] == "o200k_base"

    def test_templates_hide_source_paths_and_globals_route_is_not_published(
        self, client: TestClient, preview_repo: PromptRepository
    ):
        ctx = _build_context(preview_repo)
        with override_context(app, ctx):
            templates = client.get("/api/preview/templates")
            openapi = client.get("/openapi.json")

        assert templates.status_code == 200, templates.text
        assert templates.json() == [{"id": "preview_role", "label": "Preview Role"}]
        assert "/api/preview/globals" not in openapi.json()["paths"]

    def test_user_preview_scenarios_show_the_actual_context_boundary(
        self, client: TestClient, preview_repo: PromptRepository
    ):
        ctx = _build_context(preview_repo)
        with override_context(app, ctx):
            first_round_sequential = client.get(
                "/api/preview/preview_role", params={"scenario": "first_round_sequential"}
            )
            continuation = client.get(
                "/api/preview/preview_role", params={"scenario": "continuation"}
            )
            sequential = client.get(
                "/api/preview/preview_role", params={"scenario": "continuation_sequential"}
            )
            multi_continuation = client.get(
                "/api/preview/preview_role",
                params={"multi_agent": True, "scenario": "continuation"},
            )
            multi_sequential = client.get(
                "/api/preview/preview_role",
                params={"multi_agent": True, "scenario": "continuation_sequential"},
            )

        assert first_round_sequential.status_code == 200
        assert "=== ROUND 1 (CURRENT ROUND) ===" in first_round_sequential.json()["user_prompt"]
        assert (
            "[Preview: earlier same-round contribution]"
            in first_round_sequential.json()["user_prompt"]
        )
        assert continuation.status_code == 200
        assert "=== ROUND 1 ===" in continuation.json()["user_prompt"]
        assert "=== ROUND 2 (CURRENT ROUND) ===" not in continuation.json()["user_prompt"]
        assert "[Preview: earlier round contribution]" in continuation.json()["user_prompt"]
        assert sequential.status_code == 200
        assert "=== ROUND 2 (CURRENT ROUND) ===" in sequential.json()["user_prompt"]
        assert "[Preview: earlier same-round contribution]" in sequential.json()["user_prompt"]
        for response in (multi_continuation, multi_sequential):
            assert response.status_code == 200
            user_prompt = response.json()["user_prompt"]
            for perspective_number in range(1, 4):
                assert f"[Perspective {perspective_number}]:" in user_prompt
                assert (
                    f"[Preview: earlier round contribution from Perspective {perspective_number}]"
                    in user_prompt
                )
        for response in (
            first_round_sequential,
            continuation,
            sequential,
            multi_continuation,
            multi_sequential,
        ):
            user_prompt = response.json()["user_prompt"]
            assert user_prompt.endswith(
                "=== CURRENT RESPONSE LANGUAGE REMINDER ===\n"
                "Write all prose in [Preview: selected response language]."
            )
            assert user_prompt.count("CURRENT RESPONSE LANGUAGE REMINDER") == 1

    def test_unknown_template_returns_404(self, client: TestClient, preview_repo: PromptRepository):
        ctx = _build_context(preview_repo)
        with override_context(app, ctx):
            resp = client.get("/api/preview/does-not-exist")

        assert resp.status_code == 404
