"""Tests for prompt-repository reload and settings validation."""

from src.config.settings import Settings
from src.prompts.storage import PromptRepository


class TestPromptRepositoryReload:
    def test_reload_clears_and_reloads(self, tmp_path):
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()

        (roles_dir / "test_role.poml").write_text(
            '<prompts><prompt id="test_role" label="Test">'
            "<role>Du bist ein Test.</role>"
            "</prompt></prompts>",
            encoding="utf-8",
        )

        repo = PromptRepository(base_path=tmp_path)
        assert repo.get_template("test_role") is not None

        (roles_dir / "neue_rolle.poml").write_text(
            '<prompts><prompt id="neue_rolle" label="Neu">'
            "<role>Ich bin neu.</role>"
            "</prompt></prompts>",
            encoding="utf-8",
        )

        repo.reload()

        assert repo.get_template("neue_rolle") is not None
        assert repo.get_template("test_role") is not None

    def test_reload_removes_deleted_templates(self, tmp_path):
        poml_file = tmp_path / "to_delete.poml"
        poml_file.write_text(
            '<prompts><prompt id="delete_me" label="Lösch mich">'
            "<role>Bald weg.</role>"
            "</prompt></prompts>",
            encoding="utf-8",
        )

        repo = PromptRepository(base_path=tmp_path)
        assert repo.get_template("delete_me") is not None

        poml_file.unlink()
        repo.reload()

        assert repo.get_template("delete_me") is None

    def test_reload_updates_modified_content(self, tmp_path):
        poml_file = tmp_path / "changing.poml"
        poml_file.write_text(
            '<prompts><prompt id="changing" label="Alt">'
            "<role>Alte Rolle.</role>"
            "</prompt></prompts>",
            encoding="utf-8",
        )

        repo = PromptRepository(base_path=tmp_path)
        tpl = repo.get_template("changing")
        assert tpl.label == "Alt"

        poml_file.write_text(
            '<prompts><prompt id="changing" label="Neu">'
            "<role>Neue Rolle.</role>"
            "</prompt></prompts>",
            encoding="utf-8",
        )

        repo.reload()
        tpl = repo.get_template("changing")
        assert tpl.label == "Neu"
        assert tpl.role == "Neue Rolle."


class TestSettingsValidation:
    def test_default_settings_valid(self):
        s = Settings(_env_file=None)
        assert "known_llm_hosts" in s.model_dump()
        assert s.llm_timeout == 120
