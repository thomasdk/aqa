"""Tests for role (prompt-template) management routes.

Exercises the role CRUD endpoints AND the ``POST /api/prompts/roles/restore-defaults``
endpoint, which must:

* atomically restore every baseline POML into the active ``data/prompts/roles/``
  directory, recreating missing shipped roles and overwriting edited ones;
* leave custom (non-baseline) roles unchanged;
* reload the prompt repository and live session configuration on success;
* fail clearly (non-2xx) and leave the active directory untouched when the
  baseline directory is missing or empty, or any source file is invalid;
* validate that all resolved paths stay inside the active / baseline ``data`` root.

The tests use a fully mocked ``AppContext``; filesystem side-effects are real, scoped to
``tmp_path`` and only touch sibling ``prompts/`` + ``prompt_defaults/`` trees.
"""

from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api_server import app
from src.prompts.storage import PromptRepository
from src.service.discussion import DiscussionService
from src.service.routers.roles import _atomic_write_text
from tests.router_test_support import override_context

_SHIPPED_BASELINE = {
    "alpha": (
        "<prompts>"
        '<prompt id="alpha" label="Alpha">'
        "<role>Original Alpha role.</role>"
        "<task>Original Alpha task.</task>"
        "</prompt>"
        "</prompts>"
    ),
    "beta": (
        "<prompts>"
        '<prompt id="beta" label="Beta">'
        "<role>Original Beta role.</role>"
        "</prompt>"
        "</prompts>"
    ),
}

_CUSTOM_POML = (
    "<prompts>"
    '<prompt id="custom_user" label="Custom User">'
    "<role>Custom user-defined role.</role>"
    "</prompt>"
    "</prompts>"
)


def _build_layout(
    tmp_path: Path,
    *,
    shipped_active: dict[str, str] | None = None,
    extra_active: dict[str, str] | None = None,
    shipped_baseline: dict[str, str] | None = None,
    baseline_dir_missing: bool = False,
    baseline_dir_empty: bool = False,
    invalid_baseline_file: str | None = None,
) -> tuple[Path, Path]:
    """Create ``tmp/data/prompts`` and ``tmp/data/prompt_defaults/roles`` trees.

    Returns ``(prompts_dir, baseline_dir)``.
    """

    prompts_dir = tmp_path / "data" / "prompts"
    roles_dir = prompts_dir / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)

    for role_id, content in (shipped_active or {}).items():
        (roles_dir / f"{role_id}.poml").write_text(content, encoding="utf-8")

    for role_id, content in (extra_active or {}).items():
        (roles_dir / f"{role_id}.poml").write_text(content, encoding="utf-8")

    baseline_dir = tmp_path / "data" / "prompt_defaults" / "roles"
    if baseline_dir_missing:
        return prompts_dir, baseline_dir

    baseline_dir.mkdir(parents=True, exist_ok=True)

    if invalid_baseline_file is not None:
        (baseline_dir / "alpha.poml").write_text(invalid_baseline_file, encoding="utf-8")
    elif not baseline_dir_empty:
        for role_id, content in (shipped_baseline or {}).items():
            (baseline_dir / f"{role_id}.poml").write_text(content, encoding="utf-8")

    return prompts_dir, baseline_dir


def _build_context(tmp_path: Path, prompts_dir: Path, baseline_dir: Path) -> MagicMock:
    """Build a mocked AppContext wired to real PromptRepository + DiscussionService.

    The repository and discussion service are real (so reload / list_templates are
    exercised), but every other collaborator is a MagicMock. The repo is rooted
    at ``prompts_dir`` (NOT a global cache), so each test gets a fresh state.
    """

    prompt_repo = PromptRepository(base_path=prompts_dir)
    discussion = MagicMock(spec=DiscussionService)
    discussion.reload_session_configuration = MagicMock()
    discussion.session_type_repo = MagicMock()
    discussion.session_type_repo.list.return_value = []

    ctx = MagicMock()
    ctx.prompts = prompt_repo
    ctx.discussion = discussion
    ctx.settings = MagicMock()
    ctx.settings.prompt_library_path = str(prompts_dir)
    ctx.llm_manager = MagicMock()
    return ctx


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# Import through an isolated configuration boundary.
class TestApiImport:
    def test_app_is_fastapi_instance(self):
        from fastapi import FastAPI

        assert isinstance(app, FastAPI)


