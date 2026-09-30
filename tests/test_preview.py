"""Tests for the prompt-preview tool (CLI and rendering)."""

import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.prompts import PromptRepository
from src.prompts.preview import _build_preview
from src.prompts.preview import main as preview_main
from src.service.discussion import (
    SESSION_TYPES,
    DiscussionService,
    MaterialContext,
)

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


_PREVIEW_PLACEHOLDER = "[Preview: set during the discussion]"


def _make_material_context(
    session_type: str, service: "DiscussionService | None" = None
) -> MaterialContext:
    """Create a deterministic ``MaterialContext`` for preview tests.

    When a ``DiscussionService`` is provided, normalize the session type
    through its ``_normalize_session_type`` method.
    """

    if service is not None:
        normalized = service._normalize_session_type(session_type)
    else:
        normalized = session_type

    return MaterialContext(
        material_type="document",
        session_type=normalized,
        session_input_values={
            "research_material_context": _PREVIEW_PLACEHOLDER,
            "main_input": _PREVIEW_PLACEHOLDER,
            "additional_instructions": _PREVIEW_PLACEHOLDER,
        },
    )


@pytest.fixture()
def preview_repo(tmp_path: Path) -> PromptRepository:
    """Create a ``PromptRepository`` with files for preview tests.

    Copy session-context files from the shipped
    ``data/prompts/session_contexts`` directory into the test path so the
    live repository lookup in ``DiscussionService`` reads the real
    frontmatter and bodies.
    """

    library_dir = tmp_path / "prompts"
    library_dir.mkdir()

    roles_dir = library_dir / "roles"
    roles_dir.mkdir()
    (roles_dir / "test_role.poml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<prompts>
  <prompt id="test_role" label="Test-Rolle">
    <role>Du bist ein Test-Agent.</role>
    <task>Analysiere das Material.</task>
    <output-format>Fliesstext, max. 100 Woerter.</output-format>
  </prompt>
</prompts>""",
        encoding="utf-8",
    )

    (library_dir / "prompts_globals.poml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<prompts>
  <global id="principles" label="Grundhaltung">
    <content>Sei reflektiv und zitiere Material.</content>
  </global>
  <global id="round_norms" label="Diskussionsnormen" scope="multi_agent">
    <content>Reagiere auf andere Teilnehmer.</content>
  </global>
</prompts>""",
        encoding="utf-8",
    )

    # Seed shipped session contexts into the test directory so the CLI and
    # service paths find them.
    _seed_session_contexts(library_dir / "session_contexts")

    return PromptRepository(base_path=library_dir)


class TestBuildPreview:
    def test_single_agent_contains_role_and_task(self, preview_repo: PromptRepository):
        template = preview_repo.get_template("test_role")
        assert template is not None
        common = preview_repo.get_common_instructions(multi_agent=False)
        result = _build_preview(template, common, multi_agent=False)

        assert "ROLE:" in result
        assert "Du bist ein Test-Agent." in result
        assert "UNIQUE PERSPECTIVE TASK:" in result
        assert "\nTASK:\n" not in result
        assert "OUTPUT FORMAT:" in result

    def test_single_agent_excludes_multi_agent_norms(self, preview_repo: PromptRepository):
        template = preview_repo.get_template("test_role")
        assert template is not None
        common = preview_repo.get_common_instructions(multi_agent=False)
        result = _build_preview(template, common, multi_agent=False)

        assert "DISCUSSION CONTEXT" not in result
        assert "Reagiere auf andere Teilnehmer" not in result

    def test_multi_agent_includes_discussion_context(self, preview_repo: PromptRepository):
        template = preview_repo.get_template("test_role")
        assert template is not None
        common = preview_repo.get_common_instructions(multi_agent=True)
        result = _build_preview(template, common, multi_agent=True, total_agents=3)

        assert "DISCUSSION CONTEXT" in result
        assert "perspective 1 of 3" in result
        assert "Reagiere auf andere Teilnehmer" in result

    def test_global_principles_always_present(self, preview_repo: PromptRepository):
        template = preview_repo.get_template("test_role")
        assert template is not None
        common = preview_repo.get_common_instructions(multi_agent=False)
        result = _build_preview(template, common, multi_agent=False)

        assert "Sei reflektiv und zitiere Material." in result


