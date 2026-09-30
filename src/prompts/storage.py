"""File-backed storage for prompt templates and fragments."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from loguru import logger

from .models import (
    GlobalPromptBlock,
    PromptContextBlock,
    PromptRecord,
    PromptRenderResult,
    PromptSlot,
    PromptTemplate,
)


class PromptRepository:
    """Manage prompt files within one library directory."""

    def __init__(self, *, base_path: Path, library_glob: str = "**/*.poml") -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.library_glob = library_glob
        self._template_cache: dict[str, PromptTemplate] = {}
        self._global_cache: dict[str, GlobalPromptBlock] = {}
        self._template_index: dict[Path, list[str]] = {}
        self._global_index: dict[Path, list[str]] = {}
        self._library_mtimes: dict[Path, float] = {}
        self._refresh_library()

    def _path_for(self, prompt_id: str) -> Path:
        return self.base_path / "user" / f"{prompt_id}.json"

    def _refresh_library(self) -> None:
        """Reload changed POML files and update the caches."""

        library_dir = self.base_path
        user_dir = library_dir / "user"
        user_dir.mkdir(exist_ok=True, parents=True)

        available_files = {path for path in library_dir.glob(self.library_glob)}

        for file_path in list(self._template_index.keys()):
            if file_path not in available_files:
                for template_id in self._template_index.pop(file_path, []):
                    self._template_cache.pop(template_id, None)
                for global_id in self._global_index.pop(file_path, []):
                    self._global_cache.pop(global_id, None)
                self._library_mtimes.pop(file_path, None)

        for file_path in available_files:
            try:
                mtime = file_path.stat().st_mtime
            except OSError as error:  # pragma: no cover - unreadable source file
                logger.warning("Cannot read POML file {path}: {error}", path=file_path, error=error)
                continue

            if self._library_mtimes.get(file_path) == mtime:
                continue

            templates, globals_ = self._parse_poml_file(file_path)

            for template_id in self._template_index.get(file_path, []):
                self._template_cache.pop(template_id, None)
            for global_id in self._global_index.get(file_path, []):
                self._global_cache.pop(global_id, None)

            collected_ids: list[str] = []
            for template in templates:
                if template.id in self._template_cache:
                    logger.warning(
                        "Duplicate prompt ID {template_id} in {path}; replacing the existing template.",
                        template_id=template.id,
                        path=file_path,
                    )
                template.metadata.setdefault("source_file", str(file_path))
                self._template_cache[template.id] = template
                collected_ids.append(template.id)

            collected_global_ids: list[str] = []
            for block in globals_:
                block.metadata.setdefault("source_file", str(file_path))
                self._global_cache[block.id] = block
                collected_global_ids.append(block.id)

            self._template_index[file_path] = collected_ids
            self._global_index[file_path] = collected_global_ids
            self._library_mtimes[file_path] = mtime

    def _parse_poml_file(
        self, file_path: Path
    ) -> tuple[list[PromptTemplate], list[GlobalPromptBlock]]:
        """Parse a POML file into template and global instruction models."""

        try:
            tree = ET.parse(file_path)
        except ET.ParseError as error:
            logger.error("Invalid POML file {path}: {error}", path=file_path, error=error)
            return [], []

        root = tree.getroot()

        def clean_text(node) -> str | None:
            if node is None:
                return None
            text = node.text or ""
            return text.strip()

        templates: list[PromptTemplate] = []
        for prompt_node in root.findall("prompt"):
            template_id = prompt_node.get("id")
            if not template_id:
                logger.warning("Skipping prompt without an ID in {path}", path=file_path)
                continue
            label = prompt_node.get("label") or template_id

            description_text = clean_text(prompt_node.find("description"))
            role_text = clean_text(prompt_node.find("role"))
            task_text = clean_text(prompt_node.find("task"))
            output_text = clean_text(prompt_node.find("output-format"))

            contexts: list[PromptContextBlock] = []
            for context_node in prompt_node.findall("context"):
                context_label = context_node.get("label") or "Kontext"
                contexts.append(
                    PromptContextBlock(
                        label=context_label,
                        content=clean_text(context_node) or "",
                    )
                )

            metadata: dict[str, object] = {
                "source_file": str(file_path),
                "label": label,
            }

            templates.append(
                PromptTemplate(
                    id=template_id,
                    label=label,
                    description=description_text,
                    role=role_text,
                    task=task_text,
                    contexts=contexts,
                    output_format=output_text,
                    metadata=metadata,
                )
            )

        globals_: list[GlobalPromptBlock] = []
        for global_node in root.findall("global"):
            global_id = global_node.get("id")
            if not global_id:
                logger.warning("Skipping global block without an ID in {path}", path=file_path)
                continue
            label = global_node.get("label") or global_id
            scope = global_node.get("scope")  # ``multi_agent`` limits the block to that mode.
            content = clean_text(global_node.find("content")) or ""

            globals_.append(
                GlobalPromptBlock(
                    id=global_id,
                    label=label,
                    content=content,
                    scope=scope,
                    metadata={"source_file": str(file_path)},
                )
            )

        return templates, globals_

    def reload(self) -> None:
        """Clear caches and reload every POML file."""
        self._template_cache.clear()
        self._global_cache.clear()
        self._template_index.clear()
        self._global_index.clear()
        self._library_mtimes.clear()
        self._refresh_library()
        logger.info(
            "Reloaded prompt repository: "
            f"{len(self._template_cache)} templates, {len(self._global_cache)} globals"
        )

    def list_templates(self) -> list[PromptTemplate]:
        """Return all available templates sorted by label."""

        self._refresh_library()
        return sorted(self._template_cache.values(), key=lambda item: item.label.lower())

    def get_template(self, template_id: str) -> PromptTemplate | None:
        """Return one template from the cache."""

        self._refresh_library()
        return self._template_cache.get(template_id)

    def list_globals(self) -> list[GlobalPromptBlock]:
        """Return every global instruction block."""

        self._refresh_library()
        return list(self._global_cache.values())

    def get_global(self, global_id: str) -> GlobalPromptBlock | None:
        """Return one global instruction block from the cache."""

        self._refresh_library()
        return self._global_cache.get(global_id)

    def get_common_instructions(self, multi_agent: bool = False) -> str:
        """Build the applicable global instruction text for the selected mode."""
        self._refresh_library()
        blocks = []
        for block in self._global_cache.values():
            if block.scope == "synthesis":
                continue
            if block.scope == "multi_agent" and not multi_agent:
                continue
            blocks.append(f"=== {block.label.upper()} ===\n{block.content}")

        if not blocks:
            # Preserve the minimum instruction contract when no global blocks exist.
            return "=== TECHNICAL REQUIREMENTS ===\nDO NOT use Markdown tables."

        return "\n\n".join(blocks)

    def render_template(
        self,
        template_id: str,
        *,
        placeholders: Mapping[str, object] | None = None,
        overrides: Mapping[str, object] | None = None,
        additional_fragments: Sequence[str | PromptRecord] | None = None,
    ) -> PromptRenderResult:
        """Render a template with placeholders and optional overrides."""

        template = self.get_template(template_id)
        if template is None:
            raise KeyError(f"Unbekanntes Prompt-Template: {template_id}")

        resolved_overrides: dict[str, object] = {}
        if overrides:
            for key, value in overrides.items():
                if key == "contexts":
                    resolved_list: list[object] = []
                    if not isinstance(value, Iterable):
                        raise TypeError("contexts override muss eine Iterable sein")
                    for item in value:
                        resolved_list.append(
                            self._resolve_fragment_input(item, expected_slot="context")
                        )
                    resolved_overrides[key] = resolved_list
                else:
                    resolved_overrides[key] = self._resolve_fragment_input(value, expected_slot=key)

        resolved_fragments: list[PromptRecord] = []
        if additional_fragments:
            for fragment in additional_fragments:
                resolved = self._resolve_fragment_input(fragment)
                if isinstance(resolved, PromptRecord):
                    resolved_fragments.append(resolved)
                else:
                    resolved_fragments.append(
                        PromptRecord(name="Custom", content=str(resolved), tags=[], slot="custom")
                    )

        return template.render(
            placeholders=placeholders,
            overrides=resolved_overrides,
            additional_fragments=resolved_fragments,
        )

    def _resolve_fragment_input(
        self,
        value: object,
        *,
        expected_slot: str | None = None,
    ) -> PromptRecord | PromptContextBlock | Mapping[str, object] | str:
        """Resolve a fragment value to its structured representation."""

        if isinstance(value, PromptRecord):
            if expected_slot and value.slot not in {expected_slot, "custom"}:
                logger.debug(
                    "Prompt slot mismatch: expected {expected}, received {actual}",
                    expected=expected_slot,
                    actual=value.slot,
                )
            return value
        if isinstance(value, PromptContextBlock):
            return value
        if isinstance(value, Mapping):
            return value
        if isinstance(value, str):
            record = self.get_prompt(value)
            if record is None:
                raise KeyError(f"Prompt-Fragment nicht gefunden: {value}")
            return record
        raise TypeError(f"Unbekannter Fragment-Typ: {type(value)!r}")

    def list_prompts(self) -> list[PromptRecord]:
        """Read and return persisted prompts ordered by most recent update."""

        user_dir = self.base_path / "user"
        user_dir.mkdir(exist_ok=True, parents=True)

        records: list[PromptRecord] = []
        files = sorted(user_dir.glob("*.json"), key=lambda item: item.name)
        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")
                record = PromptRecord.model_validate_json(content)
                records.append(record)
            except Exception as error:  # pragma: no cover - defensive logging
                logger.warning(
                    "Skipping invalid prompt file {path}: {error}", path=file_path, error=error
                )
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return records

    def get_prompt(self, prompt_id: str) -> PromptRecord | None:
        """Load a persisted prompt by ID."""

        file_path = self._path_for(prompt_id)
        if not file_path.exists():
            return None
        content = file_path.read_text(encoding="utf-8")
        return PromptRecord.model_validate_json(content)

    def save_prompt(
        self,
        *,
        name: str,
        content: str,
        tags: Iterable[str] | None = None,
        metadata: dict[str, object] | None = None,
        prompt_id: str | None = None,
        slot: PromptSlot = "custom",
        template_id: str | None = None,
    ) -> PromptRecord:
        """Create or update a persisted prompt."""

        existing = self.get_prompt(prompt_id) if prompt_id else None
        tags_list = list(tags) if tags is not None else (existing.tags if existing else [])
        metadata_dict = (
            dict(metadata) if metadata is not None else (existing.metadata if existing else {})
        )

        if existing:
            record = existing.updated_copy(
                name=name,
                content=content,
                tags=tags_list,
                metadata=metadata_dict,
                slot=slot,
                template_id=template_id,
            )
        else:
            init_args = {
                "name": name,
                "content": content,
                "tags": tags_list,
                "metadata": metadata_dict,
                "slot": slot,
                "template_id": template_id,
            }
            if prompt_id:
                init_args["id"] = prompt_id
            record = PromptRecord(**init_args)

        file_path = self._path_for(record.id)
        file_path.parent.mkdir(exist_ok=True, parents=True)
        payload = record.model_dump_json(indent=2)
        file_path.write_text(payload, encoding="utf-8")
        logger.info(
            "Saved prompt {prompt_id} ({name})",
            prompt_id=record.id,
            name=record.name,
        )
        return record

    def delete_prompt(self, prompt_id: str) -> bool:
        """Delete a persisted prompt file."""

        file_path = self._path_for(prompt_id)
        if not file_path.exists():
            return False
        file_path.unlink()
        logger.info("Deleted prompt {prompt_id}", prompt_id=prompt_id)
        return True
