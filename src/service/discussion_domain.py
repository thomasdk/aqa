"""Domain records and state invariants for multi-agent discussions."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.llm.errors import truncate_error
from src.prompts import (
    SessionInputDefinition,
    SessionTypeRepository,
    default_session_inputs,
    normalize_session_input_values,
    validate_session_inputs,
)
from src.prompts.session_types import normalize_session_type_key
from src.service.discussion_text import MATERIAL_TYPES

DEFAULT_SESSION_TYPE = "exploration"


def _discover_default_session_contexts_dir() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    candidates = [
        project_root / "data" / "prompts" / "session_contexts",
        Path("./data/prompts/session_contexts"),
    ]
    return next((path for path in candidates if path.exists()), candidates[0])


def _build_module_level_session_types() -> tuple[
    dict[str, dict[str, str]],
    dict[str, list[str]],
]:
    base = _discover_default_session_contexts_dir()
    if not base.exists():
        return {}, {}
    try:
        definitions = SessionTypeRepository(base_path=base).list()
    except Exception:
        return {}, {}
    sessions = {
        item.key: {"label": item.label, "description": item.description} for item in definitions
    }
    agents = {item.key: list(item.default_agent_prompt_ids) for item in definitions}
    return sessions, agents


SESSION_TYPES, DEFAULT_AGENT_PROMPTS_BY_SESSION_TYPE = _build_module_level_session_types()


@dataclass
class MaterialContext:
    """Research-material metadata injected into agent prompts."""

    material_type: str = "document"
    session_type: str = DEFAULT_SESSION_TYPE
    # Empty retains the material-language default.  This is deliberately
    # separate from the application's UI locale.
    target_language: str = ""
    # Saved sessions carry this schema snapshot so a later edit to a session
    # type cannot reinterpret the setup data that produced a discussion.
    session_input_values: dict[str, str] = field(default_factory=normalize_session_input_values)
    session_inputs: list[SessionInputDefinition] = field(default_factory=default_session_inputs)
    # This is a session-type policy captured when a discussion starts. It is
    # deliberately snapshot metadata, not a value supplied with user input.
    include_unchanged_research_material_context_in_prompt: bool = False

    def __post_init__(self) -> None:
        self.session_type = normalize_session_type_key(self.session_type)
        self.target_language = str(self.target_language or "").strip()
        self.session_input_values = normalize_session_input_values(self.session_input_values)
        self.session_inputs = validate_session_inputs(self.session_inputs)
        self.include_unchanged_research_material_context_in_prompt = bool(
            self.include_unchanged_research_material_context_in_prompt
        )

    def set_session_inputs(self, definitions: list[SessionInputDefinition]) -> None:
        self.session_inputs = validate_session_inputs(definitions)

    @property
    def type_label(self) -> str:
        return MATERIAL_TYPES.get(self.material_type, "Material")

    @property
    def session_label(self) -> str:
        return SESSION_TYPES.get(self.session_type, {}).get("label", "Session")


@dataclass
class AgentConfig:
    """Persistable configuration and execution invariant for one agent."""

    name: str
    client_id: str | None = None
    prompt_id: str | None = None
    color: str = "#333333"
    temperature: float | None = None
    llm_id: str | None = None
    api_host: str | None = None
    host_configuration_id: str | None = None
    host_label: str | None = None
    api_key: str | None = None
    max_tokens: int | None = None
    enabled: bool = True
    # Stable visible identity.  Unlike ``agent_index`` this value survives
    # reordering and is copied to generated messages for stable labels.
    perspective_number: int = 0

    @property
    def is_active(self) -> bool:
        return self.enabled and isinstance(self.prompt_id, str) and bool(self.prompt_id.strip())


@dataclass
class SynthesisConfig:
    """Non-secret execution settings for the optional round synthesis."""

    enabled: bool
    api_host: str | None
    llm_id: str | None
    # ``None`` means that the provider receives no temperature override.
    temperature: float | None = None
    host_configuration_id: str | None = None
    host_label: str | None = None


@dataclass
class AgentResponse:
    """One streaming or terminal agent response."""

    message_id: str
    agent_index: int
    agent_name: str
    theory_label: str
    color: str
    text: str
    client_id: str | None = None
    perspective_number: int = 0
    is_complete: bool = False
    # ``completed`` means the provider finished successfully.  A response
    # with visible text can instead be ``interrupted`` or ``failed`` and must
    # remain durable without being presented as a successful answer.
    status: str = "in_progress"
    error: str | None = None
    error_code: str | None = None
    error_params: dict[str, Any] = field(default_factory=dict)
    # ``None`` means that no provider request was started (for example a
    # Local-AI preflight rejection). ``False`` means a request completed or
    # failed without a valid OpenAI-compatible ``usage`` object.
    usage_available: bool | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    context_usage_available: bool | None = None
    input_context_tokens: int | None = None
    context_window_tokens: int | None = None
    context_tokens_exact: bool | None = None
    omitted_round_numbers: tuple[int, ...] = ()


@dataclass
class SynthesisResponse:
    """One streaming or terminal round-synthesis response."""

    message_id: str
    text: str
    round_number: int
    is_complete: bool = False
    status: str = "in_progress"
    error: str | None = None
    error_code: str | None = None
    error_params: dict[str, Any] = field(default_factory=dict)
    usage_available: bool | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    context_usage_available: bool | None = None
    input_context_tokens: int | None = None
    context_window_tokens: int | None = None
    context_tokens_exact: bool | None = None


@dataclass(frozen=True)
class ContextUsage:
    """One preflight token measurement for an imminent agent request."""

    available: bool
    # ``True`` when the configured provider counted the exact final chat
    # request.  The bundled tokenizer deliberately remains useful when a
    # provider does not implement the optional OpenAI-compatible endpoint,
    # but its result is only an estimate of the provider's chat template.
    exact: bool = False
    material_tokens: int | None = None
    discussion_tokens: int | None = None
    other_tokens: int | None = None
    input_tokens: int | None = None
    context_tokens: int | None = None
    # These are request-local audit facts.  They never change the persisted
    # transcript or a user's include/exclude choice; callers recompute them
    # for each request from the current context-window setting.
    omitted_round_numbers: tuple[int, ...] = ()


@dataclass
class DiscussionMessage:
    """One path- and secret-free entry in the discussion audit log."""

    id: str
    role: str
    content: str
    round_number: int = 1
    status: str = "completed"
    agent_name: str | None = None
    theory_label: str | None = None
    color: str | None = None
    agent_index: int | None = None
    perspective_number: int | None = None
    note: str = ""
    include_note_in_agent_context: bool = False
    error: str | None = None
    error_code: str | None = None
    error_params: dict[str, Any] = field(default_factory=dict)
    include_in_agent_context: bool = True
    client_id: str | None = None
    usage_available: bool | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    context_usage_available: bool | None = None
    input_context_tokens: int | None = None
    context_window_tokens: int | None = None
    context_tokens_exact: bool | None = None
    omitted_round_numbers: tuple[int, ...] = ()


@dataclass
class DiscussionState:
    """Mutable discussion state with message and context invariants."""

    material: str = ""
    initial_question: str = ""
    messages: list[DiscussionMessage] = field(default_factory=list)
    round_number: int = 0
    round_status: str | None = None

    def add_user_message(
        self,
        content: str,
        *,
        message_id: str | None = None,
    ) -> DiscussionMessage:
        message = DiscussionMessage(
            id=message_id or str(uuid4()),
            role="user",
            content=content,
            round_number=max(1, self.round_number),
        )
        self.messages.append(message)
        return message

    def add_agent_response(self, response: AgentResponse) -> DiscussionMessage:
        return self.upsert_agent_response(response)

    def upsert_agent_response(
        self, response: AgentResponse, *, append_text: bool = False
    ) -> DiscussionMessage:
        """Insert or update one agent card without duplicating streamed output."""
        text = response.text or ""
        response_status = "completed" if response.is_complete else response.status
        error = truncate_error(response.error) if response.error else None
        message = DiscussionMessage(
            id=response.message_id,
            role="agent",
            # Provider output and failure metadata are separate durable fields.
            # Embedding the error here would render it twice and contaminate
            # later transcript/export handling.
            content=text,
            round_number=max(1, self.round_number),
            status=response_status,
            agent_name=response.agent_name,
            theory_label=response.theory_label,
            color=response.color,
            agent_index=response.agent_index,
            perspective_number=response.perspective_number or None,
            error=error,
            error_code=response.error_code,
            error_params=dict(response.error_params),
            client_id=response.client_id,
            usage_available=response.usage_available,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            context_usage_available=response.context_usage_available,
            input_context_tokens=response.input_context_tokens,
            context_window_tokens=response.context_window_tokens,
            context_tokens_exact=response.context_tokens_exact,
            omitted_round_numbers=tuple(response.omitted_round_numbers),
        )
        existing_index = next(
            (index for index, item in enumerate(self.messages) if item.id == message.id), None
        )
        if existing_index is None:
            self.messages.append(message)
        elif append_text:
            existing = self.messages[existing_index]
            existing.content += text
            existing.status = response_status
            existing.error = error
            existing.error_code = response.error_code
            existing.error_params = dict(response.error_params)
            # Keep all provider/context metadata current as it arrives.
            for field_name in (
                "usage_available",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "context_usage_available",
                "input_context_tokens",
                "context_window_tokens",
                "context_tokens_exact",
                "omitted_round_numbers",
            ):
                setattr(existing, field_name, getattr(response, field_name))
            return existing
        else:
            self.messages[existing_index] = message
        return message

    def add_synthesis_response(self, response: SynthesisResponse) -> DiscussionMessage:
        return self.upsert_synthesis_response(response)

    def upsert_synthesis_response(
        self, response: SynthesisResponse, *, append_text: bool = False
    ) -> DiscussionMessage:
        """Append a synthesis that can never enter an agent prompt."""
        response_status = "completed" if response.is_complete else response.status
        message = DiscussionMessage(
            id=response.message_id,
            role="synthesis",
            content=response.text,
            round_number=response.round_number,
            status=response_status,
            error=truncate_error(response.error) if response.error else None,
            error_code=response.error_code,
            error_params=dict(response.error_params),
            include_in_agent_context=False,
            usage_available=response.usage_available,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            context_usage_available=response.context_usage_available,
            input_context_tokens=response.input_context_tokens,
            context_window_tokens=response.context_window_tokens,
            context_tokens_exact=response.context_tokens_exact,
        )
        existing_index = next(
            (index for index, item in enumerate(self.messages) if item.id == message.id), None
        )
        if existing_index is None:
            self.messages.append(message)
        elif append_text:
            existing = self.messages[existing_index]
            existing.content += response.text
            existing.status = response_status
            existing.error = message.error
            existing.error_code = message.error_code
            existing.error_params = dict(message.error_params)
            return existing
        else:
            self.messages[existing_index] = message
        return message

    def get_message(self, message_id: str) -> DiscussionMessage | None:
        return next(
            (message for message in self.messages if message.id == message_id),
            None,
        )

    def has_included_researcher_note_in_round(self, round_number: int) -> bool:
        """Whether a round will render at least one opted-in agent note."""

        return any(
            message.round_number == round_number
            and message.role == "agent"
            and message.include_in_agent_context
            and message.include_note_in_agent_context
            and bool(message.note.strip())
            for message in self.messages
        )

    def get_context_for_agents(self, *, omitted_round_numbers: set[int] | None = None) -> str:
        """Render the deterministic material/transcript request envelope.

        ``omitted_round_numbers`` is an ephemeral LLM-request selection, not
        a mutation.  The UI/export transcript and ``include_in_agent_context``
        flags remain intact so a later request with a larger window can bring
        the omitted rounds back.
        """
        parts: list[str] = []
        if self.material:
            parts.append(f"=== RESEARCH MATERIAL (AUTHORITATIVE SOURCE) ===\n{self.material}")
        discussion = self.get_discussion_for_agents(omitted_round_numbers=omitted_round_numbers)
        if discussion:
            parts.append(discussion)
        return "\n\n".join(parts)

    def get_discussion_for_agents(self, *, omitted_round_numbers: set[int] | None = None) -> str:
        """Render selected messages grouped by round in chronological order.

        Whole rounds are intentionally selected before rendering.  We never
        cut an individual contribution, which keeps the compacted context
        interpretable and avoids creating a synthetic partial transcript.
        """
        omitted = omitted_round_numbers or set()
        parts: list[str] = []
        if self.messages:
            current_round = self.round_number
            rendered_by_round: dict[int, list[str]] = {}
            for message in self.messages:
                if not message.include_in_agent_context:
                    continue
                if message.round_number in omitted:
                    continue
                if message.role == "user":
                    if message.round_number == current_round:
                        continue
                    rendered = f"[USER]: {message.content}"
                elif message.role == "agent":
                    perspective = (
                        f"Perspective {message.perspective_number}"
                        if message.perspective_number
                        else (message.agent_name or "Perspective")
                    )
                    rendered = f"[{perspective}]: {message.content}"
                    if message.note.strip() and message.include_note_in_agent_context:
                        rendered += (
                            "\n[HUMAN RESEARCHER NOTE ON THE ABOVE PERSPECTIVE RESPONSE]: "
                            f"{message.note.strip()}"
                        )
                else:
                    continue
                rendered_by_round.setdefault(message.round_number, []).append(rendered)

            if rendered_by_round:
                parts.append("=== DISCUSSION SO FAR ===")
                if omitted:
                    rendered_rounds = ", ".join(str(number) for number in sorted(omitted))
                    parts.append(f"[Rounds omitted from the LLM context: {rendered_rounds}]")
            for round_number in sorted(rendered_by_round):
                current = round_number == current_round
                title = (
                    f"=== ROUND {round_number} (CURRENT ROUND) ==="
                    if current
                    else f"=== ROUND {round_number} ==="
                )
                parts.append(title)
                parts.append("\n\n".join(rendered_by_round[round_number]))

            task = next(
                (
                    message.content
                    for message in self.messages
                    if message.role == "user"
                    and message.round_number == current_round
                    and message.include_in_agent_context
                ),
                "",
            )
            if task:
                parts.append(f"=== CURRENT ROUND USER INPUT (ROUND {current_round}) ===\n{task}")
        return "\n\n".join(parts)

    def compaction_candidate_round_numbers(self, *, before_round: int) -> list[int]:
        """Return removable previous rounds in deterministic oldest-first order.

        Round one and the two latest completed rounds are protected.  Only
        earlier *middle* rounds may be omitted.  Excluded messages do not
        change the round-level protection rule: a retained round can simply
        render no excluded contributions.
        """
        completed = sorted(
            {
                message.round_number
                for message in self.messages
                if 1 <= message.round_number < before_round
            }
        )
        if not completed:
            return []
        protected = {completed[0], *completed[-2:]}
        return [round_number for round_number in completed if round_number not in protected]

    def clear(self) -> None:
        self.material = ""
        self.initial_question = ""
        self.messages.clear()
        self.round_number = 0
        self.round_status = None


@dataclass(frozen=True)
class DiscussionGeneration:
    """Run-scoped cancellation handle for one worker invocation."""

    id: str
    cancelled: threading.Event

    def is_active(self) -> bool:
        return not self.cancelled.is_set()


__all__ = [
    "AgentConfig",
    "AgentResponse",
    "ContextUsage",
    "DEFAULT_AGENT_PROMPTS_BY_SESSION_TYPE",
    "DEFAULT_SESSION_TYPE",
    "DiscussionGeneration",
    "DiscussionMessage",
    "DiscussionState",
    "MaterialContext",
    "SESSION_TYPES",
    "SynthesisConfig",
    "SynthesisResponse",
]
