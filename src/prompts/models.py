"""Typed models for reusable prompt templates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_serializer

PromptSlot = Literal["role", "task", "context", "output_format", "prefix", "suffix", "custom"]


class GlobalPromptBlock(BaseModel):
    """A reusable instruction block loaded from a POML ``<global>`` element."""

    id: str
    label: str
    content: str
    scope: str | None = None  # ``multi_agent`` applies only to multi-agent discussions.
    metadata: dict[str, object] = Field(default_factory=dict)


class PromptContextBlock(BaseModel):
    """A labelled context section within a template."""

    label: str
    content: str


class PromptRenderResult(BaseModel):
    """The rendered prompt and its source segments."""

    template_id: str
    prompt_text: str
    segments: dict[str, str]
    metadata: dict[str, object] = Field(default_factory=dict)


class PromptRecord(BaseModel):
    """A persisted reusable prompt fragment."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    content: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
    slot: PromptSlot = Field(default="custom")
    template_id: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_serializer("created_at", "updated_at")
    @classmethod
    def _serialize_dt(cls, value: datetime) -> str:
        return value.isoformat()

    def updated_copy(self, **updates: object) -> PromptRecord:
        """Return a copy with an updated timestamp."""

        payload = {**updates, "updated_at": datetime.now(UTC)}
        return self.model_copy(update=payload)


class PromptTemplate(BaseModel):
    """A structured prompt template composed of independently rendered segments."""

    id: str
    label: str
    # UI catalogue copy only.  Keeping this outside the rendered prompt
    # segments ensures a perspective description is never sent to a model.
    description: str | None = None
    role: str | None = None
    task: str | None = None
    contexts: list[PromptContextBlock] = Field(default_factory=list)
    output_format: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @staticmethod
    def _resolve_text(source: str | None, placeholders: Mapping[str, object]) -> str | None:
        if source is None:
            return None
        text = str(source)
        for key, value in placeholders.items():
            text = text.replace(f"{{{{{key}}}}}", str(value))
        return text

    def _override_text(
        self, slot: str, overrides: Mapping[str, object], placeholders: Mapping[str, object]
    ) -> str | None:
        value = overrides.get(slot)
        if value is None:
            return None
        source = value.content if isinstance(value, PromptRecord) else str(value)
        return self._resolve_text(source, placeholders)

    def _context_blocks(self, overrides: Mapping[str, object]) -> list[PromptContextBlock]:
        value = overrides.get("contexts")
        if value is None:
            return self.contexts
        if not isinstance(value, Iterable):
            raise TypeError("contexts override must be iterable")
        blocks: list[PromptContextBlock] = []
        for item in value:
            if isinstance(item, PromptRecord):
                blocks.append(PromptContextBlock(label=item.name, content=item.content))
            elif isinstance(item, PromptContextBlock):
                blocks.append(item)
            elif isinstance(item, Mapping):
                blocks.append(
                    PromptContextBlock(
                        label=str(item.get("label", "Context")),
                        content=str(item.get("content", "")),
                    )
                )
            else:
                raise TypeError("Unsupported context override type")
        return blocks

    def _set_rendered_slot(
        self,
        segments: dict[str, str],
        slot: str,
        source: str | None,
        overrides: Mapping[str, object],
        placeholders: Mapping[str, object],
    ) -> None:
        text = self._override_text(slot, overrides, placeholders) or self._resolve_text(
            source, placeholders
        )
        if text:
            segments[slot] = text

    def render(
        self,
        *,
        placeholders: Mapping[str, object] | None = None,
        overrides: Mapping[str, object] | None = None,
        additional_fragments: Iterable[PromptRecord] | None = None,
    ) -> PromptRenderResult:
        """Render the prompt text and retain its semantic segments."""

        placeholders = placeholders or {}
        overrides = overrides or {}
        segments: dict[str, str] = {}

        self._set_rendered_slot(segments, "role", self.role, overrides, placeholders)
        self._set_rendered_slot(segments, "task", self.task, overrides, placeholders)

        context_segments: list[str] = []
        for block in self._context_blocks(overrides):
            content = self._resolve_text(block.content, placeholders)
            context_segments.append(f"{block.label}:\n{content}")

        if context_segments:
            segments["contexts"] = "\n\n".join(context_segments)

        self._set_rendered_slot(
            segments, "output_format", self.output_format, overrides, placeholders
        )

        if additional_fragments:
            custom_parts = []
            for fragment in additional_fragments:
                content = self._resolve_text(fragment.content, placeholders)
                custom_parts.append(content)
            if custom_parts:
                segments["custom"] = "\n\n".join(custom_parts)

        prompt_text = "\n\n".join(segments.values())
        return PromptRenderResult(
            template_id=self.id,
            prompt_text=prompt_text,
            segments=segments,
            metadata=dict(self.metadata),
        )
