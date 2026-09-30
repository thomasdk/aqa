"""FastAPI transport layer for the shared application context.

Endpoints validate HTTP payloads and delegate application behavior to the
shared context. Business rules remain in the services that own them.
"""

from __future__ import annotations

import json
import queue
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from src.config.settings import (
    LOCAL_AI_HOST_KIND,
    LOCAL_AI_MODEL_ALIASES,
)
from src.config.user_data import mutable_data_lock
from src.local_ai.catalog import (
    MODELS,
)
from src.local_ai.manager import LocalAIStateError
from src.prompts.session_types import (
    SessionTypeRepository,
)
from src.service.api_errors import api_error as _api_error
from src.service.api_schemas import (
    AgentConfigModel,
    CancelDiscussionResponse,
    ContextEstimateRequest,
    ContextEstimateResponse,
    ContinueDiscussionRequest,
    DiscussionSessionTypeResponse,
    DiscussionStateResponse,
    DiscussionStreamEventResponse,
    MaterialContextModel,
    MessageContextInclusionRequest,
    MessageContextInclusionResponse,
    NextRoundAgentConfigModel,
    NextRoundSynthesisConfigModel,
    NoteRequest,
    PerspectiveResponse,
    RoundProviderProvenanceResponse,
    SessionSummaryModel,
    StartDiscussionRequest,
    SynthesisConfigModel,
    UpdateDiscussionAgentsRequest,
    UpdateDiscussionAgentsResponse,
    UpdateNextRoundConfigurationRequest,
    UpdateNextRoundConfigurationResponse,
    UpdateSynthesisRequest,
)
from src.service.discussion import (
    AgentConfig,
    AgentResponse,
    ContextUsage,
    MaterialContext,
    ProviderRebindRequiredError,
    ProviderRebindTargetChangedError,
    SynthesisConfig,
    SynthesisResponse,
)

from .dependencies import ContextDependency
from .local_ai import LocalAIManagerDependency
from .session_types import _session_type_payload_to_dict

router = APIRouter()


def _agent_config_from_model(m: AgentConfigModel) -> AgentConfig:
    return AgentConfig(
        name=m.name,
        client_id=m.client_id,
        prompt_id=m.prompt_id,
        color=m.color,
        temperature=m.temperature,
        llm_id=m.llm_id,
        api_host=m.api_host,
        host_configuration_id=m.host_configuration_id,
        host_label=m.host_label,
        api_key=m.api_key,
        max_tokens=m.max_tokens,
        enabled=m.enabled,
        perspective_number=m.perspective_number,
    )


def _synthesis_config_from_model(m: SynthesisConfigModel) -> SynthesisConfig:
    return SynthesisConfig(
        enabled=m.enabled,
        api_host=m.api_host,
        llm_id=m.llm_id,
        host_configuration_id=m.host_configuration_id,
        host_label=m.host_label,
        temperature=m.temperature,
    )


def _next_round_agent_config_from_model(m: NextRoundAgentConfigModel) -> AgentConfig:
    return AgentConfig(
        name=m.name,
        client_id=m.client_id,
        prompt_id=m.prompt_id,
        color=m.color,
        temperature=m.temperature,
        llm_id=m.llm_id,
        api_host=m.api_host,
        host_configuration_id=m.host_configuration_id,
        max_tokens=m.max_tokens,
        enabled=m.enabled,
        perspective_number=m.perspective_number,
    )


def _next_round_synthesis_config_from_model(
    m: NextRoundSynthesisConfigModel,
) -> SynthesisConfig:
    return SynthesisConfig(
        enabled=m.enabled,
        api_host=m.api_host,
        llm_id=m.llm_id,
        host_configuration_id=m.host_configuration_id,
        temperature=m.temperature,
    )


def _material_context_from_model(m: MaterialContextModel) -> MaterialContext:
    return MaterialContext(
        material_type=m.material_type,
        session_type=m.session_type,
        target_language=m.target_language,
        session_input_values=m.input_values.model_dump(),
    )


@router.get("/api/discussions/perspectives", response_model=list[PerspectiveResponse])
def list_discussion_perspectives(context: ContextDependency) -> list[dict]:
    items: list[dict] = []
    for perspective_id, label in context.discussion.get_available_perspectives():
        template = context.prompts.get_template(perspective_id)
        description = getattr(template, "description", None) if template is not None else None
        items.append(
            {
                "id": perspective_id,
                "label": label,
                "description": description if isinstance(description, str) else None,
            }
        )
    return items