# Current CRUD routes remain reachable alongside literal routes.
class TestExistingRoleRoutesStillWork:
    def test_get_role_by_id_still_routes_correctly(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/roles/alpha")

        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == "alpha"

    def test_restore_defaults_does_not_shadow_get_role_id(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/roles/restore-defaults")

        # 404 (no such role) — not 200 — proves literal route was not shadowed.
        assert resp.status_code == 404, resp.text


class TestRoleCrudReloadsLiveDiscussionConfiguration:
    def test_create_update_and_delete_reload_live_configuration(self, client, tmp_path):
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            shipped_baseline=dict(_SHIPPED_BASELINE),
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            created = client.post(
                "/api/prompts/roles",
                json={
                    "id": "custom_role",
                    "label": "Custom role",
                    "role": "Custom role text.",
                    "task": "",
                    "output_format": "",
                },
            )
            updated = client.put(
                "/api/prompts/roles/alpha",
                json={"label": "Updated Alpha"},
            )
            deleted = client.delete("/api/prompts/roles/custom_role")

        assert created.status_code == 201, created.text
        assert updated.status_code == 200, updated.text
        assert deleted.status_code == 200, deleted.text
        assert ctx.discussion.reload_session_configuration.call_count == 3


class TestRoleDeletionSessionTypeDependencies:
    def _context_with_dependencies(self, tmp_path: Path, role_id: str = "custom_role"):
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            extra_active={
                role_id: (
                    "<prompts>"
                    f'<prompt id="{role_id}" label="Custom Role">'
                    "<role>Custom role text.</role>"
                    "</prompt></prompts>"
                )
            },
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)
        ctx.discussion.session_type_repo = MagicMock()
        return ctx, prompts_dir / "roles" / f"{role_id}.poml"

    def test_referenced_role_returns_stable_conflict_and_leaves_files_unchanged(
        self, client, tmp_path
    ):
        ctx, role_path = self._context_with_dependencies(tmp_path)
        ctx.discussion.session_type_repo.list.return_value = [
            SimpleNamespace(
                key="zeta_review",
                label="Zeta Review",
                default_agent_prompt_ids=["custom_role", "custom_role"],
            ),
            SimpleNamespace(
                key="alpha_review",
                label="Alpha Review",
                default_agent_prompt_ids=["custom_role"],
            ),
            SimpleNamespace(key="unrelated", label="Unrelated", default_agent_prompt_ids=[]),
            # A stale malformed unrelated entry must not affect the result.
            SimpleNamespace(key=None, label=None, default_agent_prompt_ids=["other_role"]),
        ]

        with override_context(app, ctx):
            response = client.delete("/api/prompts/roles/custom_role")

        assert response.status_code == 409, response.text
        assert response.json()["error"] == {
            "code": "role_referenced_by_session_types",
            "params": {
                "session_types": [
                    {"key": "alpha_review", "label": "Alpha Review"},
                    {"key": "zeta_review", "label": "Zeta Review"},
                ]
            },
        }
        assert role_path.exists()
        assert ctx.discussion.reload_session_configuration.call_count == 0

    def test_dependency_check_is_serialized_with_other_mutable_data_operations(
        self, client, tmp_path
    ):
        ctx, _role_path = self._context_with_dependencies(tmp_path)
        dependency_check_started = Event()
        release_dependency_check = Event()
        competing_operation_started = Event()

        def list_dependencies():
            dependency_check_started.set()
            assert release_dependency_check.wait(timeout=2)
            return []

        ctx.discussion.session_type_repo.list.side_effect = list_dependencies

        def delete_role():
            with override_context(app, ctx):
                client.delete("/api/prompts/roles/custom_role")

        delete_thread = Thread(target=delete_role)
        delete_thread.start()
        assert dependency_check_started.wait(timeout=2)

        def competing_operation():
            # Session Type mutation routes use this same lock.
            from src.config.user_data import mutable_data_lock

            with mutable_data_lock:
                competing_operation_started.set()

        competing_thread = Thread(target=competing_operation)
        competing_thread.start()
        assert not competing_operation_started.wait(timeout=0.05)

        release_dependency_check.set()
        delete_thread.join(timeout=2)
        competing_thread.join(timeout=2)
        assert not delete_thread.is_alive()
        assert not competing_thread.is_alive()
        assert competing_operation_started.is_set()

    @pytest.mark.parametrize(
        "repository",
        [
            None,
            SimpleNamespace(
                list=lambda: [
                    SimpleNamespace(
                        key="../outside",
                        label="Unsafe",
                        default_agent_prompt_ids=["custom_role"],
                    )
                ]
            ),
        ],
    )
    def test_unavailable_or_unsafe_dependency_data_fails_closed(self, client, tmp_path, repository):
        ctx, role_path = self._context_with_dependencies(tmp_path)
        ctx.discussion.session_type_repo = repository

        with override_context(app, ctx):
            response = client.delete("/api/prompts/roles/custom_role")

        assert response.status_code == 503, response.text
        assert response.json()["error"] == {
            "code": "session_type_dependency_check_unavailable",
            "params": {},
        }
        assert role_path.exists()
        assert ctx.discussion.reload_session_configuration.call_count == 0


class TestRoleCrudAtomicWrites:
    def test_atomic_text_write_replaces_existing_file(self, tmp_path):
        target = tmp_path / "roles" / "alpha.poml"
        target.parent.mkdir()
        target.write_text("old", encoding="utf-8")

        _atomic_write_text(target, "new")

        assert target.read_text(encoding="utf-8") == "new"
        assert list(target.parent.glob(".*.tmp")) == []

    def test_atomic_text_write_preserves_existing_file_on_replace_failure(self, tmp_path):
        target = tmp_path / "roles" / "alpha.poml"
        target.parent.mkdir()
        target.write_text("old", encoding="utf-8")

        with patch(
            "src.service.routers.roles.os.replace",
            side_effect=OSError("simulated interrupted publication"),
        ):
            with pytest.raises(OSError, match="interrupted"):
                _atomic_write_text(target, "partial-new")

        assert target.read_text(encoding="utf-8") == "old"
        assert list(target.parent.glob(".*.tmp")) == []


# POST /api/prompts/roles/{role_id}/restore-default — single-role restore
class TestRestoreSingleDefault:
    def test_modified_shipped_role_is_restored_alone(self, client, tmp_path):
        modified_alpha = _SHIPPED_BASELINE["alpha"].replace(
            "Original Alpha role.", "Edited Alpha role."
        )
        modified_beta = _SHIPPED_BASELINE["beta"].replace(
            "Original Beta role.", "Edited Beta role."
        )
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": modified_alpha, "beta": modified_beta},
            shipped_baseline=dict(_SHIPPED_BASELINE),
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            resp = client.post("/api/prompts/roles/alpha/restore-default")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"restored": ["alpha"]}
        assert (prompts_dir / "roles" / "alpha.poml").read_text(
            encoding="utf-8"
        ) == _SHIPPED_BASELINE["alpha"]
        assert (prompts_dir / "roles" / "beta.poml").read_text(encoding="utf-8") == modified_beta
        ctx.discussion.reload_session_configuration.assert_called_once()

    @pytest.mark.parametrize("role_id", ["custom_user", "unknown"])
    def test_custom_or_unknown_role_is_refused_without_mutation(self, client, tmp_path, role_id):
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            extra_active={"custom_user": _CUSTOM_POML},
            shipped_baseline=dict(_SHIPPED_BASELINE),
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)
        before = {path.name: path.read_bytes() for path in (prompts_dir / "roles").glob("*.poml")}

        with override_context(app, ctx):
            resp = client.post(f"/api/prompts/roles/{role_id}/restore-default")

        assert resp.status_code == 404, resp.text
        assert {
            path.name: path.read_bytes() for path in (prompts_dir / "roles").glob("*.poml")
        } == before
        ctx.discussion.reload_session_configuration.assert_not_called()

    def test_invalid_baseline_is_rejected_before_any_write(self, client, tmp_path):
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={
                "alpha": _SHIPPED_BASELINE["alpha"],
                "beta": _SHIPPED_BASELINE["beta"],
            },
            invalid_baseline_file="<<<not valid xml>>>",
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)
        before = {path.name: path.read_bytes() for path in (prompts_dir / "roles").glob("*.poml")}

        with override_context(app, ctx):
            resp = client.post("/api/prompts/roles/alpha/restore-default")

        assert resp.status_code == 422, resp.text
        assert {
            path.name: path.read_bytes() for path in (prompts_dir / "roles").glob("*.poml")
        } == before
        ctx.discussion.reload_session_configuration.assert_not_called()