class TestPreviewCLI:
    def test_list_mode_returns_zero(self, preview_repo: PromptRepository):
        exit_code = preview_main(["--path", str(preview_repo.base_path)])
        assert exit_code == 0

    def test_render_known_template(self, preview_repo: PromptRepository):
        exit_code = preview_main(["--path", str(preview_repo.base_path), "test_role"])
        assert exit_code == 0

    def test_render_unknown_template_returns_one(self, preview_repo: PromptRepository):
        exit_code = preview_main(["--path", str(preview_repo.base_path), "nonexistent"])
        assert exit_code == 1

    def test_globals_flag(self, preview_repo: PromptRepository):
        exit_code = preview_main(["--path", str(preview_repo.base_path), "--globals"])
        assert exit_code == 0

    def test_all_flag(self, preview_repo: PromptRepository):
        exit_code = preview_main(["--path", str(preview_repo.base_path), "--all"])
        assert exit_code == 0

    def test_multi_agent_flag(self, preview_repo: PromptRepository):
        exit_code = preview_main(
            ["--path", str(preview_repo.base_path), "--multi-agent", "test_role"]
        )
        assert exit_code == 0


class TestBuildPreviewSessionAware:
    def _build_service(self, preview_repo: PromptRepository) -> DiscussionService:
        """Build a ``DiscussionService`` with real session-context files.

        ``settings`` remains a minimal ``MagicMock`` stub. The live
        ``SessionTypeRepository`` receives a directory seeded with the shipped
        session-context files so session-specific bodies can be resolved.
        """

        settings = MagicMock()
        llm_manager = MagicMock()
        session_context_dir = Path(preview_repo.base_path) / "session_contexts"
        return DiscussionService(
            settings=settings,
            llm_manager=llm_manager,
            prompt_repo=preview_repo,
            session_context_dir=session_context_dir,
        )

    def test_rendered_prompt_contains_session_specific_guidance_for_exploration(
        self, preview_repo: PromptRepository
    ):
        from src.prompts.preview import build_preview_rendered

        template = preview_repo.get_template("test_role")
        assert template is not None
        service = self._build_service(preview_repo)

        rendered, _segments = build_preview_rendered(
            service=service,
            template=template,
            material_context=_make_material_context("exploration", service=service),
            multi_agent=False,
        )

        # The session-specific guidance from the service must be visible.
        assert "BEHAVIOR FOR 'EXPLORATION' MODE" in rendered
        assert "Use USER INPUT as your starting point" in rendered
        assert "BEHAVIOR FOR 'CRITIQUE' MODE" not in rendered

    def test_preview_context_includes_final_language_requirement(
        self, preview_repo: PromptRepository
    ):
        from src.prompts.preview import _build_material_context_for_preview, build_preview_rendered

        template = preview_repo.get_template("test_role")
        assert template is not None
        service = self._build_service(preview_repo)

        rendered, _segments = build_preview_rendered(
            service=service,
            template=template,
            material_context=_build_material_context_for_preview("exploration", service=service),
        )

        assert rendered.endswith(
            "=== FINAL RESPONSE LANGUAGE REQUIREMENT ===\n"
            "Write all prose in [Preview: selected response language]. Before returning the "
            "response, verify that it contains no quotation marks, that every material-based claim "
            "is paraphrased, and that every line reference appears inside one parenthesized citation "
            "group immediately after its claim."
        )

    def test_rendered_prompt_contains_session_specific_guidance_for_review(
        self, preview_repo: PromptRepository
    ):
        from src.prompts.preview import build_preview_rendered

        template = preview_repo.get_template("test_role")
        assert template is not None
        service = self._build_service(preview_repo)

        rendered, _segments = build_preview_rendered(
            service=service,
            template=template,
            material_context=_make_material_context("critique", service=service),
            multi_agent=False,
        )

        assert "BEHAVIOR FOR 'CRITIQUE' MODE" in rendered
        assert "Critically examine the interpretation provided" in rendered
        assert "BEHAVIOR FOR 'EXPLORATION' MODE" not in rendered

    def test_session_specific_guidance_differs_between_session_types(
        self, preview_repo: PromptRepository
    ):
        from src.prompts.preview import build_preview_rendered

        template = preview_repo.get_template("test_role")
        assert template is not None
        service = self._build_service(preview_repo)

        rendered_exploration, _ = build_preview_rendered(
            service=service,
            template=template,
            material_context=_make_material_context("exploration", service=service),
            multi_agent=False,
        )
        rendered_review, _ = build_preview_rendered(
            service=service,
            template=template,
            material_context=_make_material_context("critique", service=service),
            multi_agent=False,
        )

        assert rendered_exploration != rendered_review
        assert "BEHAVIOR FOR 'EXPLORATION' MODE" in rendered_exploration
        assert "BEHAVIOR FOR 'CRITIQUE' MODE" in rendered_review

    def test_session_label_and_context_included_in_render(self, preview_repo: PromptRepository):
        from src.prompts.preview import build_preview_rendered

        template = preview_repo.get_template("test_role")
        assert template is not None
        service = self._build_service(preview_repo)

        rendered, segments = build_preview_rendered(
            service=service,
            template=template,
            material_context=_make_material_context("exploration", service=service),
            multi_agent=False,
        )

        expected_label = SESSION_TYPES["exploration"]["label"]
        assert f"SESSION TYPE: {expected_label}" in rendered
        assert "RESEARCH TASK" in rendered
        assert _PREVIEW_PLACEHOLDER in rendered
        assert "context" in segments
        assert "globals" in segments
        assert "role" in segments

    def test_invalid_session_type_is_rejected(self, preview_repo: PromptRepository):
        template = preview_repo.get_template("test_role")
        assert template is not None
        service = self._build_service(preview_repo)

        with pytest.raises(ValueError, match="unknown session type"):
            _make_material_context("not-a-real-session", service=service)

    def test_multi_agent_renders_discussion_context(self, preview_repo: PromptRepository):
        from src.prompts.preview import build_preview_rendered

        template = preview_repo.get_template("test_role")
        assert template is not None
        service = self._build_service(preview_repo)

        rendered, _segments = build_preview_rendered(
            service=service,
            template=template,
            material_context=_make_material_context("exploration", service=service),
            multi_agent=True,
        )

        assert "=== DISCUSSION SETTING ===" in rendered
        assert "You are `Perspective 1`." in rendered
        assert "Reagiere auf andere Teilnehmer" in rendered
        assert "[Preview: second perspective]" not in rendered
        assert "[Vorschau: zweite Perspektive]" not in rendered