@router.get("/api/discussions/session-types", response_model=list[DiscussionSessionTypeResponse])
def list_discussion_session_types(context: ContextDependency) -> list[dict]:
    items: list[dict] = []
    repo = getattr(context.discussion, "session_type_repo", None)
    for key, label in context.discussion.get_available_session_types():
        item = {"key": key, "label": label, "description": None, "inputs": []}
        if isinstance(repo, SessionTypeRepository):
            definition = repo.get(key)
            if definition is not None:
                editor_payload = _session_type_payload_to_dict(definition, context)
                item["description"] = definition.description
                item["inputs"] = editor_payload["inputs"]
        items.append(item)
    return items


@router.get("/api/discussions/defaults/agents")
def get_default_agents(context: ContextDependency, session_type: str = "") -> list[str]:
    return context.discussion.get_default_agent_prompt_ids(session_type)


@router.post(
    "/api/discussions/context-estimate",
    response_model=ContextEstimateResponse,
)
def estimate_discussion_context(
    payload: ContextEstimateRequest,
    context: ContextDependency,
) -> ContextEstimateResponse:
    """Estimate the current first-round request without generating text."""

    try:
        result = context.discussion.estimate_start_context_budget(
            material=payload.material,
            material_context=_material_context_from_model(payload.material_context),
            agents=[_agent_config_from_model(agent) for agent in payload.agents],
            synthesis=_synthesis_config_from_model(payload.synthesis),
            sequential_mode=payload.sequential_mode,
        )
    except ValueError as error:
        raise _api_error(422, "validation_failed", "Invalid discussion configuration") from error
    return ContextEstimateResponse(**result)


def _managed_local_ai_preflight(
    context: Any, configurations: list[Any], manager: Any
) -> str | None:
    """Return short German setup guidance before a managed-host discussion starts."""
    hosts = context.settings.known_llm_hosts
    inventory = {entry.get("model_id"): entry for entry in manager.inventory()}
    status = manager.status()
    managed_model_id: str | None = None
    for configuration in configurations:
        # Keep the preflight aligned with DiscussionService execution:
        # disabled agents and roster rows without an assigned role are
        # persisted, but they are not executed and therefore must not block
        # an otherwise valid Local-AI discussion with a stale model choice.
        is_active = (
            configuration.is_active
            if hasattr(configuration, "is_active")
            else bool(getattr(configuration, "enabled", False))
        )
        if not is_active:
            continue
        host = next(
            (
                entry
                for entry in hosts.values()
                if isinstance(entry, dict)
                and entry.get("kind") == LOCAL_AI_HOST_KIND
                and entry.get("url") == configuration.api_host
            ),
            None,
        )
        if host is None:
            continue
        requested_model = configuration.llm_id or host.get("model")
        alias_to_id = {
            alias: model_id
            for model_id, alias in zip(
                MODELS,
                LOCAL_AI_MODEL_ALIASES,
                strict=True,
            )
        }
        model_id = alias_to_id.get(requested_model)
        if model_id is None:
            raise _api_error(
                422,
                "validation_failed",
                "Das ausgewählte Modell ist für Integrierte KI nicht gültig.",
            )
        managed_model_id = model_id
        if not inventory.get(model_id, {}).get("installed"):
            raise _api_error(
                409,
                "local_ai_model_not_installed",
                "Öffne Integrierte KI und lade zuerst eine Gemma-Variante herunter.",
                params={"model_id": model_id},
            )
        if status.state not in {"running", "sleeping"}:
            raise _api_error(
                409,
                "local_ai_not_running",
                "Öffne Integrierte KI und starte zuerst das ausgewählte Modell.",
            )
        if status.model_id != model_id:
            raise _api_error(
                409,
                "local_ai_wrong_model_running",
                "Das ausgewählte Modell läuft nicht. Wähle es unter Integrierte KI aus und starte es.",
                params={"model_id": model_id},
            )
        if host.get("context_tokens") != status.context_tokens:
            raise _api_error(
                409,
                "local_ai_context_mismatch",
                "Der laufende KI-Dienst verwendet ein anderes Kontextfenster. Starte Integrierte KI erneut.",
            )
    return managed_model_id


