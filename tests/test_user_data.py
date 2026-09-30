"""Contracts for the packaged mutable-data boundary."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

import src.config.user_data as user_data
from src.config.settings import Settings
from src.config.user_data import (
    bootstrap_user_data,
    conversations_dir,
    local_ai_dir_path,
    prompt_defaults_dir,
    prompt_library_dir,
    settings_path,
)


def test_packaged_root_derives_all_mutable_paths(monkeypatch, tmp_path) -> None:
    root = tmp_path / "User Data"
    baseline = tmp_path / "app" / "prompt_defaults"
    monkeypatch.setenv("AQA_USER_DATA_DIR", str(root))
    monkeypatch.setenv("AQA_PROMPT_DEFAULTS_DIR", str(baseline))

    assert settings_path() == root / "settings.json"
    assert conversations_dir() == root / "conversations"
    assert prompt_library_dir() == root / "prompts"
    assert local_ai_dir_path() == root / "local-ai"
    assert prompt_defaults_dir() == baseline


def test_explicit_overrides_win_outside_packaged_mode(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AQA_USER_DATA_DIR", str(tmp_path / "User Data"))
    overrides = {
        "AQA_SETTINGS_PATH": tmp_path / "custom-settings.json",
        "AQA_CONVERSATIONS_DIR": tmp_path / "custom-conversations",
        "PROMPT_LIBRARY_PATH": tmp_path / "custom-prompts",
        "AQA_LOCAL_AI_DIR": tmp_path / "custom-local-ai",
    }
    for name, path in overrides.items():
        monkeypatch.setenv(name, str(path))

    assert settings_path() == overrides["AQA_SETTINGS_PATH"]
    assert conversations_dir() == overrides["AQA_CONVERSATIONS_DIR"]
    assert prompt_library_dir() == overrides["PROMPT_LIBRARY_PATH"]
    assert local_ai_dir_path() == overrides["AQA_LOCAL_AI_DIR"]


def test_packaged_mode_ignores_inherited_mutable_path_overrides(monkeypatch, tmp_path) -> None:
    root = tmp_path / "User Data"
    monkeypatch.setenv("AQA_PACKAGED_MODE", "1")
    monkeypatch.setenv("AQA_USER_DATA_DIR", str(root))
    for name, path in {
        "AQA_SETTINGS_PATH": tmp_path / "outside-settings.json",
        "AQA_CONVERSATIONS_DIR": tmp_path / "outside-conversations",
        "PROMPT_LIBRARY_PATH": tmp_path / "outside-prompts",
        "AQA_LOCAL_AI_DIR": tmp_path / "outside-local-ai",
        "AQA_PROMPT_DEFAULTS_DIR": tmp_path / "outside-prompt-defaults",
    }.items():
        monkeypatch.setenv(name, str(path))

    assert settings_path() == root / "settings.json"
    assert conversations_dir() == root / "conversations"
    assert prompt_library_dir() == root / "prompts"
    assert local_ai_dir_path() == root / "local-ai"
    assert prompt_defaults_dir() != tmp_path / "outside-prompt-defaults"


def test_portable_settings_ignore_environment_prompt_root_overrides(monkeypatch, tmp_path) -> None:
    root = tmp_path / "User Data"
    monkeypatch.setenv("AQA_PACKAGED_MODE", "1")
    monkeypatch.setenv("AQA_USER_DATA_DIR", str(root))
    monkeypatch.setenv("PROMPT_LIBRARY_PATH", str(tmp_path / "outside-prompts"))
    monkeypatch.setenv("PROMPT_DEFAULTS_PATH", str(tmp_path / "outside-defaults"))

    settings = Settings(_env_file=None)

    assert settings.prompt_library_path == str(root / "prompts")
    assert settings.prompt_defaults_path == str(prompt_defaults_dir())


def test_packaged_mode_requires_a_user_data_directory(monkeypatch) -> None:
    monkeypatch.setenv("AQA_PACKAGED_MODE", "1")
    monkeypatch.delenv("AQA_USER_DATA_DIR", raising=False)

    with pytest.raises(RuntimeError, match="AQA_USER_DATA_DIR"):
        settings_path()
    with pytest.raises(RuntimeError, match="AQA_USER_DATA_DIR"):
        bootstrap_user_data()


def test_bootstrap_seeds_once_and_keeps_immutable_baseline_separate(monkeypatch, tmp_path) -> None:
    root = tmp_path / "User Data"
    monkeypatch.setenv("AQA_USER_DATA_DIR", str(root))

    assert bootstrap_user_data() == root
    seeded = root / "prompts" / "prompts_globals.poml"
    original = seeded.read_text(encoding="utf-8")
    seeded.write_text("user edit", encoding="utf-8")

    bootstrap_user_data()

    assert seeded.read_text(encoding="utf-8") == "user edit"
    assert original != "user edit"
    assert prompt_defaults_dir() != root / "prompts"
    assert json.loads((root / "manifest.json").read_text(encoding="utf-8"))["data_schema"] == 1
    assert "API credentials" in (root / "README.txt").read_text(encoding="utf-8")


def test_concurrent_first_bootstrap_creates_a_complete_prompt_library(
    monkeypatch, tmp_path
) -> None:
    root = tmp_path / "User Data"
    monkeypatch.setenv("AQA_USER_DATA_DIR", str(root))

    with ThreadPoolExecutor(max_workers=8) as executor:
        roots = list(executor.map(lambda _: bootstrap_user_data(), range(8)))

    assert roots == [root] * 8
    assert (root / "prompts" / "session_contexts" / "exploration.md").is_file()
    assert (root / "prompts" / "session_contexts" / "critique.md").is_file()


def test_bootstrap_keeps_a_modified_prompt_asset(monkeypatch, tmp_path) -> None:
    root = tmp_path / "User Data"
    monkeypatch.setenv("AQA_USER_DATA_DIR", str(root))
    bootstrap_user_data()

    prompt_asset = root / "prompts" / "prompts_globals.poml"
    custom_content = b"custom prompt edit\n"
    prompt_asset.write_bytes(custom_content)

    bootstrap_user_data()

    assert prompt_asset.read_bytes() == custom_content


def _configure_portable_prompt_fixture(monkeypatch, tmp_path):
    """Point portable bootstrap at a minimal shipped prompt tree."""

    app_root = tmp_path / "app"
    shipped = app_root / "data" / "prompts"
    (shipped / "roles").mkdir(parents=True)
    (shipped / "prompts_globals.poml").write_text("source globals\n", encoding="utf-8")
    (shipped / "roles" / "source.poml").write_text("source role\n", encoding="utf-8")
    (app_root / "data" / "prompt_defaults").mkdir(parents=True)
    root = tmp_path / "User Data"
    monkeypatch.setattr(user_data, "_PROJECT_ROOT", app_root)
    monkeypatch.setenv("AQA_PACKAGED_MODE", "1")
    monkeypatch.setenv("AQA_USER_DATA_DIR", str(root))
    return root, shipped


def test_source_sync_replaces_the_entire_active_prompt_tree(monkeypatch, tmp_path) -> None:
    root, shipped = _configure_portable_prompt_fixture(monkeypatch, tmp_path)
    bootstrap_user_data()
    prompts = root / "prompts"
    (prompts / "prompts_globals.poml").write_text("test edit\n", encoding="utf-8")
    (prompts / "obsolete.poml").write_text("old source file\n", encoding="utf-8")
    (shipped / "roles" / "source.poml").unlink()
    (shipped / "session_contexts").mkdir()
    (shipped / "session_contexts" / "new.md").write_text("new source file\n", encoding="utf-8")
    settings = root / "settings.json"
    settings.write_text("settings stay put\n", encoding="utf-8")
    conversation = root / "conversations" / "saved.json"
    conversation.write_text("conversation stays put\n", encoding="utf-8")
    local_ai = root / "local-ai" / "model.bin"
    local_ai.write_text("local AI stays put\n", encoding="utf-8")

    monkeypatch.setenv("AQA_SYNC_PROMPTS_FROM_SOURCE", "1")
    bootstrap_user_data()

    assert (prompts / "prompts_globals.poml").read_text(encoding="utf-8") == "source globals\n"
    assert (prompts / "session_contexts" / "new.md").read_text(
        encoding="utf-8"
    ) == "new source file\n"
    assert not (prompts / "roles" / "source.poml").exists()
    assert not (prompts / "obsolete.poml").exists()
    assert settings.read_text(encoding="utf-8") == "settings stay put\n"
    assert conversation.read_text(encoding="utf-8") == "conversation stays put\n"
    assert local_ai.read_text(encoding="utf-8") == "local AI stays put\n"


def test_source_sync_copy_failure_keeps_existing_prompts(monkeypatch, tmp_path) -> None:
    root, _shipped = _configure_portable_prompt_fixture(monkeypatch, tmp_path)
    bootstrap_user_data()
    prompts = root / "prompts"
    active_prompt = prompts / "prompts_globals.poml"
    active_prompt.write_text("test edit\n", encoding="utf-8")
    monkeypatch.setenv("AQA_SYNC_PROMPTS_FROM_SOURCE", "1")

    def fail_copytree(*_args, **_kwargs):
        raise OSError("simulated copy failure")

    monkeypatch.setattr(user_data.shutil, "copytree", fail_copytree)

    with pytest.raises(OSError, match="simulated copy failure"):
        bootstrap_user_data()

    assert active_prompt.read_text(encoding="utf-8") == "test edit\n"