class TestBuildPreviewDirectCall:
    def test_build_preview_direct_call_returns_text(self, preview_repo: PromptRepository):
        template = preview_repo.get_template("test_role")
        assert template is not None
        common = preview_repo.get_common_instructions(multi_agent=False)
        result = _build_preview(template, common, multi_agent=False)
        assert "ROLE:" in result
        assert "Du bist ein Test-Agent." in result


class TestPreviewCLISessionType:
    def test_cli_session_type_flag_is_accepted(
        self, preview_repo: PromptRepository, capsys: pytest.CaptureFixture
    ):
        exit_code = preview_main(
            [
                "--path",
                str(preview_repo.base_path),
                "--session-type",
                "critique",
                "test_role",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0, captured.out
        assert "BEHAVIOR FOR 'CRITIQUE' MODE" in captured.out

    def test_cli_invalid_session_type_is_rejected(
        self, preview_repo: PromptRepository, capsys: pytest.CaptureFixture
    ):
        exit_code = preview_main(
            [
                "--path",
                str(preview_repo.base_path),
                "--session-type",
                "totally-bogus",
                "test_role",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "unknown session type" in captured.err


class TestPreviewCLIShippedRoles:
    def test_cli_renders_shipped_role_with_default_session(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ):

        shipped_base = Path(__file__).resolve().parent.parent / "data" / "prompts"
        # Copy into a temporary directory so the test uses shipped session
        # contexts and remains independent of mutable application data.
        scratch = tmp_path / "shipped"
        shutil.copytree(shipped_base, scratch)
        # ``--path`` points to the prompt directory; ``skepticism`` is the
        # template ID to render.
        exit_code = preview_main(["--path", str(scratch), "skepticism"])
        captured = capsys.readouterr()
        assert exit_code == 0, captured.out
        assert "BEHAVIOR FOR 'EXPLORATION' MODE" in captured.out
        assert "Use USER INPUT as your starting point" in captured.out
        assert "Session: Exploration" in captured.out

    def test_cli_renders_shipped_role_with_explicit_session_type(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ):

        shipped_base = Path(__file__).resolve().parent.parent / "data" / "prompts"
        scratch = tmp_path / "shipped"
        shutil.copytree(shipped_base, scratch)
        exit_code = preview_main(
            [
                "--path",
                str(scratch),
                "--session-type",
                "critique",
                "skepticism",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0, captured.out
        # Review guidance must appear; exploration guidance must not.
        assert "BEHAVIOR FOR 'CRITIQUE' MODE" in captured.out
        assert "BEHAVIOR FOR 'EXPLORATION' MODE" not in captured.out
        # The label shows the live value, not a static snapshot.
        assert "Session: Critique" in captured.out

    def test_cli_renders_shipped_role_multi_agent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ):

        shipped_base = Path(__file__).resolve().parent.parent / "data" / "prompts"
        scratch = tmp_path / "shipped"
        shutil.copytree(shipped_base, scratch)
        exit_code = preview_main(["--path", str(scratch), "--multi-agent", "skepticism"])
        captured = capsys.readouterr()
        assert exit_code == 0, captured.out
        assert "Multi-agent (3 perspectives)" in captured.out
        assert "=== DISCUSSION SETTING ===" in captured.out
        assert "You are `Perspective 1`." in captured.out

    def test_cli_renders_all_shipped_templates(self, tmp_path: Path, capsys: pytest.CaptureFixture):

        shipped_base = Path(__file__).resolve().parent.parent / "data" / "prompts"
        scratch = tmp_path / "shipped"
        shutil.copytree(shipped_base, scratch)
        exit_code = preview_main(["--all", str(scratch)])
        captured = capsys.readouterr()
        assert exit_code == 0, captured.out
        assert "skepticism" in captured.out
        assert "conceptualization" in captured.out


class TestSessionLabelConsistency:
    def test_session_label_matches_live_repository_for_known_types(
        self, preview_repo: PromptRepository
    ):
        settings = MagicMock()
        llm_manager = MagicMock()
        session_context_dir = Path(preview_repo.base_path) / "session_contexts"
        service = DiscussionService(
            settings=settings,
            llm_manager=llm_manager,
            prompt_repo=preview_repo,
            session_context_dir=session_context_dir,
        )

        for session_key, info in SESSION_TYPES.items():
            context = MaterialContext(
                material_type="document",
                session_type=session_key,
                session_input_values={"main_input": _PREVIEW_PLACEHOLDER},
            )
            live_definition = service.session_type_repo.get(session_key)
            assert live_definition is not None, session_key
            assert context.session_label == live_definition.label == info["label"]

    def test_session_label_reflects_user_added_session_type(self, preview_repo: PromptRepository):

        from src.prompts.session_types import (
            SessionTypeDefinition,
            SessionTypeRepository,
        )

        session_context_dir = Path(preview_repo.base_path) / "session_contexts"
        user_repo = SessionTypeRepository(base_path=session_context_dir)
        custom = SessionTypeDefinition(
            key="custom_smoke",
            label="Eigener Smoke-Test-Session-Typ",
            description="Temporaerer Test-Typ fuer Live-Repository-Lookup.",
            default_agent_prompt_ids=[],
            body="- Content does not matter.",
        )
        user_repo.create(custom)
        try:
            settings = MagicMock()
            llm_manager = MagicMock()
            service = DiscussionService(
                settings=settings,
                llm_manager=llm_manager,
                prompt_repo=preview_repo,
                session_context_dir=session_context_dir,
            )
            # The snapshot omits the type; the live repository contains it.
            assert "custom_smoke" not in SESSION_TYPES
            live = service.session_type_repo.get("custom_smoke")
            assert live is not None
            assert live.label == "Eigener Smoke-Test-Session-Typ"
        finally:
            # Keep the test idempotent.
            (session_context_dir / "custom_smoke.md").unlink(missing_ok=True)

    def test_print_preview_uses_live_label_for_user_added_session(
        self, preview_repo: PromptRepository, capsys: pytest.CaptureFixture
    ):

        from src.prompts.session_types import (
            SessionTypeDefinition,
            SessionTypeRepository,
        )

        session_context_dir = Path(preview_repo.base_path) / "session_contexts"
        user_repo = SessionTypeRepository(base_path=session_context_dir)
        custom = SessionTypeDefinition(
            key="custom_smoke",
            label="Eigener Smoke-Test-Session-Typ",
            description="Temporaerer Test-Typ fuer Live-Repository-Lookup.",
            default_agent_prompt_ids=[],
            body="- Content does not matter.",
        )
        user_repo.create(custom)
        try:
            exit_code = preview_main(
                [
                    "--path",
                    str(preview_repo.base_path),
                    "--session-type",
                    "custom_smoke",
                    "test_role",
                ]
            )
            captured = capsys.readouterr()
            assert exit_code == 0, captured.out
            # The live repository label appears; the static snapshot omits
            # the user-added type.
            assert "Session: Eigener Smoke-Test-Session-Typ" in captured.out
            assert "BEHAVIOR FOR 'EIGENER SMOKE-TEST-SESSION-TYP' MODE" in captured.out
        finally:
            (session_context_dir / "custom_smoke.md").unlink(missing_ok=True)