def _managed_request_owner(manager: Any, expected_model_id: str | None) -> Callable[[], None]:
    """Hold one managed-runtime request lease for a complete discussion run."""
    released = False
    release_lock = threading.Lock()
    if expected_model_id is not None:
        try:
            manager.mark_request_active(expected_model_id)
        except LocalAIStateError as error:
            raise _api_error(
                409,
                error.code,
                "Integrierte KI wurde zwischenzeitlich geändert. Versuche es erneut.",
            ) from error

    def release() -> None:
        nonlocal released
        with release_lock:
            if released:
                return
            released = True
        if expected_model_id is not None:
            manager.mark_request_idle()

    return release


def _disconnect_generation(
    context: Any,
    generation_token: str | None,
    release_request: Callable[[], None],
) -> None:
    """Cancel the run and always release its managed-runtime ownership."""
    try:
        if generation_token is not None:
            context.discussion.cancel_generation(generation_token)
    finally:
        release_request()


def _stream_callbacks(
    event_queue: queue.Queue[dict[str, Any]],
    done_event: threading.Event,
    on_terminal: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Build the shared typed SSE callbacks for a discussion run."""

    def on_agent_start(response: AgentResponse) -> None:
        event_queue.put(
            {
                "type": "agent_start",
                "message_id": response.message_id,
                "agent_index": response.agent_index,
                "agent_name": response.agent_name,
                "client_id": response.client_id,
                "perspective_number": response.perspective_number,
                "theory_label": response.theory_label,
                "color": response.color,
            }
        )

    def on_context_usage(response: AgentResponse, usage: ContextUsage) -> None:
        event_queue.put(
            {
                "type": "context_usage",
                "message_id": response.message_id,
                "agent_index": response.agent_index,
                "perspective_number": response.perspective_number,
                "available": usage.available,
                "input_tokens": usage.input_tokens,
                "context_tokens": usage.context_tokens,
                "exact": usage.exact,
                "omitted_round_numbers": list(usage.omitted_round_numbers),
            }
        )

    def on_chunk(response: AgentResponse) -> None:
        event_queue.put(
            {
                "type": "chunk",
                "message_id": response.message_id,
                "agent_index": response.agent_index,
                "perspective_number": response.perspective_number,
                "agent_name": response.agent_name,
                "text": response.text,
            }
        )

    def on_agent_complete(response: AgentResponse) -> None:
        event_queue.put(
            {
                "type": "agent_complete",
                "message_id": response.message_id,
                "agent_index": response.agent_index,
                "perspective_number": response.perspective_number,
                "agent_name": response.agent_name,
                "client_id": response.client_id,
                "theory_label": response.theory_label,
                "color": response.color,
                "text": response.text,
                "is_complete": response.is_complete,
                "status": response.status,
                "error": response.error,
                "error_code": response.error_code,
                "error_params": response.error_params,
                "usage_available": response.usage_available,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "total_tokens": response.total_tokens,
                "context_usage_available": response.context_usage_available,
                "input_context_tokens": response.input_context_tokens,
                "context_window_tokens": response.context_window_tokens,
                "context_tokens_exact": response.context_tokens_exact,
                "omitted_round_numbers": list(response.omitted_round_numbers),
            }
        )

    def on_synthesis_start(response: SynthesisResponse) -> None:
        event_queue.put(
            {
                "type": "synthesis_start",
                "message_id": response.message_id,
                "round_number": response.round_number,
            }
        )

    def on_synthesis_chunk(response: SynthesisResponse) -> None:
        event_queue.put(
            {"type": "synthesis_chunk", "message_id": response.message_id, "text": response.text}
        )

    def on_synthesis_complete(response: SynthesisResponse) -> None:
        if response.status == "failed" or response.error:
            event_queue.put(
                {
                    "type": "synthesis_error",
                    "message_id": response.message_id,
                    "round_number": response.round_number,
                    "message": response.error or "",
                    "text": response.text,
                    "status": response.status,
                    "error_code": response.error_code,
                    "error_params": response.error_params,
                }
            )
            return
        event_queue.put(
            {
                "type": "synthesis_complete",
                "message_id": response.message_id,
                "round_number": response.round_number,
                "text": response.text,
                "status": response.status,
                "usage_available": response.usage_available,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "total_tokens": response.total_tokens,
                "error_code": response.error_code,
                "error_params": response.error_params,
            }
        )

    def on_all_complete() -> None:
        event_queue.put({"type": "all_complete"})
        done_event.set()
        if on_terminal is not None:
            on_terminal()

    def on_unexpected_error() -> None:
        event_queue.put(
            {
                "type": "error",
                "message": "Discussion generation was interrupted.",
                "error_code": "discussion_generation_interrupted",
                "error_params": {},
            }
        )
        done_event.set()
        if on_terminal is not None:
            on_terminal()

    return {
        "on_agent_start": on_agent_start,
        "on_context_usage": on_context_usage,
        "on_chunk": on_chunk,
        "on_agent_complete": on_agent_complete,
        "on_synthesis_start": on_synthesis_start,
        "on_synthesis_chunk": on_synthesis_chunk,
        "on_synthesis_complete": on_synthesis_complete,
        "on_all_complete": on_all_complete,
        "on_unexpected_error": on_unexpected_error,
    }


def _stream_response(
    event_queue: queue.Queue[dict[str, Any]],
    done_event: threading.Event,
    initial_events: list[dict[str, Any]],
    *,
    complete_after_initial_events: bool = False,
    on_disconnect: Callable[[], None] | None = None,
) -> StreamingResponse:
    """Serialize a queued discussion run while preserving initial event ordering."""

    def event_generator():
        terminal_event_seen = complete_after_initial_events
        try:
            yield from (f"data: {json.dumps(event)}\n\n" for event in initial_events)
            if complete_after_initial_events:
                return
            while True:
                try:
                    event = event_queue.get(timeout=0.5)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("type") in {"all_complete", "error"}:
                        terminal_event_seen = True
                        return
                except queue.Empty:
                    if done_event.is_set():
                        while not event_queue.empty():
                            try:
                                event = event_queue.get_nowait()
                                yield f"data: {json.dumps(event)}\n\n"
                                if event.get("type") in {"all_complete", "error"}:
                                    terminal_event_seen = True
                            except queue.Empty:
                                break
                        return
                    yield ": keepalive\n\n"
        finally:
            if not terminal_event_seen and on_disconnect is not None:
                on_disconnect()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post(
    "/api/discussions/start",
    responses={
        200: {
            "model": DiscussionStreamEventResponse,
            "description": "A sequence of JSON payloads encoded as text/event-stream.",
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/DiscussionStreamEventResponse"}
                }
            },
        }
    },
)
def start_discussion(
    payload: StartDiscussionRequest,
    context: ContextDependency,
    manager: LocalAIManagerDependency,
) -> StreamingResponse:
    event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
    done_event = threading.Event()
    if not payload.material.strip():
        raise _api_error(
            422,
            "material_required",
            "Das Diskussionsmaterial fehlt.",
        )
    agents = [_agent_config_from_model(agent) for agent in payload.agents]
    synthesis = _synthesis_config_from_model(payload.synthesis)
    managed_model_id = _managed_local_ai_preflight(context, [*agents, synthesis], manager)
    material_context = _material_context_from_model(payload.material_context)
    main_input = material_context.session_input_values["main_input"].strip()
    if not main_input:
        raise _api_error(
            422,
            "session_input_required",
            "Die zentrale Eingabe fehlt.",
            params={"session_type": material_context.session_type, "input_key": "main_input"},
        )

    budget = context.discussion.estimate_start_context_budget(
        material=payload.material,
        material_context=material_context,
        agents=agents,
        synthesis=synthesis,
        sequential_mode=payload.sequential_mode,
    )
    if managed_model_id is not None and not budget["known"]:
        raise _api_error(
            503,
            "input_estimate_unavailable",
            "Die Eingabegröße konnte nicht geschätzt werden. Prüfe die AQA-Installation.",
        )
    if budget.get("known") is True and budget.get("overflow") is True:
        raise _api_error(
            422,
            "context_limit_exceeded",
            "Die Eingabe ist zu lang. Kürze das Material oder den Auftrag.",
            params={
                "input_tokens": budget["estimated_input_tokens"],
                "context_tokens": budget["context_window_tokens"],
                "available_input_tokens": budget["available_input_tokens"],
                "reserved_output_tokens": budget["reserved_output_tokens"],
            },
        )

    release_request = _managed_request_owner(manager, managed_model_id)
    callbacks = _stream_callbacks(event_queue, done_event, release_request)
    try:
        with mutable_data_lock:
            user_message = context.discussion.start_new_discussion(
                material=payload.material,
                question=main_input,
                agents=agents,
                title=payload.title,
                material_context=material_context,
                synthesis_config=synthesis,
                sequential_mode=payload.sequential_mode,
                **callbacks,
            )
            generation_token = context.discussion.active_generation_token()
    except Exception:
        release_request()
        raise
    active_file_id = context.discussion.current_session_file_id()
    if active_file_id:
        context.settings.last_active_discussion_id = active_file_id
        try:
            context.settings.save_user_settings()
        except OSError:
            # Resume persistence is advisory; the discussion itself is already valid.
            pass
    initial_events = [
        {
            "type": "discussion_started",
            "file_id": active_file_id or "",
            "title": context.discussion.current_session_title() or "",
        }
    ]
    if user_message is not None:
        initial_events.append(
            {
                "type": "user_message",
                "message_id": user_message.id,
                "content": user_message.content,
                "round_number": user_message.round_number,
            }
        )
    return _stream_response(
        event_queue,
        done_event,
        initial_events,
        on_disconnect=lambda: _disconnect_generation(context, generation_token, release_request),
    )


@router.post(
    "/api/discussions/continue",
    responses={
        200: {
            "model": DiscussionStreamEventResponse,
            "description": "A sequence of JSON payloads encoded as text/event-stream.",
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/DiscussionStreamEventResponse"}
                }
            },
        }
    },
)
def continue_discussion(
    payload: ContinueDiscussionRequest,
    context: ContextDependency,
    manager: LocalAIManagerDependency,
) -> StreamingResponse:
    event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
    done_event = threading.Event()
    agents = [_agent_config_from_model(agent) for agent in payload.agents]
    release_request: Callable[[], None] | None = None
    try:
        with mutable_data_lock:
            resolved_agents, resolved_synthesis = (
                context.discussion.resolve_continuation_configuration(
                    agents,
                    rebind_configuration_id=(
                        payload.provider_rebind.configuration_id
                        if payload.provider_rebind
                        else None
                    ),
                    rebind_model_id=(
                        payload.provider_rebind.model_id if payload.provider_rebind else None
                    ),
                )
            )
            configurations = [
                *resolved_agents,
                *([resolved_synthesis] if resolved_synthesis is not None else []),
            ]
            managed_model_id = _managed_local_ai_preflight(context, configurations, manager)
            release_request = _managed_request_owner(manager, managed_model_id)
            callbacks = _stream_callbacks(event_queue, done_event, release_request)
            user_message = context.discussion.continue_discussion(
                user_input=payload.user_input,
                agents=agents,
                focus_segment=payload.focus_segment,
                sequential_mode=payload.sequential_mode,
                rebind_configuration_id=(
                    payload.provider_rebind.configuration_id if payload.provider_rebind else None
                ),
                rebind_model_id=(
                    payload.provider_rebind.model_id if payload.provider_rebind else None
                ),
                **callbacks,
            )
            generation_token = context.discussion.active_generation_token()
    except (ProviderRebindRequiredError, ProviderRebindTargetChangedError) as error:
        if release_request is not None:
            release_request()
        message = (
            "The replacement host or model changed. Review the current catalogue and try again."
            if isinstance(error, ProviderRebindTargetChangedError)
            else "Select a currently configured replacement host and model before continuing."
        )
        raise _api_error(
            409,
            error.code,
            message,
            params=error.params,
        ) from error
    except Exception:
        if release_request is not None:
            release_request()
        raise
    assert release_request is not None
    if user_message is None:
        release_request()
        return _stream_response(
            event_queue,
            done_event,
            [
                {
                    "type": "error",
                    "message": "No active discussion",
                    "error_code": "no_active_discussion",
                    "error_params": {},
                }
            ],
            complete_after_initial_events=True,
        )
    return _stream_response(
        event_queue,
        done_event,
        [
            {
                "type": "user_message",
                "message_id": user_message.id,
                "content": user_message.content,
                "round_number": user_message.round_number,
            }
        ],
        on_disconnect=lambda: _disconnect_generation(context, generation_token, release_request),
    )


@router.get(
    "/api/discussions/provider-provenance",
    response_model=list[RoundProviderProvenanceResponse],
)
def get_provider_provenance(context: ContextDependency) -> list[dict[str, Any]]:
    return context.discussion.round_provider_provenance_snapshot()


@router.get("/api/discussions/state", response_model=DiscussionStateResponse)
def get_discussion_state(context: ContextDependency) -> dict:
    state = context.discussion.state
    return {
        "material": state.material,
        "initial_question": state.initial_question,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "round_number": m.round_number,
                "status": m.status,
                "agent_name": m.agent_name,
                "theory_label": m.theory_label,
                "color": m.color,
                "agent_index": m.agent_index,
                "perspective_number": m.perspective_number,
                "note": m.note,
                "include_note_in_agent_context": bool(m.include_note_in_agent_context),
                "error": m.error,
                "error_code": m.error_code,
                "error_params": m.error_params,
                "include_in_agent_context": bool(m.include_in_agent_context),
                "client_id": m.client_id,
                "usage_available": m.usage_available,
                "prompt_tokens": m.prompt_tokens,
                "completion_tokens": m.completion_tokens,
                "total_tokens": m.total_tokens,
                "context_usage_available": m.context_usage_available,
                "input_context_tokens": m.input_context_tokens,
                "context_window_tokens": m.context_window_tokens,
                "context_tokens_exact": m.context_tokens_exact,
                "omitted_round_numbers": list(m.omitted_round_numbers),
            }
            for m in state.messages
        ],
        "has_errors": any(m.status == "failed" or m.error for m in state.messages),
        "round_number": state.round_number,
        "round_status": state.round_status,
        "has_active_discussion": context.discussion.has_active_discussion,
    }


# Session endpoints project storage data through explicit Pydantic DTOs so a
# response-model mismatch cannot expose API keys, paths, or internal IDs.


def _reveal_path(path: Path) -> None:
    """Reveal one validated path without exposing command or path details.

    Callers must validate grammar, existence, and containment before calling
    this helper. Launch failures are reported as a generic HTTP 502 response.
    """

    system = sys.platform
    if system == "darwin":
        argv: list[str] = ["open", "-R", str(path)]
    elif system == "win32":
        # ``explorer /select,<path>`` highlights the file.
        argv = ["explorer", f"/select,{path}"]
    else:
        # Linux file managers reliably open the containing directory.
        argv = ["xdg-open", str(path.parent)]

    try:
        subprocess.run(
            argv,
            shell=False,
            check=False,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError):
        raise HTTPException(
            status_code=502, detail="Reveal command could not be launched"
        ) from None


def _open_directory(path: Path) -> None:
    """Open an already validated directory in the platform file manager.

    Unlike :func:`_reveal_path`, this does not select an individual file.  The
    caller must validate existence and containment before invoking it.  All
    launch details remain internal so no filesystem paths or command details
    can leak through the API response.
    """

    if sys.platform == "darwin":
        argv: list[str] = ["open", str(path)]
    elif sys.platform == "win32":
        argv = ["explorer", str(path)]
    else:
        argv = ["xdg-open", str(path)]

    try:
        result = subprocess.run(
            argv,
            shell=False,
            check=False,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if isinstance(result.returncode, int) and result.returncode != 0:
            raise HTTPException(status_code=502, detail="Directory is unavailable")
    except HTTPException:
        raise
    except (subprocess.TimeoutExpired, OSError):
        raise HTTPException(status_code=502, detail="Directory is unavailable") from None


def _current_open_file_id(context: Any) -> str | None:
    """Return the canonical ID of the open session."""
    return context.discussion.current_session_file_id()


def _summarize_session(item: dict, *, is_open: bool) -> SessionSummaryModel:
    """Map validated storage metadata to the public response model."""
    return SessionSummaryModel(
        file_id=str(item["file_id"]),
        title=str(item.get("title", "")),
        created=str(item.get("created", "")),
        updated=str(item.get("updated", "")),
        session_type=str(item["session_type"]),
        round_count=int(item.get("round_count", 0)),
        is_open=bool(is_open),
        is_favorite=bool(item.get("is_favorite", False)),
    )


@router.post("/api/discussions/reset")
def reset_discussion(context: ContextDependency) -> dict:
    context.discussion.cancel_active_generation()
    context.discussion.reset_discussion()
    return {"status": "ok"}


@router.post("/api/discussions/cancel", response_model=CancelDiscussionResponse)
def cancel_discussion_generation(context: ContextDependency) -> CancelDiscussionResponse:
    cancelled = context.discussion.cancel_active_generation()
    return CancelDiscussionResponse(status="cancelling" if cancelled else "idle")


@router.get("/api/discussions/export")
def export_discussion(
    context: ContextDependency,
    locale: Literal["de", "en"] = "de",
    download_filename: str | None = None,
) -> Response:
    """Export the current discussion as Markdown."""
    markdown = context.discussion.get_markdown(locale=locale)
    if markdown is None:
        raise HTTPException(status_code=400, detail="No active discussion")
    title = context.discussion.current_session_title() or "diskussion"
    safe_title = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß\s-]", "", title).strip().replace(" ", "-")
    filename = f"{safe_title or 'diskussion'}.md"
    if download_filename and re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}\.md", download_filename
    ):
        filename = download_filename
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/discussions/messages/{message_id}/note")
def set_message_note(message_id: str, payload: NoteRequest, context: ContextDependency) -> dict:
    success = context.discussion.set_message_note(
        message_id, payload.note, payload.include_note_in_agent_context
    )
    if not success:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"status": "ok"}


@router.delete("/api/discussions/messages/{message_id}/note")
def delete_message_note(message_id: str, context: ContextDependency) -> dict:
    success = context.discussion.clear_message_note(message_id)
    if not success:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"status": "ok"}


@router.put(
    "/api/discussions/agents",
    response_model=UpdateDiscussionAgentsResponse,
)
def update_discussion_agents(
    payload: UpdateDiscussionAgentsRequest,
    context: ContextDependency,
) -> UpdateDiscussionAgentsResponse:
    """Replace the complete editable agent roster for the open discussion."""
    new_agents = [_agent_config_from_model(a) for a in payload.agents]
    updated = context.discussion.update_current_agents(new_agents)
    if not updated:
        raise HTTPException(status_code=404, detail="No active discussion")
    return UpdateDiscussionAgentsResponse(agent_count=len(new_agents))


@router.put("/api/discussions/synthesis")
def update_discussion_synthesis(
    payload: UpdateSynthesisRequest, context: ContextDependency
) -> dict:
    """Replace the persisted synthesis configuration between rounds."""
    synthesis = _synthesis_config_from_model(payload.synthesis)
    result = context.discussion.update_synthesis_config_for_session(payload.file_id, synthesis)
    if result == "generation_active":
        raise HTTPException(status_code=409, detail="A discussion generation is active")
    if result == "session_mismatch":
        raise HTTPException(status_code=409, detail="The active session changed")
    if result == "no_active_session":
        raise HTTPException(status_code=404, detail="No active discussion")
    return {"ok": True}


@router.put(
    "/api/discussions/next-round-configuration",
    response_model=UpdateNextRoundConfigurationResponse,
)
def update_next_round_configuration(
    payload: UpdateNextRoundConfigurationRequest,
    context: ContextDependency,
) -> UpdateNextRoundConfigurationResponse:
    """Atomically replace all editable settings for the next round."""
    agents = [_next_round_agent_config_from_model(agent) for agent in payload.agents]
    synthesis = _next_round_synthesis_config_from_model(payload.synthesis)
    result = context.discussion.update_next_round_configuration(payload.file_id, agents, synthesis)
    if result == "generation_active":
        raise HTTPException(status_code=409, detail="A discussion generation is active")
    if result == "session_mismatch":
        raise HTTPException(status_code=409, detail="The active session changed")
    if result == "roster_changed":
        raise HTTPException(status_code=409, detail="The session participant roster changed")
    if result == "provider_changed":
        raise HTTPException(status_code=409, detail="The host or model catalogue changed")
    if result == "role_changed":
        raise HTTPException(status_code=409, detail="The selected role is no longer available")
    if result == "no_active_session":
        raise HTTPException(status_code=404, detail="No active discussion")
    return UpdateNextRoundConfigurationResponse(agent_count=len(agents))


@router.put(
    "/api/discussions/messages/{message_id}/context-inclusion",
    response_model=MessageContextInclusionResponse,
)
def update_message_context_inclusion(
    message_id: str,
    payload: MessageContextInclusionRequest,
    context: ContextDependency,
) -> MessageContextInclusionResponse:
    """Update one current-round message's next-round context inclusion flag."""
    result = context.discussion.set_message_context_inclusion(
        message_id, payload.include_in_agent_context
    )
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Message not found")
    if result == "locked":
        raise HTTPException(
            status_code=409,
            detail=(
                "Diese Nachricht liegt in einer abgeschlossenen "
                "Runde und kann nicht mehr geändert werden."
            ),
        )
    return MessageContextInclusionResponse(ok=True)


LocalAIModelId = Literal["gemma-4-e2b", "gemma-4-e4b", "gemma-4-12b"]
LocalAIMtpDraftTokens = Literal[1, 2, 3, 4, 5, 6]
