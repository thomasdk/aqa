"""Tests for prompt-configuration endpoints.

Covers the secure backend CRUD/edit APIs for:

* file-backed session types (``/api/prompts/session-types``), and
* existing global prompt blocks (``/api/prompts/globals``)

both with the additional requirement that successful mutations take effect
in discussion and prompt preview without server restart, by routing through
public reload façades on the live ``DiscussionService`` and the underlying
``PromptRepository`` / ``SessionTypeRepository``.

These tests use a fully mocked ``AppContext``; filesystem
side-effects are real and scoped to ``tmp_path`` and only touch sibling
``prompts/`` and ``session_contexts/`` trees.

The fixtures mirror the conventions established in
``tests/test_api_roles.py`` and ``tests/test_api_preview.py``: a real
``PromptRepository`` and ``SessionTypeRepository`` rooted at a temp path,
and a real ``DiscussionService`` (so the public reload façades exercise the
real code path) with the rest of the collaborators mocked.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api_server import app
from src.prompts.session_types import (
    SessionTypeRepository,
)
from src.prompts.storage import PromptRepository
from src.service.discussion import DiscussionService
from tests.router_test_support import override_context

# Directory containing the shipped session-context files. Copy it into each
# fixture so the live repository lookup in ``DiscussionService`` reads the
# actual frontmatter and bodies.
SHIPPED_SESSION_CONTEXTS = (
    Path(__file__).resolve().parent.parent / "data" / "prompts" / "session_contexts"
)


# Directory containing the shipped global POML file. Copy it into each
# fixture so the live ``PromptRepository`` reads the actual global blocks,
# especially ``prompts_globals.poml``.
SHIPPED_GLOBALS_POML = (
    Path(__file__).resolve().parent.parent / "data" / "prompts" / "prompts_globals.poml"
)

SHIPPED_DEFAULT_SESSION_CONTEXTS = (
    Path(__file__).resolve().parent.parent / "data" / "prompt_defaults" / "session_contexts"
)

SHIPPED_DEFAULT_GLOBALS_POML = (
    Path(__file__).resolve().parent.parent / "data" / "prompt_defaults" / "prompts_globals.poml"
)


def _seed_session_contexts(target: Path) -> None:
    """Copy the shipped session-context files into ``target``."""

    target.mkdir(parents=True, exist_ok=True)
    for src in SHIPPED_SESSION_CONTEXTS.glob("*.md"):
        shutil.copy2(src, target / src.name)


def _seed_globals_poml(target: Path) -> None:
    """Copy the shipped ``prompts_globals.poml`` into ``target``."""

    shutil.copy2(SHIPPED_GLOBALS_POML, target / "prompts_globals.poml")


def _seed_prompt_defaults(target: Path) -> None:
    """Seed the shipped defaults beside the configured prompt library."""

    session_target = target / "prompt_defaults" / "session_contexts"
    session_target.mkdir(parents=True, exist_ok=True)
    for src in SHIPPED_DEFAULT_SESSION_CONTEXTS.glob("*.md"):
        shutil.copy2(src, session_target / src.name)
    shutil.copy2(
        SHIPPED_DEFAULT_GLOBALS_POML,
        target / "prompt_defaults" / "prompts_globals.poml",
    )


def _build_layout(
    tmp_path: Path,
    *,
    shipped_active_roles: dict[str, str] | None = None,
    extra_active_roles: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    """Create ``tmp/prompts`` with roles + globals and ``tmp/session_contexts``.

    Returns ``(prompts_dir, session_contexts_dir)``.
    """

    prompts_dir = tmp_path / "prompts"
    roles_dir = prompts_dir / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)

    for role_id, content in (shipped_active_roles or {}).items():
        (roles_dir / f"{role_id}.poml").write_text(content, encoding="utf-8")
    for role_id, content in (extra_active_roles or {}).items():
        (roles_dir / f"{role_id}.poml").write_text(content, encoding="utf-8")

    _seed_globals_poml(prompts_dir)
    _seed_prompt_defaults(tmp_path)

    session_contexts_dir = tmp_path / "session_contexts"
    _seed_session_contexts(session_contexts_dir)

    return prompts_dir, session_contexts_dir


def _build_context(
    prompts_dir: Path,
    session_contexts_dir: Path,
    *,
    storage_dir: Path | None = None,
) -> MagicMock:
    """Build a mocked AppContext wired to a real ``DiscussionService``.

    The prompt repository, the session type repository (transitively
    created by the real ``DiscussionService``) and the discussion service
    itself are real so the public reload façades exercise real code.
    Every other collaborator is a ``MagicMock``. The live configuration reload
    method is replaced with a ``MagicMock`` so tests can assert on it without
    bypassing it.
    """

    prompt_repo = PromptRepository(base_path=prompts_dir)

    settings = MagicMock()
    settings.prompt_library_path = str(prompts_dir)
    llm_manager = MagicMock()

    if storage_dir is None:
        storage_dir = prompts_dir.parent / "_disc_storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    discussion = DiscussionService(
        settings=settings,
        llm_manager=llm_manager,
        prompt_repo=prompt_repo,
        storage_dir=storage_dir,
        session_context_dir=session_contexts_dir,
    )
    discussion.reload_session_configuration = MagicMock(
        wraps=discussion.reload_session_configuration
    )

    ctx = MagicMock()
    ctx.prompts = prompt_repo
    ctx.discussion = discussion
    ctx.settings = settings
    ctx.llm_manager = llm_manager
    return ctx


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestPromptDirectoryReveal:
    @pytest.mark.parametrize(
        ("endpoint", "expected_leaf"),
        [
            ("/api/prompts/session-types/reveal-directory", "session_contexts"),
            ("/api/prompts/globals/reveal-directory", "prompts"),
        ],
    )
    @pytest.mark.parametrize(
        ("platform", "expected_command"),
        [("darwin", "open"), ("win32", "explorer"), ("linux", "xdg-open")],
    )
    def test_opens_directory_with_platform_command(
        self,
        client: TestClient,
        tmp_path: Path,
        endpoint: str,
        expected_leaf: str,
        platform: str,
        expected_command: str,
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run") as run_mock,
            patch("src.service.routers.prompt_config.sys") as sys_mock,
        ):
            sys_mock.platform = platform
            resp = client.post(endpoint)

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ok"}
        assert str(prompts_dir) not in resp.text
        args, kwargs = run_mock.call_args
        assert args[0][0] == expected_command
        assert Path(args[0][1]).name == expected_leaf
        assert kwargs["shell"] is False
        assert kwargs["check"] is False
        assert kwargs["timeout"] == 5
        assert kwargs["stdout"] is __import__("subprocess").DEVNULL
        assert kwargs["stderr"] is __import__("subprocess").DEVNULL

    @pytest.mark.parametrize(
        "endpoint",
        [
            "/api/prompts/session-types/reveal-directory",
            "/api/prompts/globals/reveal-directory",
        ],
    )
    def test_rejects_missing_directory_without_launching(
        self, client: TestClient, tmp_path: Path, endpoint: str
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        if "session-types" in endpoint:
            shutil.rmtree(sc_dir)
        else:
            shutil.rmtree(prompts_dir)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run") as run_mock,
        ):
            resp = client.post(endpoint)

        assert resp.status_code == 404, resp.text
        assert str(tmp_path) not in resp.text
        run_mock.assert_not_called()

    def test_rejects_session_directory_outside_prompt_data_root_without_launching(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        outside = tmp_path.parent / f"{tmp_path.name}-outside-session-contexts"
        outside.mkdir()
        shutil.rmtree(sc_dir)
        sc_dir.symlink_to(outside, target_is_directory=True)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run") as run_mock,
        ):
            resp = client.post("/api/prompts/session-types/reveal-directory")

        assert resp.status_code == 404, resp.text
        assert str(outside) not in resp.text
        run_mock.assert_not_called()

    @pytest.mark.parametrize(
        "endpoint",
        [
            "/api/prompts/session-types/reveal-directory",
            "/api/prompts/globals/reveal-directory",
        ],
    )
    @pytest.mark.parametrize(
        "failure",
        [OSError("launch failure"), __import__("subprocess").TimeoutExpired("open", 5)],
    )
    def test_launch_failure_returns_path_free_502(
        self, client: TestClient, tmp_path: Path, endpoint: str, failure: Exception
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run", side_effect=failure),
        ):
            resp = client.post(endpoint)

        assert resp.status_code == 502, resp.text
        assert "launch failure" not in resp.text
        assert str(prompts_dir) not in resp.text

    @pytest.mark.parametrize(
        "endpoint",
        [
            "/api/prompts/session-types/reveal-directory",
            "/api/prompts/globals/reveal-directory",
        ],
    )
    def test_nonzero_launch_status_returns_path_free_502(
        self, client: TestClient, tmp_path: Path, endpoint: str
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        completed = __import__("subprocess").CompletedProcess(["open"], returncode=1)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run", return_value=completed),
        ):
            resp = client.post(endpoint)

        assert resp.status_code == 502, resp.text
        assert str(prompts_dir) not in resp.text


class TestSessionTypeList:
    def test_list_returns_editor_relevant_fields(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/session-types")

        assert resp.status_code == 200, resp.text
        by_key = {item["key"]: item for item in resp.json()}
        assert "exploration" in by_key
        entry = by_key["exploration"]
        for field in (
            "key",
            "label",
            "description",
            "default_agent_prompt_ids",
            "include_unchanged_research_material_context_in_prompt",
            "body",
            "inputs",
        ):
            assert field in entry, f"Missing field: {field}"
        assert entry["key"] == "exploration"
        assert entry["label"] == "Exploration"
        assert "label_key" not in entry
        assert "description_key" not in entry
        assert isinstance(entry["default_agent_prompt_ids"], list)
        assert "skepticism" in entry["default_agent_prompt_ids"]
        assert entry["include_unchanged_research_material_context_in_prompt"] is False
        assert entry["body"].startswith("- Use USER INPUT as your starting point.")

    def test_shipped_metadata_stays_verbatim_when_the_body_changes(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        active_path = sc_dir / "exploration.md"
        active_path.write_text(
            active_path.read_text(encoding="utf-8").replace(
                "- Use USER INPUT as your starting point.", "- EDITED BODY"
            ),
            encoding="utf-8",
        )
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            entry = next(
                item
                for item in client.get("/api/prompts/session-types").json()
                if item["key"] == "exploration"
            )

        assert entry["origin"] == "shipped_modified"
        assert entry["label"] == "Exploration"
        assert "label_key" not in entry
        assert "description_key" not in entry


class TestSessionTypeCreate:
    def test_create_writes_file_and_returns_full_definition(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        payload = {
            "key": "neuer_modus",
            "label": "Neuer Modus",
            "description": "Test",
            "default_agent_prompt_ids": ["rt_skeptiker"],
            "include_unchanged_research_material_context_in_prompt": True,
            "body": "BODY für neuen Modus",
        }

        with override_context(app, ctx):
            resp = client.post("/api/prompts/session-types", json=payload)

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["key"] == "neuer_modus"
        assert body["label"] == "Neuer Modus"
        assert (sc_dir / "neuer_modus.md").is_file()
        # Re-read via the live session_type_repo to confirm the file is valid.
        repo = SessionTypeRepository(base_path=sc_dir)
        loaded = repo.get("neuer_modus")
        assert loaded is not None
        assert loaded.label == "Neuer Modus"
        assert loaded.body == "BODY für neuen Modus"
        assert loaded.input_for_key("main_input") is not None
        assert loaded.include_unchanged_research_material_context_in_prompt is True

    def test_create_rejects_invalid_key(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        bad_payload = {
            "key": "Has-Dash",  # invalid: contains dash, uppercase
            "label": "Bad",
            "description": "D",
            "body": "B",
        }

        with override_context(app, ctx):
            resp = client.post("/api/prompts/session-types", json=bad_payload)

        assert resp.status_code == 422, resp.text
        assert not (sc_dir / "Has-Dash.md").exists()
        assert list(sc_dir.glob("Has-Dash*")) == []

    def test_create_rejects_path_traversal(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        bad_payload = {
            "key": "../escape",  # traversal attempt
            "label": "Escape",
            "description": "D",
            "body": "B",
        }

        with override_context(app, ctx):
            resp = client.post("/api/prompts/session-types", json=bad_payload)

        assert resp.status_code == 422, resp.text
        assert not any(sc_dir.parent.glob("escape*"))

    def test_create_rejects_duplicate(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        # Seed ships `exploration` already.
        payload = {
            "key": "exploration",
            "label": "Duplicate",
            "description": "D",
            "body": "B",
        }

        with override_context(app, ctx):
            resp = client.post("/api/prompts/session-types", json=payload)

        assert resp.status_code == 409, resp.text
        # The shipped file is unchanged.
        original = (SHIPPED_SESSION_CONTEXTS / "exploration.md").read_text(encoding="utf-8")
        assert (sc_dir / "exploration.md").read_text(encoding="utf-8") == original


class TestSessionTypeUpdate:
    def test_update_changes_fields_but_not_key(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        update_payload = {
            "label": "Freie Exploration (bearbeitet)",
            "description": "Neue Beschreibung",
            "default_agent_prompt_ids": ["rt_verdichter", "rt_praezise"],
            "include_unchanged_research_material_context_in_prompt": True,
            "body": "Updated open-exploration requirements",
        }

        with override_context(app, ctx):
            resp = client.put(
                "/api/prompts/session-types/exploration",
                json=update_payload,
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["key"] == "exploration"
        assert body["label"] == "Freie Exploration (bearbeitet)"
        assert body["default_agent_prompt_ids"] == [
            "rt_verdichter",
            "rt_praezise",
        ]
        assert body["include_unchanged_research_material_context_in_prompt"] is True
        on_disk = (sc_dir / "exploration.md").read_text(encoding="utf-8")
        assert "Updated open-exploration requirements" in on_disk
        assert (sc_dir / "exploration.md").is_file()

    def test_update_rejects_path_traversal_via_url(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.put(
                "/api/prompts/session-types/..%2Fescape",
                json={"label": "x", "description": "d", "body": "b"},
            )

        # Should not 500; either 422 (invalid key) or 404 (not found).
        assert resp.status_code in (404, 422), resp.text
        assert not any(sc_dir.parent.glob("escape*"))

    def test_update_rejects_key_rename_via_body(self, client: TestClient, tmp_path: Path):

        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        body = {
            "key": "anderer_key",
            "label": "Should be ignored",
            "description": "D",
            "body": "B",
        }

        with override_context(app, ctx):
            resp = client.put("/api/prompts/session-types/exploration", json=body)

        # Schema strips ``key``; update proceeds against the URL key.
        # The point: the new key must NOT be created.
        assert resp.status_code == 200, resp.text
        assert (sc_dir / "exploration.md").is_file()
        assert not (sc_dir / "anderer_key.md").exists()

    def test_update_404_for_unknown_key(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.put(
                "/api/prompts/session-types/does_not_exist",
                json={"label": "x", "description": "d", "body": "b"},
            )

        assert resp.status_code == 404, resp.text
        assert not (sc_dir / "does_not_exist.md").exists()

    def test_update_validation_error_does_not_corrupt(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        original_bytes = (sc_dir / "exploration.md").read_bytes()

        with override_context(app, ctx):
            # Invalid agent id format triggers a validation error in the repo.
            resp = client.put(
                "/api/prompts/session-types/exploration",
                json={
                    "label": "X",
                    "description": "Y",
                    "body": "B",
                    "default_agent_prompt_ids": ["Not-Valid-Id"],
                },
            )

        assert resp.status_code == 422, resp.text
        assert (sc_dir / "exploration.md").read_bytes() == original_bytes

    def test_custom_session_type_can_be_deleted_and_reloads(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        custom = {
            "key": "eigener_typ",
            "label": "Eigener Typ",
            "description": "D",
            "body": "B",
        }

        with override_context(app, ctx):
            created = client.post("/api/prompts/session-types", json=custom)
            deleted = client.delete("/api/prompts/session-types/eigener_typ")

        assert created.status_code == 201, created.text
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {"deleted": "eigener_typ"}
        assert not (sc_dir / "eigener_typ.md").exists()
        assert ctx.discussion.reload_session_configuration.call_count == 2

    def test_shipped_session_type_cannot_be_deleted(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            response = client.delete("/api/prompts/session-types/exploration")

        assert response.status_code == 409, response.text
        assert (sc_dir / "exploration.md").is_file()


class TestSessionTypeReloadBehavior:
    def test_create_triggers_reload_facade(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        payload = {
            "key": "neu_und_mehr",
            "label": "Neu",
            "description": "D",
            "body": "B",
        }

        with override_context(app, ctx):
            resp = client.post("/api/prompts/session-types", json=payload)

        assert resp.status_code == 201, resp.text
        ctx.discussion.reload_session_configuration.assert_called_once()

    def test_update_triggers_reload_facade(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.put(
                "/api/prompts/session-types/exploration",
                json={"label": "X", "description": "D", "body": "B"},
            )

        assert resp.status_code == 200, resp.text
        ctx.discussion.reload_session_configuration.assert_called_once()

    def test_reload_makes_new_session_type_available_via_service(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.post(
                "/api/prompts/session-types",
                json={
                    "key": "sofort_verfuegbar",
                    "label": "Sofort",
                    "description": "D",
                    "body": "B",
                },
            )
            assert resp.status_code == 201, resp.text

            # The live service must reflect the new entry — no restart.
            types = ctx.discussion.get_available_session_types()
        ids = [k for k, _ in types]
        assert "sofort_verfuegbar" in ids


class TestGlobalsList:
    def test_list_returns_only_existing_globals(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/globals")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        ids = {b["id"] for b in body}
        # Shipped globals in data/prompts/prompts_globals.poml.
        assert "principles" in ids
        assert "response_contract" in ids
        assert "roundtable_norms" in ids

    def test_list_entry_exposes_safe_metadata(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/globals")

        body = resp.json()
        by_id = {b["id"]: b for b in body}
        # scope is a metadata field; for shipped globals it must reflect XML.
        assert by_id["principles"]["scope"] in (None, "")
        # roundtable_norms is scope="multi_agent" in the shipped XML.
        assert by_id["roundtable_norms"]["scope"] == "multi_agent"
        for entry in body:
            assert "source_file" not in entry
            assert "path" not in entry
            assert "absolute_path" not in entry


class TestGlobalsUpdate:
    def test_update_label_and_content(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.put(
                "/api/prompts/globals/principles",
                json={
                    "label": "Research stance (edited)",
                    "content": "COLLABORATIVE: revised version.",
                },
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == "principles"
        assert body["label"] == "Research stance (edited)"
        assert body["content"].startswith("COLLABORATIVE: revised version.")
        # scope is read-only — preserved from the original XML.
        assert body["scope"] in (None, "")

        # Disk: full XML file was atomically replaced; other globals are intact.
        poml_path = prompts_dir / "prompts_globals.poml"
        on_disk = poml_path.read_text(encoding="utf-8")
        assert "Research stance (edited)" in on_disk
        assert "revised version" in on_disk
        assert "Response contract" in on_disk
        assert "Discussion norms" in on_disk

    def test_update_rejects_scope_change(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        original_bytes = (prompts_dir / "prompts_globals.poml").read_bytes()

        with override_context(app, ctx):
            resp = client.put(
                "/api/prompts/globals/principles",
                json={
                    "label": "X",
                    "content": "Y",
                    "scope": "multi_agent",  # forbidden
                },
            )

        # Schema rejects the extra field, OR endpoint refuses — either way
        # the file must NOT be mutated.
        assert resp.status_code in (400, 422), resp.text
        assert (prompts_dir / "prompts_globals.poml").read_bytes() == original_bytes

    def test_update_unknown_id_returns_404(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        original_bytes = (prompts_dir / "prompts_globals.poml").read_bytes()

        with override_context(app, ctx):
            resp = client.put(
                "/api/prompts/globals/does_not_exist",
                json={"label": "x", "content": "y"},
            )

        assert resp.status_code == 404, resp.text
        assert (prompts_dir / "prompts_globals.poml").read_bytes() == original_bytes

    def test_update_path_traversal_rejected(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.put(
                "/api/prompts/globals/..%2Fescape",
                json={"label": "x", "content": "y"},
            )

        # The route must not 500, must not write anywhere.
        assert resp.status_code in (400, 404, 422), resp.text
        assert not any(prompts_dir.parent.glob("escape*"))

    def test_update_preserves_other_blocks_exactly(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        original = (prompts_dir / "prompts_globals.poml").read_text(encoding="utf-8")

        with override_context(app, ctx):
            resp = client.put(
                "/api/prompts/globals/response_contract",
                json={"label": "Response contract", "content": "FORM: concise."},
            )

        assert resp.status_code == 200, resp.text
        new_text = (prompts_dir / "prompts_globals.poml").read_text(encoding="utf-8")
        cr_start = new_text.index('id="response_contract"')
        cr_end = new_text.index("</global>", cr_start)
        cr_block = new_text[cr_start:cr_end]
        assert "FORM: concise." in cr_block
        # And the "principles" block must not have been rewritten.
        assert "COLLABORATIVE" in new_text
        assert 'id="response_contract"' in original


class TestGlobalsReloadBehavior:
    def test_update_triggers_reload_facade(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.put(
                "/api/prompts/globals/principles",
                json={"label": "x", "content": "y"},
            )

        assert resp.status_code == 200, resp.text
        ctx.discussion.reload_session_configuration.assert_called_once()

    def test_reload_makes_new_global_content_available_via_repo(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        new_text = "TOTAL NEUE GRUNDHALTUNG XYZ"

        with override_context(app, ctx):
            resp = client.put(
                "/api/prompts/globals/principles",
                json={"label": "Grundhaltung", "content": new_text},
            )
            assert resp.status_code == 200, resp.text
            common = ctx.prompts.get_common_instructions()
        assert new_text in common

    def test_update_only_touches_target_block_in_xml(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.put(
                "/api/prompts/globals/principles",
                json={"label": "Research stance", "content": "REPLACED"},
            )
        assert resp.status_code == 200, resp.text

        ctx.prompts.reload()
        block = ctx.prompts.get_global("principles")
        assert block is not None
        assert block.content.strip() == "REPLACED"
        for other_id, expected_substring in (
            ("response_contract", "one continuous paragraph"),
            ("roundtable_norms", "ENGAGE"),
        ):
            other = ctx.prompts.get_global(other_id)
            assert other is not None
            assert expected_substring in other.content, other_id


# Route ordering: literal routes must not be shadowed by dynamic
class TestRouteOrdering:
    def test_get_globals_not_shadowed_by_dynamic_id(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/globals")

        # The literal list must return 200, not a 404 for ``globals`` as id.
        assert resp.status_code == 200, resp.text
        # And it must be a list, not a single object.
        assert isinstance(resp.json(), list)

    def test_get_session_types_not_shadowed_by_dynamic_key(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/session-types")

        assert resp.status_code == 200, resp.text
        assert isinstance(resp.json(), list)


class TestSessionTypeDefaultParity:
    def test_shipped_session_baselines_match_active_definitions(self):

        active = {path.name: path.read_bytes() for path in SHIPPED_SESSION_CONTEXTS.glob("*.md")}
        baselines = {
            path.name: path.read_bytes() for path in SHIPPED_DEFAULT_SESSION_CONTEXTS.glob("*.md")
        }

        assert baselines == active

    def test_list_and_update_expose_provenance(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        baseline_path = tmp_path / "prompt_defaults" / "session_contexts" / "exploration.md"
        original_baseline = baseline_path.read_bytes()
        (sc_dir / "exploration.md").write_bytes(original_baseline + b"edited\n")

        with override_context(app, ctx):
            listed = client.get("/api/prompts/session-types")
            updated = client.put(
                "/api/prompts/session-types/exploration",
                json={"label": "Edited", "description": "D", "body": "B"},
            )

        assert listed.status_code == 200, listed.text
        entry = {item["key"]: item for item in listed.json()}["exploration"]
        assert entry["is_shipped"] is True
        assert entry["origin"] == "shipped_modified"
        assert updated.status_code == 200, updated.text
        assert updated.json()["origin"] == "shipped_modified"
        assert baseline_path.read_bytes() == original_baseline

    def test_bulk_restore_recreates_baselines_and_preserves_custom(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        baseline_root = tmp_path / "prompt_defaults" / "session_contexts"
        (sc_dir / "exploration.md").write_text("edited", encoding="utf-8")
        (sc_dir / "critique.md").unlink()
        custom = sc_dir / "custom_mode.md"
        custom.write_text(
            "---\nkey: custom_mode\nlabel: Custom\ndescription: D\n---\nCustom body\n",
            encoding="utf-8",
        )

        with override_context(app, ctx):
            resp = client.post("/api/prompts/session-types/restore-defaults")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"restored": ["critique", "exploration"]}
        for key in ("critique", "exploration"):
            assert (sc_dir / f"{key}.md").read_bytes() == (baseline_root / f"{key}.md").read_bytes()
        assert custom.read_text(encoding="utf-8").endswith("Custom body\n")
        ctx.discussion.reload_session_configuration.assert_called_once()

    def test_single_restore_validates_baseline_and_preserves_source(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        baseline_path = tmp_path / "prompt_defaults" / "session_contexts" / "exploration.md"
        baseline_bytes = baseline_path.read_bytes()
        (sc_dir / "exploration.md").write_text("edited", encoding="utf-8")

        with override_context(app, ctx):
            resp = client.post("/api/prompts/session-types/exploration/restore-default")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"restored": ["exploration"]}
        assert (sc_dir / "exploration.md").read_bytes() == baseline_bytes
        assert baseline_path.read_bytes() == baseline_bytes
        ctx.discussion.reload_session_configuration.assert_called_once()

    def test_single_restore_ignores_an_unrelated_corrupt_baseline(
        self, client: TestClient, tmp_path: Path
    ):

        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        baseline_dir = tmp_path / "prompt_defaults" / "session_contexts"
        expected = (baseline_dir / "exploration.md").read_bytes()
        (sc_dir / "exploration.md").write_text("edited", encoding="utf-8")
        (baseline_dir / "critique.md").write_text("not valid", encoding="utf-8")

        with override_context(app, ctx):
            resp = client.post("/api/prompts/session-types/exploration/restore-default")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"restored": ["exploration"]}
        assert (sc_dir / "exploration.md").read_bytes() == expected
        ctx.discussion.reload_session_configuration.assert_called_once()

    def test_single_restore_rejects_invalid_or_non_shipped_keys_without_mutation(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        custom = sc_dir / "custom_mode.md"
        custom.write_text(
            "---\nkey: custom_mode\nlabel: Custom\ndescription: D\n---\nCustom body\n",
            encoding="utf-8",
        )
        before = {path.name: path.read_bytes() for path in sc_dir.glob("*.md")}

        with override_context(app, ctx):
            malformed = client.post("/api/prompts/session-types/Has-Dash/restore-default")
            custom_response = client.post("/api/prompts/session-types/custom_mode/restore-default")

        assert malformed.status_code == 422, malformed.text
        assert custom_response.status_code == 404, custom_response.text
        assert {path.name: path.read_bytes() for path in sc_dir.glob("*.md")} == before
        ctx.discussion.reload_session_configuration.assert_not_called()

    def test_missing_session_baseline_directory_does_not_mutate_or_reload(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        baseline_dir = tmp_path / "prompt_defaults" / "session_contexts"
        shutil.rmtree(baseline_dir)
        before = {path.name: path.read_bytes() for path in sc_dir.glob("*.md")}

        with override_context(app, ctx):
            resp = client.post("/api/prompts/session-types/restore-defaults")

        assert resp.status_code == 404, resp.text
        assert {path.name: path.read_bytes() for path in sc_dir.glob("*.md")} == before
        ctx.discussion.reload_session_configuration.assert_not_called()

    def test_corrupt_session_baseline_does_not_mutate_or_reload(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        baseline_dir = tmp_path / "prompt_defaults" / "session_contexts"
        (baseline_dir / "exploration.md").write_text("not valid", encoding="utf-8")
        before = {path.name: path.read_bytes() for path in sc_dir.glob("*.md")}

        with override_context(app, ctx):
            resp = client.post("/api/prompts/session-types/restore-defaults")

        assert resp.status_code == 422, resp.text
        assert {path.name: path.read_bytes() for path in sc_dir.glob("*.md")} == before
        ctx.discussion.reload_session_configuration.assert_not_called()


class TestGlobalDefaultParity:
    @staticmethod
    def _add_custom_global(prompts_dir: Path) -> None:
        path = prompts_dir / "prompts_globals.poml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                "</prompts>",
                '  <global id="custom_block" label="Custom"><content>Custom content</content></global>\n</prompts>',
            ),
            encoding="utf-8",
        )

    def test_list_exposes_default_and_custom_provenance(self, client: TestClient, tmp_path: Path):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        self._add_custom_global(prompts_dir)
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/globals")

        assert resp.status_code == 200, resp.text
        by_id = {block["id"]: block for block in resp.json()}
        assert by_id["principles"]["is_shipped"] is True
        assert by_id["principles"]["origin"] == "shipped_default"
        assert by_id["custom_block"]["is_shipped"] is False
        assert by_id["custom_block"]["origin"] == "custom"

    def test_list_uses_effective_global_content_for_provenance(
        self, client: TestClient, tmp_path: Path
    ):

        prompts_dir, sc_dir = _build_layout(tmp_path)
        active = prompts_dir / "prompts_globals.poml"
        original = active.read_text(encoding="utf-8")
        active.write_text(
            original.replace("<content>", "<content>\n  ").replace("</content>", "\n  </content>"),
            encoding="utf-8",
        )
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/globals")

        assert resp.status_code == 200, resp.text
        by_id = {block["id"]: block for block in resp.json()}
        assert by_id["principles"]["is_shipped"] is True
        assert by_id["principles"]["origin"] == "shipped_default"

    def test_bulk_restore_copies_baseline_blocks_and_preserves_custom(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        self._add_custom_global(prompts_dir)
        active = prompts_dir / "prompts_globals.poml"
        active.write_text(
            active.read_text(encoding="utf-8").replace("Research stance", "Edited"),
            encoding="utf-8",
        )
        ctx = _build_context(prompts_dir, sc_dir)
        baseline = tmp_path / "prompt_defaults" / "prompts_globals.poml"
        baseline_bytes = baseline.read_bytes()

        with override_context(app, ctx):
            resp = client.post("/api/prompts/globals/restore-defaults")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "restored": [
                "principles",
                "response_contract",
                "round_synthesis",
                "roundtable_norms",
            ]
        }
        restored_text = active.read_text(encoding="utf-8")
        assert 'id="custom_block"' in restored_text
        assert "Custom content" in restored_text
        assert "Edited" not in restored_text
        assert baseline.read_bytes() == baseline_bytes
        ctx.discussion.reload_session_configuration.assert_called_once()

    def test_single_restore_replaces_one_block_without_deleting_custom(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        self._add_custom_global(prompts_dir)
        active = prompts_dir / "prompts_globals.poml"
        active.write_text(
            active.read_text(encoding="utf-8").replace("Grundhaltung", "Edited"),
            encoding="utf-8",
        )
        ctx = _build_context(prompts_dir, sc_dir)

        with override_context(app, ctx):
            resp = client.post("/api/prompts/globals/principles/restore-default")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"restored": ["principles"]}
        text = active.read_text(encoding="utf-8")
        assert "Research stance" in text
        assert 'id="custom_block"' in text
        ctx.discussion.reload_session_configuration.assert_called_once()

    def test_global_restore_rejects_duplicate_baseline_ids_without_mutation(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        baseline = tmp_path / "prompt_defaults" / "prompts_globals.poml"
        baseline.write_text(
            "<prompts>"
            '<global id="principles" label="One"><content>A</content></global>'
            '<global id="principles" label="Two"><content>B</content></global>'
            "</prompts>",
            encoding="utf-8",
        )
        active = prompts_dir / "prompts_globals.poml"
        before = active.read_bytes()

        with override_context(app, ctx):
            resp = client.post("/api/prompts/globals/restore-defaults")

        assert resp.status_code == 422, resp.text
        assert active.read_bytes() == before
        ctx.discussion.reload_session_configuration.assert_not_called()

    def test_global_restore_rejects_malformed_active_document_without_reload(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        active = prompts_dir / "prompts_globals.poml"
        active.write_text('<prompts><global id="principles">', encoding="utf-8")
        before = active.read_bytes()

        with override_context(app, ctx):
            resp = client.post("/api/prompts/globals/restore-defaults")

        assert resp.status_code == 422, resp.text
        assert active.read_bytes() == before
        ctx.discussion.reload_session_configuration.assert_not_called()

    def test_invalid_global_baseline_does_not_mutate_or_reload(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        baseline = tmp_path / "prompt_defaults" / "prompts_globals.poml"
        baseline.write_text("<prompts><global id='broken'>", encoding="utf-8")
        active = prompts_dir / "prompts_globals.poml"
        before = active.read_bytes()

        with override_context(app, ctx):
            resp = client.post("/api/prompts/globals/restore-defaults")

        assert resp.status_code == 422, resp.text
        assert active.read_bytes() == before
        ctx.discussion.reload_session_configuration.assert_not_called()

    def test_single_unknown_global_is_404_without_mutation(
        self, client: TestClient, tmp_path: Path
    ):
        prompts_dir, sc_dir = _build_layout(tmp_path)
        ctx = _build_context(prompts_dir, sc_dir)
        active = prompts_dir / "prompts_globals.poml"
        before = active.read_bytes()

        with override_context(app, ctx):
            resp = client.post("/api/prompts/globals/not_shipped/restore-default")

        assert resp.status_code == 404, resp.text
        assert active.read_bytes() == before
        ctx.discussion.reload_session_configuration.assert_not_called()