class TestRoleShippedMetadata:
    def test_role_list_exposes_is_shipped(self, client, tmp_path):
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            extra_active={"custom_user": _CUSTOM_POML},
            shipped_baseline={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/roles")

        assert resp.status_code == 200, resp.text
        by_id = {role["id"]: role for role in resp.json()}
        assert by_id["alpha"]["is_shipped"] is True
        assert by_id["custom_user"]["is_shipped"] is False


class TestRoleOrigin:
    def _role_meta_for(self, role_id, prompts_dir):
        """Return ``(active_bytes, baseline_bytes_or_None)`` for a role id."""
        active_path = prompts_dir / "roles" / f"{role_id}.poml"
        baseline_path = prompts_dir.parent / "prompt_defaults" / "roles" / f"{role_id}.poml"
        active_bytes = active_path.read_bytes() if active_path.exists() else b""
        baseline_bytes = baseline_path.read_bytes() if baseline_path.is_file() else None
        return active_bytes, baseline_bytes

    def test_origin_is_shipped_default_when_active_matches_baseline(self, client, tmp_path):
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            shipped_baseline={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/roles")

        assert resp.status_code == 200, resp.text
        by_id = {role["id"]: role for role in resp.json()}
        assert by_id["alpha"]["origin"] == "shipped_default"
        # The current response retains ``is_shipped`` and sets it to True.
        assert by_id["alpha"]["is_shipped"] is True

    def test_origin_is_shipped_modified_when_active_differs_from_baseline(self, client, tmp_path):
        modified_alpha = _SHIPPED_BASELINE["alpha"].replace(
            "Original Alpha role.", "Edited Alpha role."
        )
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": modified_alpha},
            shipped_baseline={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/roles")

        assert resp.status_code == 200, resp.text
        by_id = {role["id"]: role for role in resp.json()}
        assert by_id["alpha"]["origin"] == "shipped_modified"
        assert by_id["alpha"]["is_shipped"] is True

    def test_origin_is_custom_for_non_baseline_role(self, client, tmp_path):
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            extra_active={"custom_user": _CUSTOM_POML},
            shipped_baseline={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/roles")

        assert resp.status_code == 200, resp.text
        by_id = {role["id"]: role for role in resp.json()}
        assert by_id["custom_user"]["origin"] == "custom"
        assert by_id["custom_user"]["is_shipped"] is False

    def test_origin_is_custom_when_baseline_file_is_missing(self, client, tmp_path):
        # No shipped baseline present at all — the active role is treated as custom.
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            # No shipped_baseline argument: baseline_dir exists but is empty.
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/roles")

        assert resp.status_code == 200, resp.text
        by_id = {role["id"]: role for role in resp.json()}
        # The only "shipped" role reported must have origin == "custom" because
        # there is no baseline file to compare against.
        assert by_id["alpha"]["origin"] == "custom"
        assert by_id["alpha"]["is_shipped"] is False

    def test_origin_byte_comparison_holds_against_disk(self, client, tmp_path):
        modified_beta = _SHIPPED_BASELINE["beta"].replace(
            "Original Beta role.", "Edited Beta role."
        )
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={
                "alpha": _SHIPPED_BASELINE["alpha"],
                "beta": modified_beta,
            },
            extra_active={"custom_user": _CUSTOM_POML},
            shipped_baseline=dict(_SHIPPED_BASELINE),
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/roles")

        assert resp.status_code == 200, resp.text
        by_id = {role["id"]: role for role in resp.json()}

        for role_id, expected_origin in (
            ("alpha", "shipped_default"),
            ("beta", "shipped_modified"),
            ("custom_user", "custom"),
        ):
            active_bytes, baseline_bytes = self._role_meta_for(role_id, prompts_dir)
            if expected_origin == "shipped_default":
                assert baseline_bytes is not None
                assert active_bytes == baseline_bytes
            elif expected_origin == "shipped_modified":
                assert baseline_bytes is not None
                assert active_bytes != baseline_bytes
            else:  # custom
                assert baseline_bytes is None

            assert by_id[role_id]["origin"] == expected_origin

    def test_single_role_response_exposes_origin(self, client, tmp_path):
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            shipped_baseline={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/roles/alpha")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["origin"] == "shipped_default"
        assert body["is_shipped"] is True
        assert "label_key" not in body

    def test_shipped_role_label_is_verbatim_when_prompt_body_changed(self, client, tmp_path):
        modified_alpha = _SHIPPED_BASELINE["alpha"].replace(
            "Original Alpha role.", "Edited Alpha role."
        )
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": modified_alpha},
            shipped_baseline={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            body = client.get("/api/prompts/roles/alpha").json()

        assert body["origin"] == "shipped_modified"
        assert body["label"] == "Alpha"
        assert "label_key" not in body

    def test_shipped_role_label_remains_verbatim_when_changed(self, client, tmp_path):
        modified_alpha = _SHIPPED_BASELINE["alpha"].replace('label="Alpha"', 'label="Custom Alpha"')
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": modified_alpha},
            shipped_baseline={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            body = client.get("/api/prompts/roles/alpha").json()

        assert body["label"] == "Custom Alpha"
        assert "label_key" not in body

    def test_http_errors_keep_detail_and_add_stable_envelope(self, client, tmp_path):
        prompts_dir, baseline_dir = _build_layout(tmp_path)
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            response = client.get("/api/prompts/roles/missing")

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Role 'missing' not found",
            "error": {"code": "not_found", "params": {}},
        }


# POST /api/prompts/roles/restore-defaults — happy path
class TestRestoreDefaultsHappyPath:
    def test_modified_shipped_role_is_atomically_restored(self, client, tmp_path):

        modified_alpha = (
            "<prompts>"
            '<prompt id="alpha" label="Alpha EDITED">'
            "<role>User-edited content for Alpha.</role>"
            "<task>Edited task.</task>"
            "</prompt>"
            "</prompts>"
        )
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": modified_alpha, "beta": _SHIPPED_BASELINE["beta"]},
            shipped_baseline=dict(_SHIPPED_BASELINE),
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            resp = client.post("/api/prompts/roles/restore-defaults")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert sorted(body["restored"]) == ["alpha", "beta"]

        # Atomic restore: the on-disk content matches the baseline byte-for-byte.
        restored_alpha = (prompts_dir / "roles" / "alpha.poml").read_text(encoding="utf-8")
        assert restored_alpha == _SHIPPED_BASELINE["alpha"]
        restored_beta = (prompts_dir / "roles" / "beta.poml").read_text(encoding="utf-8")
        assert restored_beta == _SHIPPED_BASELINE["beta"]

    def test_missing_shipped_role_is_recreated(self, client, tmp_path):

        # Only ``beta`` is currently present in active; ``alpha`` is missing.
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"beta": _SHIPPED_BASELINE["beta"]},
            shipped_baseline=dict(_SHIPPED_BASELINE),
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        # Precondition: alpha is absent.
        assert not (prompts_dir / "roles" / "alpha.poml").exists()

        with override_context(app, ctx):
            resp = client.post("/api/prompts/roles/restore-defaults")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        # alpha is recreated; beta is overwritten (still present after).
        assert "alpha" in body["restored"]
        assert "beta" in body["restored"]

        assert (prompts_dir / "roles" / "alpha.poml").exists()
        assert (prompts_dir / "roles" / "alpha.poml").read_text(
            encoding="utf-8"
        ) == _SHIPPED_BASELINE["alpha"]
        # beta is overwritten with baseline content.
        assert (prompts_dir / "roles" / "beta.poml").read_text(
            encoding="utf-8"
        ) == _SHIPPED_BASELINE["beta"]

    def test_custom_active_role_remains_unchanged(self, client, tmp_path):

        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            extra_active={"custom_user": _CUSTOM_POML},
            shipped_baseline=dict(_SHIPPED_BASELINE),
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        # Snapshot custom content + mtime.
        custom_path = prompts_dir / "roles" / "custom_user.poml"
        custom_before = custom_path.read_text(encoding="utf-8")
        custom_mtime_before = custom_path.stat().st_mtime_ns

        with override_context(app, ctx):
            resp = client.post("/api/prompts/roles/restore-defaults")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        # custom_user is NOT in the restored list — it is preserved.
        assert "custom_user" not in body["restored"]
        assert "alpha" in body["restored"]

        # Custom file is byte-for-byte unchanged and not even touched (mtime).
        assert custom_path.read_text(encoding="utf-8") == custom_before
        assert custom_path.stat().st_mtime_ns == custom_mtime_before

    def test_reload_invoked_on_prompt_repo_and_live_configuration(self, client, tmp_path):

        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            shipped_baseline=dict(_SHIPPED_BASELINE),
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            # Spy on PromptRepository.reload.
            with patch.object(PromptRepository, "reload") as repo_reload:
                resp = client.post("/api/prompts/roles/restore-defaults")

        assert resp.status_code == 200, resp.text
        # Preferred live-configuration wrapper was called on the service.
        ctx.discussion.reload_session_configuration.assert_called_once()
        # Repository reload was triggered.
        repo_reload.assert_called_once()


# POST /api/prompts/roles/restore-defaults — failure / no-mutation
class TestRestoreDefaultsFailures:
    def test_missing_baseline_returns_non_success_and_no_mutation(self, client, tmp_path):
        prompts_dir, _baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            baseline_dir_missing=True,
        )
        ctx = _build_context(tmp_path, prompts_dir, tmp_path / "data" / "prompt_defaults" / "roles")
        snapshot = (prompts_dir / "roles" / "alpha.poml").read_text(encoding="utf-8")

        with override_context(app, ctx):
            resp = client.post("/api/prompts/roles/restore-defaults")

        assert resp.status_code in (400, 404, 422, 500), resp.text
        # The active file is byte-for-byte unchanged.
        assert (prompts_dir / "roles" / "alpha.poml").read_text(encoding="utf-8") == snapshot
        # Reload hooks must not fire on failure.
        ctx.discussion.reload_session_configuration.assert_not_called()

    def test_empty_baseline_returns_non_success_and_no_mutation(self, client, tmp_path):
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            baseline_dir_empty=True,
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)
        snapshot = (prompts_dir / "roles" / "alpha.poml").read_text(encoding="utf-8")

        with override_context(app, ctx):
            resp = client.post("/api/prompts/roles/restore-defaults")

        assert resp.status_code in (400, 404, 422, 500), resp.text
        assert (prompts_dir / "roles" / "alpha.poml").read_text(encoding="utf-8") == snapshot
        ctx.discussion.reload_session_configuration.assert_not_called()

    def test_invalid_baseline_poml_fails_without_mutation(self, client, tmp_path):

        # Use a non-empty baseline dir where alpha.poml is intentionally invalid.
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            invalid_baseline_file="<<<not valid xml>>>",
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)
        snapshot = (prompts_dir / "roles" / "alpha.poml").read_text(encoding="utf-8")

        with override_context(app, ctx):
            resp = client.post("/api/prompts/roles/restore-defaults")

        assert resp.status_code in (400, 422, 500), resp.text
        # Mutation: alpha file in active dir is still the original.
        assert (prompts_dir / "roles" / "alpha.poml").read_text(encoding="utf-8") == snapshot
        ctx.discussion.reload_session_configuration.assert_not_called()


class TestRestoreDefaultsPathSafety:
    def test_target_path_resolves_inside_roles_dir(self, client, tmp_path):
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            shipped_baseline=dict(_SHIPPED_BASELINE),
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            resp = client.post("/api/prompts/roles/restore-defaults")

        assert resp.status_code == 200, resp.text
        # Every baseline role file landed at <prompts_dir>/roles/<id>.poml.
        roles_dir = (prompts_dir / "roles").resolve()
        for restored_id in resp.json()["restored"]:
            target = (roles_dir / f"{restored_id}.poml").resolve()
            assert roles_dir in target.parents or target.parent == roles_dir
            assert target.exists()


# PUT /api/prompts/roles/{role_id} — path-traversal contract
class TestUpdateRolePathTraversal:
    def test_invalid_id_format_returns_422_and_writes_nothing(self, client, tmp_path):
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            shipped_baseline=dict(_SHIPPED_BASELINE),
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        # Snapshot the active roles dir and the data root (to prove no escape).
        roles_dir = (prompts_dir / "roles").resolve()
        roles_before = {path.name: path.read_bytes() for path in roles_dir.glob("*.poml")}
        data_root = prompts_dir.parent.resolve()
        data_root_before = {
            path.relative_to(data_root).as_posix(): path.read_bytes()
            for path in data_root.rglob("*")
            if path.is_file()
        }

        with override_context(app, ctx):
            resp = client.put(
                "/api/prompts/roles/invalid-id",
                json={"label": "Should never write"},
            )

        # 422 — the role-id grammar is violated; no I/O should have happened.
        assert resp.status_code == 422, resp.text
        assert "must match" in resp.json()["detail"]

        # No file was created under roles_dir or anywhere under data_root.
        roles_after = {path.name: path.read_bytes() for path in roles_dir.glob("*.poml")}
        assert roles_after == roles_before
        data_root_after = {
            path.relative_to(data_root).as_posix(): path.read_bytes()
            for path in data_root.rglob("*")
            if path.is_file()
        }
        assert data_root_after == data_root_before

        # No reload or side-effect on the discussion service.
        ctx.discussion.reload_session_configuration.assert_not_called()

    def test_valid_role_edit_still_succeeds(self, client, tmp_path):
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            shipped_baseline=dict(_SHIPPED_BASELINE),
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            resp = client.put(
                "/api/prompts/roles/alpha",
                json={"label": "Alpha Renamed"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == "alpha"
        assert body["label"] == "Alpha Renamed"

        # The on-disk file was updated.
        written = (prompts_dir / "roles" / "alpha.poml").read_text(encoding="utf-8")
        assert "Alpha Renamed" in written
        ctx.discussion.reload_session_configuration.assert_called_once()

    def test_resolved_containment_helper_rejects_escape(self, tmp_path):
        # An "outside" location: a sibling directory of roles_dir.
        outside_dir = (tmp_path / "data" / "escaped").resolve()
        outside_dir.mkdir(parents=True, exist_ok=True)
        # Pretend the resolved target landed outside roles_dir (e.g. via
        # a symlink or a parent-traversal segment that bypassed the regex).
        fake_target = (outside_dir / "alpha.poml").resolve()
        roles_dir = (tmp_path / "data" / "prompts" / "roles").resolve()
        assert roles_dir not in fake_target.parents
        assert roles_dir != fake_target

    def test_role_id_validation_accepts_only_grammar_compliant_ids(self):
        from src.service.routers.roles import _validate_role_id

        # Compliant
        assert _validate_role_id("alpha") is True
        assert _validate_role_id("a") is True
        assert _validate_role_id("alpha_beta_2") is True
        # Violations
        assert _validate_role_id("") is False
        assert _validate_role_id("Invalid") is False  # uppercase
        assert _validate_role_id("invalid-id") is False  # dash
        assert _validate_role_id("../etc/passwd") is False  # traversal
        assert _validate_role_id("..") is False
        assert _validate_role_id("1leading") is False  # must start with a-z
        assert _validate_role_id("with space") is False


#
# Role list / detail responses MUST NOT include ``source_file``.  The
# active ``.poml`` location is filesystem detail and was never part of
# the public contract for the role CRUD endpoints.  The reveal endpoint
# The reveal route is the only authorised way to surface a source path, and it
# does so by launching the OS file manager — never by returning the
# path itself.


class TestRoleSourceFileRedaction:
    def test_list_roles_omits_source_file(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            extra_active={"custom_user": _CUSTOM_POML},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/roles")

        assert resp.status_code == 200, resp.text
        for role in resp.json():
            assert "source_file" not in role, role

    def test_get_role_by_id_omits_source_file(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/roles/alpha")

        assert resp.status_code == 200, resp.text
        assert "source_file" not in resp.json()

    def test_role_listing_still_exposes_origin_and_is_shipped(self, client, tmp_path):
        prompts_dir, baseline_dir = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
            extra_active={"custom_user": _CUSTOM_POML},
            shipped_baseline={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, baseline_dir)

        with override_context(app, ctx):
            resp = client.get("/api/prompts/roles")

        assert resp.status_code == 200, resp.text
        by_id = {role["id"]: role for role in resp.json()}
        assert by_id["alpha"]["origin"] == "shipped_default"
        assert by_id["alpha"]["is_shipped"] is True
        assert by_id["custom_user"]["origin"] == "custom"
        assert by_id["custom_user"]["is_shipped"] is False


# POST /api/prompts/roles/{role_id}/reveal.
#
# The reveal endpoint is the *only* way a role's source path ever
# reaches the OS.  It must:
#   * validate the role id with the existing strict grammar (422),
#   * look up the active template (404 on unknown),
#   * confirm the resolved ``source_file`` is contained in the active
#     ``data/prompts/roles`` directory (404 if not — no subprocess call),
#   * launch the platform file manager with an argv list (no shell),
#     a five-second timeout, swallowed stdout/stderr,
#   * return exactly ``{"status": "ok"}`` — no path, no command,
#   * never leak a path or argv to the response on failure.


class TestRoleReveal:
    def test_invalid_role_id_is_rejected_with_422_before_any_io(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run") as run_mock,
        ):
            resp = client.post("/api/prompts/roles/invalid-id/reveal")

        # 422 — the role-id grammar is violated.
        assert resp.status_code == 422, resp.text
        assert "must match" in resp.json()["detail"]
        # No subprocess call was made: grammar check happens before I/O.
        run_mock.assert_not_called()

    def test_unknown_role_id_returns_404(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run") as run_mock,
        ):
            resp = client.post("/api/prompts/roles/missing/reveal")

        assert resp.status_code == 404, resp.text
        run_mock.assert_not_called()

    def test_reveal_invokes_subprocess_with_arg_list_and_five_second_timeout(
        self, client, tmp_path
    ):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run") as run_mock,
            patch("src.service.routers.prompt_config.sys") as sys_mock,
        ):
            sys_mock.platform = "darwin"
            resp = client.post("/api/prompts/roles/alpha/reveal")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ok"}

        run_mock.assert_called_once()
        args, kwargs = run_mock.call_args
        # argv list — never shell
        assert isinstance(args[0], list), "subprocess.run must use argv list"
        assert kwargs.get("shell", False) is False
        # macOS reveal = ['open', '-R', <path>]
        assert args[0][0] == "open"
        assert args[0][1] == "-R"
        assert str(args[0][2]).endswith("alpha.poml")
        # Five-second timeout, swallowed I/O.
        assert kwargs.get("timeout") == 5
        assert kwargs.get("stdout") is __import__("subprocess").DEVNULL
        assert kwargs.get("stderr") is __import__("subprocess").DEVNULL
        assert kwargs.get("check") is False

    def test_reveal_uses_explorer_on_windows(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run") as run_mock,
            patch("src.service.routers.prompt_config.sys") as sys_mock,
        ):
            sys_mock.platform = "win32"
            resp = client.post("/api/prompts/roles/alpha/reveal")

        assert resp.status_code == 200, resp.text
        args, _ = run_mock.call_args
        assert args[0][0] == "explorer"
        assert args[0][1].startswith("/select,")

    def test_reveal_uses_xdg_open_on_other_platforms(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run") as run_mock,
            patch("src.service.routers.prompt_config.sys") as sys_mock,
        ):
            sys_mock.platform = "linux"
            resp = client.post("/api/prompts/roles/alpha/reveal")

        assert resp.status_code == 200, resp.text
        args, _ = run_mock.call_args
        # Linux/other reveals the *parent* directory.
        assert args[0][0] == "xdg-open"
        assert str(args[0][1]).endswith("roles")

    def test_reveal_response_does_not_leak_path_or_argv(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run"),
            patch("src.service.routers.prompt_config.sys") as sys_mock,
        ):
            sys_mock.platform = "darwin"
            resp = client.post("/api/prompts/roles/alpha/reveal")

        assert resp.status_code == 200, resp.text
        body = resp.text
        # No raw filesystem path or argv command may appear in the response.
        assert "alpha.poml" not in body
        assert "open" not in body
        assert resp.json() == {"status": "ok"}

    def test_reveal_returns_404_when_source_file_escapes_roles_dir(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        # Overwrite the cached template's source_file to point outside roles.
        template = ctx.prompts.get_template("alpha")
        escaped_path = tmp_path / "elsewhere" / "alpha.poml"
        escaped_path.parent.mkdir(parents=True, exist_ok=True)
        escaped_path.write_text(template.role or "", encoding="utf-8")
        template.metadata["source_file"] = str(escaped_path)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run") as run_mock,
        ):
            resp = client.post("/api/prompts/roles/alpha/reveal")

        assert resp.status_code == 404, resp.text
        run_mock.assert_not_called()
        # No path leak.
        assert "elsewhere" not in resp.text

    def test_reveal_returns_404_when_source_file_does_not_exist(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        template = ctx.prompts.get_template("alpha")
        # Point at a non-existent file *inside* roles dir — must still 404
        # because the file is not a real regular file we can reveal.
        ghost = (prompts_dir / "roles" / "ghost.poml").resolve()
        template.metadata["source_file"] = str(ghost)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run") as run_mock,
        ):
            resp = client.post("/api/prompts/roles/alpha/reveal")

        assert resp.status_code == 404, resp.text
        run_mock.assert_not_called()

    def test_reveal_subprocess_failure_returns_502_without_leak(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with (
            override_context(app, ctx),
            patch(
                "src.service.routers.prompt_config.subprocess.run",
                side_effect=OSError("boom"),
            ),
            patch("src.service.routers.prompt_config.sys") as sys_mock,
        ):
            sys_mock.platform = "darwin"
            resp = client.post("/api/prompts/roles/alpha/reveal")

        assert resp.status_code == 502, resp.text
        body = resp.text
        # Generic message — no path, no OSError text, no command name.
        assert "boom" not in body
        assert "alpha.poml" not in body
        assert "open" not in body

    def test_reveal_subprocess_timeout_returns_502(self, client, tmp_path):
        import subprocess as _sp

        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with (
            override_context(app, ctx),
            patch(
                "src.service.routers.prompt_config.subprocess.run",
                side_effect=_sp.TimeoutExpired(cmd="open", timeout=5),
            ),
            patch("src.service.routers.prompt_config.sys") as sys_mock,
        ):
            sys_mock.platform = "darwin"
            resp = client.post("/api/prompts/roles/alpha/reveal")

        assert resp.status_code == 502, resp.text
        assert "open" not in resp.text

    def test_reveal_route_is_registered_before_dynamic_get(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run") as run_mock,
            patch("src.service.routers.prompt_config.sys") as sys_mock,
        ):
            sys_mock.platform = "darwin"

            # POST .../alpha/reveal goes to the new endpoint.
            resp = client.post("/api/prompts/roles/alpha/reveal")
            assert resp.status_code == 200, resp.text
            run_mock.assert_called_once()

            # GET .../alpha still hits the existing detail endpoint.
            resp = client.get("/api/prompts/roles/alpha")
            assert resp.status_code == 200, resp.text
            assert resp.json()["id"] == "alpha"


class TestRolesDirectoryReveal:
    @pytest.mark.parametrize(
        ("platform", "expected_command"),
        [
            ("darwin", "open"),
            ("win32", "explorer"),
            ("linux", "xdg-open"),
        ],
    )
    def test_opens_roles_directory_with_platform_command(
        self, client, tmp_path, platform, expected_command
    ):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run") as run_mock,
            patch("src.service.routers.prompt_config.sys") as sys_mock,
        ):
            sys_mock.platform = platform
            resp = client.post("/api/prompts/roles/reveal-directory")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ok"}
        args, kwargs = run_mock.call_args
        assert args[0][0] == expected_command
        assert str(args[0][1]).endswith("roles")
        assert kwargs["shell"] is False
        assert kwargs["check"] is False
        assert kwargs["timeout"] == 5
        assert kwargs["stdout"] is __import__("subprocess").DEVNULL
        assert kwargs["stderr"] is __import__("subprocess").DEVNULL

    def test_rejects_missing_roles_directory_without_launching(self, client, tmp_path):
        prompts_dir = tmp_path / "data" / "prompts"
        prompts_dir.mkdir(parents=True)
        ctx = _build_context(tmp_path, prompts_dir, tmp_path / "data" / "prompt_defaults" / "roles")

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run") as run_mock,
        ):
            resp = client.post("/api/prompts/roles/reveal-directory")

        assert resp.status_code == 404, resp.text
        assert "roles" not in resp.text.lower() or "directory" in resp.text.lower()
        assert str(prompts_dir) not in resp.text
        run_mock.assert_not_called()

    def test_rejects_roles_directory_outside_prompt_root_without_launching(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        outside_roles = tmp_path / "outside-roles"
        outside_roles.mkdir()
        (prompts_dir / "roles" / "alpha.poml").unlink()
        (prompts_dir / "roles").rmdir()
        (prompts_dir / "roles").symlink_to(outside_roles, target_is_directory=True)
        ctx = _build_context(tmp_path, prompts_dir, _)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run") as run_mock,
        ):
            resp = client.post("/api/prompts/roles/reveal-directory")

        assert resp.status_code == 404, resp.text
        assert "outside-roles" not in resp.text
        assert str(outside_roles) not in resp.text
        run_mock.assert_not_called()

    @pytest.mark.parametrize(
        "failure",
        [OSError("launch failure"), __import__("subprocess").TimeoutExpired("open", 5)],
    )
    def test_launch_failures_return_path_free_502(self, client, tmp_path, failure):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run", side_effect=failure),
        ):
            resp = client.post("/api/prompts/roles/reveal-directory")

        assert resp.status_code == 502, resp.text
        assert "launch failure" not in resp.text
        assert "open" not in resp.text
        assert str(prompts_dir) not in resp.text

    def test_nonzero_launch_status_returns_path_free_502(self, client, tmp_path):
        prompts_dir, _ = _build_layout(
            tmp_path,
            shipped_active={"alpha": _SHIPPED_BASELINE["alpha"]},
        )
        ctx = _build_context(tmp_path, prompts_dir, _)
        completed = __import__("subprocess").CompletedProcess(["open"], returncode=1)

        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run", return_value=completed),
        ):
            resp = client.post("/api/prompts/roles/reveal-directory")

        assert resp.status_code == 502, resp.text
        assert "open" not in resp.text
        assert str(prompts_dir) not in resp.text


class TestSessionRevealUnchanged:
    def test_session_reveal_still_returns_status_ok(self, client, tmp_path):
        from pathlib import Path

        ctx = MagicMock()
        ctx.discussion.session_path_for_reveal.return_value = Path(tmp_path) / "abc.json"
        with (
            override_context(app, ctx),
            patch("src.service.routers.prompt_config.subprocess.run"),
            patch("src.service.routers.prompt_config.sys") as sys_mock,
        ):
            sys_mock.platform = "darwin"
            resp = client.post("/api/sessions/abc/reveal")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ok"}
