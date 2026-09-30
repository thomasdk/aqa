"""Quick Action persistence and shipped-default contracts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.prompts.quick_actions import (
    QuickAction,
    QuickActionError,
    QuickActionRepository,
    provenance_for_actions,
    restore_all_shipped_actions,
    shipped_actions_need_restore,
)
from tests.router_test_support import override_context


def action(action_id: str, *, label: str | None = None, prompt: str | None = None) -> QuickAction:
    return QuickAction(
        id=action_id,
        label=label or action_id.title(),
        prompt=prompt or f"Prompt for {action_id}.",
    )


def test_repository_create_update_delete_preserves_order(tmp_path: Path) -> None:
    repository = QuickActionRepository(tmp_path)
    repository.create(action("first"))
    repository.create(action("second"))

    assert [item.id for item in repository.list()] == ["first", "second"]
    assert repository.update("first", label="Changed", prompt=None).label == "Changed"
    repository.delete("second")

    assert repository.list() == [action("first", label="Changed")]


def test_repository_rejects_malformed_or_duplicate_entries(tmp_path: Path) -> None:
    repository = QuickActionRepository(tmp_path)
    (tmp_path / "quick_actions.yaml").write_text(
        "quick_actions:\n  - id: duplicate\n    label: One\n    prompt: First\n"
        "  - id: duplicate\n    label: Two\n    prompt: Second\n",
        encoding="utf-8",
    )

    with pytest.raises(QuickActionError, match="unique"):
        repository.list()


def test_repository_preserves_configured_text_verbatim(tmp_path: Path) -> None:
    repository = QuickActionRepository(tmp_path)
    configured = QuickAction(
        id="verbatim",
        label="  Keep label spacing  ",
        prompt="\n  Preserve this multi-line instruction exactly.  \n",
    )

    repository.write([configured])

    assert repository.list() == [configured]


def test_shipped_provenance_marks_modified_and_custom_entries() -> None:
    baseline = [action("debate"), action("focus")]
    active = [action("debate", label="Debate differently"), action("custom")]

    assert [
        (item.id, shipped, origin)
        for item, shipped, origin in provenance_for_actions(active, baseline)
    ] == [
        ("debate", True, "shipped_modified"),
        ("custom", False, "custom"),
    ]


def test_bulk_restore_reinstates_deleted_defaults_and_keeps_custom_order() -> None:
    baseline = [action("debate"), action("focus")]
    active = [action("custom_one"), action("focus", label="Changed"), action("custom_two")]

    restored = restore_all_shipped_actions(active, baseline)

    assert restored == [
        action("debate"),
        action("focus"),
        action("custom_one"),
        action("custom_two"),
    ]


@pytest.mark.parametrize(
    ("active", "expected"),
    [
        ([action("debate"), action("focus"), action("custom")], False),
        ([action("debate")], True),
        ([action("debate", label="Changed"), action("focus")], True),
        ([action("custom"), action("focus"), action("debate")], False),
    ],
)
def test_restore_availability_tracks_missing_or_modified_defaults_only(
    active: list[QuickAction], expected: bool
) -> None:
    baseline = [action("debate"), action("focus")]

    assert shipped_actions_need_restore(active, baseline) is expected


def test_shipped_active_file_matches_baseline() -> None:
    root = Path(__file__).resolve().parents[1] / "data"
    assert (root / "prompts" / "quick_actions.yaml").read_bytes() == (
        root / "prompt_defaults" / "quick_actions.yaml"
    ).read_bytes()


def test_shipped_debate_and_explore_actions_use_the_current_prompts() -> None:
    prompts = Path(__file__).resolve().parents[1] / "data" / "prompts"
    actions = {action.id: action for action in QuickActionRepository(prompts).list()}

    assert actions["debate"].label == "Debate"
    assert actions["debate"].prompt == (
        "Continue the discussion by responding to the contributions of the previous round."
    )
    assert actions["explore"].label == "Explore"
    assert actions["explore"].prompt == (
        "Explore parts of the material and possible interpretations you previously ignored."
    )


def _context_for_actions(
    tmp_path: Path, active: list[QuickAction], baseline: list[QuickAction]
) -> MagicMock:
    prompts = tmp_path / "data" / "prompts"
    defaults = tmp_path / "data" / "prompt_defaults"
    QuickActionRepository(prompts).write(active)
    QuickActionRepository(defaults).write(baseline)
    context = MagicMock()
    context.settings.prompt_library_path = str(prompts)
    return context


def test_api_crud_and_restore_keep_custom_actions(tmp_path: Path) -> None:
    from src.api_server import app

    context = _context_for_actions(
        tmp_path,
        [action("debate", label="Changed"), action("custom")],
        [action("debate"), action("focus")],
    )
    with TestClient(app) as client, override_context(app, context):
        listed = client.get("/api/quick-actions")
        assert listed.status_code == 200
        assert listed.json()["actions"][0]["origin"] == "shipped_modified"
        assert listed.json()["can_restore_defaults"] is True

        created = client.post(
            "/api/quick-actions",
            json={"id": "new_action", "label": "New Action", "prompt": "New prompt."},
        )
        assert created.status_code == 201

        # A deleted shipped action must regain its shipped provenance through
        # the restore operation, not by creating a look-alike custom action.
        assert (
            client.post(
                "/api/quick-actions",
                json={"id": "focus", "label": "Focus", "prompt": "Replacement"},
            ).status_code
            == 409
        )

        updated = client.put("/api/quick-actions/new_action", json={"label": "Updated Action"})
        assert updated.status_code == 200
        assert updated.json()["prompt"] == "New prompt."

        restored = client.post("/api/quick-actions/restore-defaults")
        assert restored.status_code == 200
        assert [
            item.id for item in QuickActionRepository(tmp_path / "data" / "prompts").list()
        ] == ["debate", "focus", "custom", "new_action"]

        restored_list = client.get("/api/quick-actions")
        assert restored_list.json()["can_restore_defaults"] is False
