"""Discussion orchestration, streaming, and snapshot persistence."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from loguru import logger

from src.config.settings import LOCAL_AI_HOST_KIND, Settings
from src.llm.errors import (
    LLMGenerationLengthLimitError,
    LLMRequestError,
    LLMTokenCountUnsupportedError,
)
from src.llm.llm_manager import LLMManager
from src.prompts import (
    PromptRecord,
    PromptRepository,
    SessionInputDefinition,
    SessionTypeRepository,
)
from src.prompts.session_types import effective_session_input_value
from src.service.discussion_domain import (
    DEFAULT_AGENT_PROMPTS_BY_SESSION_TYPE,
    DEFAULT_SESSION_TYPE,
    SESSION_TYPES,
    AgentConfig,
    AgentResponse,
    ContextUsage,
    DiscussionMessage,
    DiscussionState,
    MaterialContext,
    SynthesisConfig,
    SynthesisResponse,
)
from src.service.discussion_domain import (
    DiscussionGeneration as _DiscussionGeneration,
)
from src.service.discussion_export import export_markdown
from src.service.discussion_prompts import (
    append_perspective_user_reminders,
    append_response_language_reminder,
    build_synthesis_user_prompt,
    perspective_prompt_layout,
)
from src.service.discussion_prompts import (
    build_system_prompt as assemble_system_prompt,
)
from src.service.discussion_prompts import (
    build_user_prompt as assemble_user_prompt,
)
from src.service.discussion_storage import (
    DiscussionStorage,
    SessionDeletionRollbackError,
    StoredAgent,
    StoredDiscussion,
    StoredMessage,
    StoredPromptSnapshot,
    StoredProviderProvenance,
    StoredRound,
    StoredSynthesisConfig,
)
from src.service.discussion_text import (
    DEFAULT_TITLE_EXCERPT_MAX_CHARS,
    DEFAULT_TITLE_FALLBACK,
    LINE_NUMBERED_MATERIAL_TYPES,
    MATERIAL_TYPES,
    add_line_numbers_to_material,
    generate_default_discussion_title,
    is_line_numbered_material,
    material_type_uses_line_numbers,
)
from src.service.host_catalog import serialize_host_entry
from src.service.token_estimator import TokenEstimatorUnavailable, estimate_tokens

CONTEXT_OUTPUT_RESERVE_TOKENS = 4_096
# The bundled BPE estimates rendered chat text, not the model's chat template.
# Reuse the established 25% + 256-token conservative allowance for offline
# checks; generation still checks each final assembled request and its history.
MANAGED_CONTEXT_ESTIMATE_MULTIPLIER = 5
MANAGED_CONTEXT_ESTIMATE_DIVISOR = 4
MANAGED_CONTEXT_ESTIMATE_OVERHEAD = 256


class _ContextPreflightFailure(RuntimeError):
    """Structured agent failure raised before a generation starts."""

    def __init__(
        self,
        code: str,
        params: dict[str, Any],
        usage: ContextUsage | None = None,
    ):
        self.code = code
        self.params = params
        self.usage = usage
        super().__init__(code)


class TargetLanguageRequiredError(ValueError):
    """Raised when a discussion would generate without an output language."""

    code = "target_language_required"


class MaterialRequiredError(ValueError):
    """Raised before a discussion could start without source material."""

    code = "material_required"


class ProviderRebindRequiredError(ValueError):
    """Raised before a continued session could contact a removed host."""

    code = "provider_rebind_required"

    def __init__(self, missing_count: int):
        self.params = {"count": missing_count}
        super().__init__(self.code)


class ProviderRebindTargetChangedError(ValueError):
    code = "provider_rebind_target_changed"

    def __init__(self):
        self.params: dict[str, Any] = {}
        super().__init__(self.code)


__all__ = [
    "AgentConfig",
    "AgentResponse",
    "ContextUsage",
    "DEFAULT_AGENT_PROMPTS_BY_SESSION_TYPE",
    "DEFAULT_SESSION_TYPE",
    "DEFAULT_TITLE_EXCERPT_MAX_CHARS",
    "DEFAULT_TITLE_FALLBACK",
    "DiscussionMessage",
    "DiscussionService",
    "DiscussionState",
    "LINE_NUMBERED_MATERIAL_TYPES",
    "MATERIAL_TYPES",
    "MaterialContext",
    "MaterialRequiredError",
    "ProviderRebindRequiredError",
    "ProviderRebindTargetChangedError",
    "SESSION_TYPES",
    "TargetLanguageRequiredError",
    "add_line_numbers_to_material",
    "generate_default_discussion_title",
    "is_line_numbered_material",
    "material_type_uses_line_numbers",
]


class DiscussionService:
    """Coordinate prompt assembly, model execution, and session persistence."""

    def __init__(
        self,
        settings: Settings,
        llm_manager: LLMManager,
        prompt_repo: PromptRepository,
        storage_dir: Path | str | None = None,
        session_context_dir: Path | str | None = None,
    ):
        self.settings = settings
        self.llm_manager = llm_manager
        self.prompt_repo = prompt_repo
        if session_context_dir is not None:
            session_base = Path(session_context_dir)
        else:
            session_base = Path(settings.prompt_library_path) / "session_contexts"
        self.session_type_repo = SessionTypeRepository(base_path=session_base)

        if storage_dir is None:
            storage_dir = Path("conversations")
        self.storage = DiscussionStorage(storage_dir)

        self._prompts: dict[str, PromptRecord] = {}
        self._load_prompts()

        self.state = DiscussionState()

        # Generation identity prevents deferred workers from mutating a newer run.
        self._run_lock = threading.RLock()
        self._active_generation: _DiscussionGeneration | None = None
        self._generation_running = False
        self._generation_streams: dict[str, dict[int, Any]] = {}

        self._current_stored: StoredDiscussion | None = None
        self._current_agents: list[AgentConfig] = []
        self._material_context: MaterialContext | None = None
        # Sequential mode must survive autosave and session reopening.
        self._sequential_mode: bool = False
        self._synthesis_config: SynthesisConfig | None = None
        self._round_provider_provenance: dict[int, list[StoredProviderProvenance]] = {}
        # ``False`` is a stable capability result (the optional endpoint was
        # missing). Successful providers are still counted per final request.
        self._token_count_capabilities: dict[tuple[str, str], bool] = {}

    def _load_prompts(self) -> None:
        """Refresh the in-memory prompt catalogue from the repository."""
        self._prompts.clear()
        for template in self.prompt_repo.list_templates():
            self._prompts[template.id] = template
            logger.debug(f"Prompt geladen: {template.label} (ID: {template.id})")
        logger.info(f"{len(self._prompts)} Theorie-Perspektiven geladen")

    def _host_configs_for_agent(self, agent: AgentConfig) -> list[Mapping[str, Any]]:
        """Return every configured host entry that owns ``agent.api_host``.

        Host URLs are editable and need not be unique. Context planning must
        therefore take the most restrictive matching configuration, rather
        than silently inheriting whichever duplicate happens to be first.
        """
        resolved_host = (agent.api_host or "").rstrip("/")
        known_hosts = getattr(self.settings, "known_llm_hosts", {})
        if not isinstance(known_hosts, Mapping):
            return []
        matches: list[Mapping[str, Any]] = []
        for config in known_hosts.values():
            if not isinstance(config, Mapping):
                continue
            if str(config.get("url", "")).rstrip("/") == resolved_host:
                matches.append(config)
        return matches

    def _configured_provider(
        self,
        host_configuration_id: str | None,
        api_host: str | None,
        model_id: str | None,
    ) -> tuple[str, str, str, str] | None:
        """Resolve one stable configuration ID, URL, and model."""
        normalized_id = (host_configuration_id or "").strip()
        normalized_host = (api_host or "").rstrip("/")
        normalized_model = (model_id or "").strip()
        if not normalized_id or not normalized_host or not normalized_model:
            return None
        known_hosts = getattr(self.settings, "known_llm_hosts", {})
        if not isinstance(known_hosts, Mapping):
            return None
        config = known_hosts.get(normalized_id)
        if not isinstance(config, Mapping):
            return None
        if str(config.get("url", "")).rstrip("/") != normalized_host:
            return None
        models = config.get("models")
        selectable = {
            str(item).strip()
            for item in (models if isinstance(models, (list, tuple)) else [])
            if str(item).strip()
        }
        preferred = str(config.get("model", "")).strip()
        if preferred:
            selectable.add(preferred)
        if normalized_model in selectable:
            display_label = str(serialize_host_entry(normalized_id, config)["label"])
            return normalized_id, display_label, normalized_host, normalized_model
        return None

    def _capture_provider_provenance(
        self,
        agents: list[AgentConfig],
        synthesis: SynthesisConfig | None,
        prompt_snapshot: StoredPromptSnapshot | None = None,
    ) -> list[StoredProviderProvenance]:
        """Freeze role and provider selections for one round without credentials."""
        snapshot = prompt_snapshot or self._prompt_snapshot()
        result: list[StoredProviderProvenance] = []
        for agent in agents:
            if not agent.is_active or not agent.api_host or not agent.llm_id:
                continue
            resolved = self._configured_provider(
                agent.host_configuration_id, agent.api_host, agent.llm_id
            )
            configuration_id, label, api_host, model_id = resolved or (
                agent.host_configuration_id,
                agent.host_label,
                agent.api_host.rstrip("/"),
                agent.llm_id.strip(),
            )
            role = self._snapshot_role(snapshot, agent.prompt_id or "") if snapshot else None
            prompt = self._prompts.get(agent.prompt_id)
            prompt_id = str((role or {}).get("id") or getattr(prompt, "id", agent.prompt_id or ""))
            prompt_label = str((role or {}).get("label") or getattr(prompt, "label", agent.name))
            result.append(
                StoredProviderProvenance(
                    kind="perspective",
                    client_id=agent.client_id,
                    prompt_id=prompt_id,
                    prompt_label=prompt_label,
                    perspective_number=agent.perspective_number,
                    temperature=agent.temperature,
                    host_configuration_id=configuration_id,
                    host_label=label,
                    api_host=api_host,
                    model_id=model_id,
                )
            )
        if synthesis and synthesis.enabled and synthesis.api_host and synthesis.llm_id:
            resolved = self._configured_provider(
                synthesis.host_configuration_id, synthesis.api_host, synthesis.llm_id
            )
            configuration_id, label, api_host, model_id = resolved or (
                synthesis.host_configuration_id,
                synthesis.host_label,
                synthesis.api_host.rstrip("/"),
                synthesis.llm_id.strip(),
            )
            result.append(
                StoredProviderProvenance(
                    kind="synthesis",
                    client_id=None,
                    prompt_id="round_synthesis",
                    prompt_label=str(
                        (snapshot.synthesis or {}).get("label", "Round synthesis")
                        if snapshot
                        else "Round synthesis"
                    ),
                    perspective_number=None,
                    temperature=synthesis.temperature,
                    host_configuration_id=configuration_id,
                    host_label=label,
                    api_host=api_host,
                    model_id=model_id,
                )
            )
        return result

    def _require_current_continuation_providers(self, agents: list[AgentConfig]) -> None:
        """Block a resumed round until every removed provider is explicitly replaced."""
        if self._current_stored is None:
            return
        missing = sum(
            1
            for agent in agents
            if agent.is_active
            and (agent.api_host or agent.llm_id)
            and self._configured_provider(agent.host_configuration_id, agent.api_host, agent.llm_id)
            is None
        )
        synthesis = self._synthesis_config
        if (
            synthesis
            and synthesis.enabled
            and (synthesis.api_host or synthesis.llm_id)
            and self._configured_provider(
                synthesis.host_configuration_id, synthesis.api_host, synthesis.llm_id
            )
            is None
        ):
            missing += 1
        if missing:
            raise ProviderRebindRequiredError(missing)

    def sessions_referencing_host(
        self, host_configuration_id: str, api_host: str
    ) -> list[dict[str, str]]:
        """Return path-free saved-session identities retaining a host reference."""
        return self.storage.sessions_referencing_host(host_configuration_id, api_host)

    def round_provider_provenance_snapshot(self) -> list[dict[str, Any]]:
        """Return the current session's safe, immutable per-round provider record."""
        with self._run_lock:
            return [
                {
                    "round_number": round_number,
                    "providers": [
                        {
                            "kind": provider.kind,
                            "client_id": provider.client_id,
                            "prompt_id": provider.prompt_id,
                            "prompt_label": provider.prompt_label,
                            "perspective_number": provider.perspective_number,
                            "temperature": provider.temperature,
                            "host_configuration_id": provider.host_configuration_id,
                            "host_label": provider.host_label,
                            "api_host": provider.api_host,
                            "model_id": provider.model_id,
                        }
                        for provider in providers
                    ],
                }
                for round_number, providers in sorted(self._round_provider_provenance.items())
            ]

    def _prospective_provider_rebind(
        self,
        agents: list[AgentConfig],
        host_configuration_id: str,
        model_id: str,
    ) -> tuple[list[AgentConfig], SynthesisConfig | None]:
        known_hosts = getattr(self.settings, "known_llm_hosts", {})
        config = (
            known_hosts.get(host_configuration_id) if isinstance(known_hosts, Mapping) else None
        )
        if not isinstance(config, Mapping):
            raise ProviderRebindTargetChangedError()
        api_host = str(config.get("url", "")).rstrip("/")
        models = {str(value).strip() for value in config.get("models", []) if str(value).strip()}
        preferred = str(config.get("model", "")).strip()
        if preferred:
            models.add(preferred)
        if not api_host or model_id not in models:
            raise ProviderRebindTargetChangedError()

        affected_client_ids = {
            agent.client_id
            for agent in self._current_agents
            if agent.is_active
            and self._configured_provider(agent.host_configuration_id, agent.api_host, agent.llm_id)
            is None
        }
        incoming_client_ids = {agent.client_id for agent in agents}
        if None in affected_client_ids or not affected_client_ids.issubset(incoming_client_ids):
            raise ProviderRebindTargetChangedError()
        rebound_agents = deepcopy(agents)
        for agent in rebound_agents:
            if agent.client_id in affected_client_ids:
                agent.host_configuration_id = host_configuration_id
                agent.host_label = str(serialize_host_entry(host_configuration_id, config)["label"])
                agent.api_host = api_host
                agent.llm_id = model_id
                agent.api_key = None
        rebound_synthesis = deepcopy(self._synthesis_config)
        if (
            rebound_synthesis
            and rebound_synthesis.enabled
            and self._configured_provider(
                rebound_synthesis.host_configuration_id,
                rebound_synthesis.api_host,
                rebound_synthesis.llm_id,
            )
            is None
        ):
            rebound_synthesis.host_configuration_id = host_configuration_id
            rebound_synthesis.host_label = str(
                serialize_host_entry(host_configuration_id, config)["label"]
            )
            rebound_synthesis.api_host = api_host
            rebound_synthesis.llm_id = model_id
        return rebound_agents, rebound_synthesis

    def resolve_continuation_configuration(
        self,
        agents: list[AgentConfig],
        *,
        rebind_configuration_id: str | None = None,
        rebind_model_id: str | None = None,
    ) -> tuple[list[AgentConfig], SynthesisConfig | None]:
        """Resolve the exact next-round providers without mutating session state."""
        with self._run_lock:
            resolved_agents = deepcopy(list(agents))
            self._validate_agent_configurations(resolved_agents)
            resolved_synthesis = deepcopy(self._synthesis_config)
            if rebind_configuration_id is None and rebind_model_id is None:
                return resolved_agents, resolved_synthesis
            if not rebind_configuration_id or not rebind_model_id:
                raise ProviderRebindTargetChangedError()
            return self._prospective_provider_rebind(
                resolved_agents,
                rebind_configuration_id,
                rebind_model_id,
            )

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        return None

    def _context_tokens_for_agent(self, agent: AgentConfig) -> int | None:
        """Resolve a configured model window for managed and external hosts."""
        limits: list[int] = []
        for config in self._host_configs_for_agent(agent):
            if config.get("kind") == LOCAL_AI_HOST_KIND:
                limit = self._positive_int(config.get("context_tokens"))
            else:
                model_limits = config.get("model_context_tokens")
                model = (agent.llm_id or config.get("model") or "").strip()
                limit = (
                    self._positive_int(model_limits.get(model))
                    if isinstance(model_limits, Mapping) and model
                    else None
                )
            if limit is not None:
                limits.append(limit)
        return min(limits) if limits else None

    def _effective_context_tokens(self, agents: list[AgentConfig]) -> int | None:
        """Return the tightest configured window among active perspectives."""
        limits = [
            limit
            for agent in agents
            if agent.is_active
            if (limit := self._context_tokens_for_agent(agent)) is not None
        ]
        return min(limits) if limits else None

    def _context_for_agent(
        self,
        agent: AgentConfig,
        *,
        omitted_round_numbers: set[int] | None = None,
    ) -> str:
        """Build the selected transcript context for one imminent request."""
        return self.state.get_context_for_agents(omitted_round_numbers=omitted_round_numbers)

    @staticmethod
    def _chat_estimate(messages: list[dict[str, str]]) -> int:
        """Estimate final chat input without pretending to know its template."""
        rendered = "\n".join(f"{message['role']}: {message['content']}" for message in messages)
        return estimate_tokens(rendered) + (4 * len(messages))

    def _offline_chat_estimate(self, messages: list[dict[str, str]]) -> int:
        """Reserve room for provider-specific tokenization and chat templates."""
        count = self._chat_estimate(messages)
        return (
            count * MANAGED_CONTEXT_ESTIMATE_MULTIPLIER + MANAGED_CONTEXT_ESTIMATE_DIVISOR - 1
        ) // MANAGED_CONTEXT_ESTIMATE_DIVISOR + MANAGED_CONTEXT_ESTIMATE_OVERHEAD

    def _count_context_usage(
        self,
        *,
        llm: Any,
        agent: AgentConfig,
        system_prompt: str | None,
        user_prompt: str,
        context_tokens: int | None,
        omitted_round_numbers: tuple[int, ...],
    ) -> ContextUsage:
        """Estimate managed requests offline; use exact counts for capable external hosts."""
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        host = str(getattr(llm, "host", None) or agent.api_host or "").rstrip("/")
        model = str(getattr(llm, "model_name", None) or agent.llm_id or "")
        key = (host, model)
        managed = any(
            config.get("kind") == LOCAL_AI_HOST_KIND
            for config in self._host_configs_for_agent(agent)
        )
        count_chat = getattr(llm, "count_chat_input_tokens", None)
        if (
            not managed
            and self._token_count_capabilities.get(key) is not False
            and callable(count_chat)
        ):
            try:
                input_tokens = count_chat(messages)
            except LLMTokenCountUnsupportedError:
                self._token_count_capabilities[key] = False
            except Exception as exc:
                # Do not mistake a transient failure for unsupported capability.
                logger.debug("Token preflight failed for %s/%s: %s", host, model, exc)
            else:
                if (
                    isinstance(input_tokens, int)
                    and not isinstance(input_tokens, bool)
                    and input_tokens >= 0
                ):
                    self._token_count_capabilities[key] = True
                    try:
                        material_tokens = estimate_tokens(self.state.material)
                        discussion_tokens = estimate_tokens(
                            self.state.get_discussion_for_agents(
                                omitted_round_numbers=set(omitted_round_numbers)
                            )
                        )
                    except TokenEstimatorUnavailable:
                        material_tokens = discussion_tokens = None
                    return ContextUsage(
                        available=True,
                        exact=True,
                        material_tokens=material_tokens,
                        discussion_tokens=discussion_tokens,
                        other_tokens=(
                            max(0, input_tokens - material_tokens - discussion_tokens)
                            if material_tokens is not None and discussion_tokens is not None
                            else None
                        ),
                        input_tokens=input_tokens,
                        context_tokens=context_tokens,
                        omitted_round_numbers=omitted_round_numbers,
                    )
                logger.debug("Token preflight returned an invalid count for %s/%s", host, model)

        try:
            input_tokens = self._offline_chat_estimate(messages)
            material_tokens = estimate_tokens(self.state.material)
            discussion_tokens = estimate_tokens(
                self.state.get_discussion_for_agents(
                    omitted_round_numbers=set(omitted_round_numbers)
                )
            )
        except TokenEstimatorUnavailable:
            return ContextUsage(
                available=False,
                exact=False,
                context_tokens=context_tokens,
                omitted_round_numbers=omitted_round_numbers,
            )
        return ContextUsage(
            available=True,
            exact=False,
            material_tokens=material_tokens,
            discussion_tokens=discussion_tokens,
            other_tokens=max(0, input_tokens - material_tokens - discussion_tokens),
            input_tokens=input_tokens,
            context_tokens=context_tokens,
            omitted_round_numbers=omitted_round_numbers,
        )

    def _preflight_context_usage(
        self,
        *,
        llm: Any,
        agent: AgentConfig,
        system_prompt: str | None,
        user_prompt: str,
        context_tokens: int | None = None,
        omitted_round_numbers: tuple[int, ...] = (),
        enforce_context_limit: bool = True,
    ) -> ContextUsage:
        """Measure one final request and enforce its configured input budget."""
        resolved_context_tokens = (
            context_tokens if context_tokens is not None else self._context_tokens_for_agent(agent)
        )
        usage = self._count_context_usage(
            llm=llm,
            agent=agent,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            context_tokens=resolved_context_tokens,
            omitted_round_numbers=omitted_round_numbers,
        )
        if (
            enforce_context_limit
            and any(
                config.get("kind") == LOCAL_AI_HOST_KIND
                for config in self._host_configs_for_agent(agent)
            )
            and not usage.available
        ):
            raise _ContextPreflightFailure("input_estimate_unavailable", {}, usage)
        if (
            enforce_context_limit
            and resolved_context_tokens is not None
            and usage.input_tokens is not None
            and usage.input_tokens > max(0, resolved_context_tokens - CONTEXT_OUTPUT_RESERVE_TOKENS)
        ):
            raise _ContextPreflightFailure(
                "context_limit_exceeded",
                {
                    "input_tokens": usage.input_tokens,
                    "context_tokens": resolved_context_tokens,
                    "available_input_tokens": max(
                        0, resolved_context_tokens - CONTEXT_OUTPUT_RESERVE_TOKENS
                    ),
                    "reserved_output_tokens": CONTEXT_OUTPUT_RESERVE_TOKENS,
                },
                usage,
            )
        return usage

    def _prepare_context_limited_prompt(
        self,
        *,
        llm: Any,
        agent: AgentConfig,
        system_prompt: str | None,
        effective_context_tokens: int | None,
        before_round: int,
        build_user_prompt: Callable[[str], str],
        context_state: DiscussionState | None = None,
    ) -> tuple[str, ContextUsage]:
        """Build and compact one request without mutating discussion state.

        The renderer receives the selected material/history context.  It lets
        the initial and continuation orchestration share one threshold and
        audit policy while preserving every stored message verbatim.
        """
        omitted: set[int] = set()
        selected_state = context_state or self.state
        candidates = selected_state.compaction_candidate_round_numbers(before_round=before_round)
        while True:
            context = selected_state.get_context_for_agents(omitted_round_numbers=omitted)
            user_prompt = build_user_prompt(context)
            usage = self._preflight_context_usage(
                llm=llm,
                agent=agent,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context_tokens=effective_context_tokens,
                omitted_round_numbers=tuple(sorted(omitted)),
                enforce_context_limit=False,
            )
            fits = (
                effective_context_tokens is None
                or usage.input_tokens is None
                or usage.input_tokens
                <= max(0, effective_context_tokens - CONTEXT_OUTPUT_RESERVE_TOKENS)
            )
            if fits:
                return user_prompt, usage
            if not candidates:
                raise _ContextPreflightFailure(
                    "context_limit_exceeded",
                    {
                        "input_tokens": usage.input_tokens or 0,
                        "context_tokens": effective_context_tokens,
                        "available_input_tokens": max(
                            0, effective_context_tokens - CONTEXT_OUTPUT_RESERVE_TOKENS
                        ),
                        "reserved_output_tokens": CONTEXT_OUTPUT_RESERVE_TOKENS,
                    },
                    usage,
                )
            omitted.add(candidates.pop(0))

    def _continuation_prompt(
        self,
        context: str,
        user_input: str,
        focus_segment: str | None,
    ) -> str:
        """Build the user prompt for one agent in a follow-up round."""
        if focus_segment:
            return f"""{context}

=== NEW MODERATOR NOTE/QUESTION (ROUND {self.state.round_number}) ===
FOCUS ON TEXT PASSAGE:
"{focus_segment}"

QUESTION:
{user_input}

Please answer this note/question. Refer specifically to the marked passage in the context of the discussion so far."""
        return f"""{context}

=== NEW MODERATOR NOTE/QUESTION (ROUND {self.state.round_number}) ===
{user_input}

Please answer this note. Refer to the material and the discussion so far."""

    @staticmethod
    def _moderator_message_content(user_input: str, focus_segment: str | None) -> str:
        """Persist the complete follow-up task once for both audit and context."""
        if focus_segment:
            return f"""FOCUS ON TEXT PASSAGE:
\"{focus_segment}\"

QUESTION:
{user_input}"""
        return user_input

    def reload_prompts(self) -> None:
        """Reload prompt assets and the service cache after a role mutation."""
        self.prompt_repo.reload()
        self._load_prompts()

    def reload_session_configuration(self) -> None:
        """Reload every prompt-backed catalogue used by previews and discussions."""
        self.prompt_repo.reload()
        self.session_type_repo.reload()
        self._load_prompts()

    def get_available_perspectives(self) -> list[tuple[str, str]]:
        """Return every available perspective as an id and label pair."""
        return [(p.id, p.label) for p in self._prompts.values()]

    def get_prompt_by_id(self, prompt_id: str) -> PromptRecord | None:
        """Return one prompt record by id."""
        return self._prompts.get(prompt_id)

    def get_default_agent_prompt_ids(self, session_type: str | None) -> list[str]:
        """Return default role ids that exist in the current prompt catalogue."""
        key = self._normalize_session_type(session_type)
        definition = self.session_type_repo.get(key)
        if definition is None:
            return []
        return [
            prompt_id
            for prompt_id in definition.default_agent_prompt_ids
            if prompt_id in self._prompts
        ]

    def _normalize_session_type(self, session_type: str | None) -> str:
        """Require a session type that exists in the active repository."""
        key = (session_type or "").strip()
        if self.session_type_repo.get(key) is None:
            raise ValueError(f"unknown session type: {key!r}")
        return key

    @staticmethod
    def _validate_agent_configurations(agents: list[AgentConfig]) -> None:
        """Validate the stable identity contract before mutating a session."""
        client_ids: set[str] = set()
        for agent in agents:
            client_id = (agent.client_id or "").strip()
            if not client_id:
                raise ValueError("agent client_id must be non-empty")
            if client_id in client_ids:
                raise ValueError("agent client_id values must be unique")
            if agent.perspective_number <= 0:
                raise ValueError("agent perspective_number must be positive")
            client_ids.add(client_id)

    def get_available_session_types(self) -> list[tuple[str, str]]:
        """Return all available session types as ``(key, label)`` pairs.

        Values come from the live ``SessionTypeRepository`` and follow its
        deterministic key ordering.
        """
        return [(definition.key, definition.label) for definition in self.session_type_repo.list()]

    def get_default_session_type(self) -> str:
        """Return the configured default session-type ID.

        Prefer ``DEFAULT_SESSION_TYPE`` when it exists in the live repository;
        otherwise use the repository's deterministic default.
        """
        if self.session_type_repo.get(DEFAULT_SESSION_TYPE) is not None:
            return DEFAULT_SESSION_TYPE
        return self.session_type_repo.default()

    def get_session_type_description(self, session_type: str | None) -> str:
        key = self._normalize_session_type(session_type)
        definition = self.session_type_repo.get(key)
        if definition is None:
            return ""
        return definition.description

    @property
    def material_context(self) -> MaterialContext | None:
        return self._material_context

    @property
    def sequential_mode(self) -> bool:
        """Whether the currently open session runs in sequential mode.

        Mirrored on the in-memory :class:`DiscussionService` and the
        persisted :class:`StoredDiscussion` so a saved session reopens
        with the same execution style the user chose.
        """
        return self._sequential_mode

    @property
    def synthesis_config(self) -> SynthesisConfig | None:
        """Return a defensive copy of the active synthesis settings."""
        with self._run_lock:
            return deepcopy(self._synthesis_config)

    @property
    def is_generation_running(self) -> bool:
        with self._run_lock:
            return self._generation_running

    def update_synthesis_config(self, config: SynthesisConfig) -> bool:
        """Persist synthesis settings between completed rounds only."""
        with self._run_lock:
            if self._generation_running:
                return False
            if self._current_stored is None:
                return False
            self._synthesis_config = deepcopy(config)
            self._save_current_state_locked()
            return True

    def update_synthesis_config_for_session(
        self,
        file_id: str,
        config: SynthesisConfig,
    ) -> str:
        """Atomically replace synthesis settings for one known open session.

        The discussion service is process-global, so validating a session ID
        in the route and saving it later would permit a session switch between
        those operations.  Keep identity, idle-state, and persistence checks
        under the same lock instead.
        """
        with self._run_lock:
            if self._generation_running:
                return "generation_active"
            if self._current_stored is None:
                return "no_active_session"
            if self.storage.file_id_for(self._current_stored) != file_id:
                return "session_mismatch"
            self._synthesis_config = deepcopy(config)
            self._save_current_state_locked()
            return "updated"

    def build_system_prompt(
        self,
        prompt_id: str,
        agent_config: AgentConfig | None = None,
        agent_index: int = 0,
        total_agents: int = 1,
        other_agents: list[tuple[str, str]] | None = None,
        material_context: MaterialContext | None = None,
        use_prompt_snapshot: bool = True,
        mark_prompt_usage: bool = True,
    ) -> str | None:
        """Resolve repository records and delegate pure prompt assembly.

        ``use_prompt_snapshot`` remains enabled for live discussion requests.
        Preview callers disable it so an explicit draft ``material_context``
        cannot be shadowed by an unrelated open history snapshot.
        """

        snapshot = self._prompt_snapshot() if use_prompt_snapshot else None
        template = (
            self._snapshot_role(snapshot, prompt_id) if snapshot else self._prompts.get(prompt_id)
        )
        if template is None:
            return None
        session_requirement = ""
        session_label = None
        if snapshot is not None:
            session_requirement = snapshot.session.get("behavioral_guidance", "")
            session_label = snapshot.session.get("label") or None
            if mark_prompt_usage:
                self._mark_prompt_usage(snapshot, role_id=prompt_id, multi_agent=total_agents > 1)
        elif material_context is not None:
            session_key = self._normalize_session_type(material_context.session_type)
            definition = self.session_type_repo.get(session_key)
            if definition is not None:
                session_requirement = definition.body
                session_label = definition.label
        perspective_number = (
            agent_config.perspective_number
            if agent_config is not None and agent_config.perspective_number > 0
            else agent_index + 1
        )
        return assemble_system_prompt(
            template=template,
            common_instructions=(
                self._snapshot_common_instructions(snapshot, total_agents > 1)
                if snapshot
                else self._load_common_instructions(multi_agent=total_agents > 1)
            ),
            session_requirement=session_requirement,
            agent_index=agent_index,
            perspective_number=perspective_number,
            total_agents=total_agents,
            other_agents=other_agents,
            material_context=material_context,
            session_label=session_label,
        )

    def _prompt_snapshot(self) -> StoredPromptSnapshot | None:
        snapshot = getattr(self._current_stored, "prompt_snapshot", None)
        return (
            snapshot
            if isinstance(snapshot, StoredPromptSnapshot) and not snapshot.is_empty
            else None
        )

    @staticmethod
    def _snapshot_role(snapshot: StoredPromptSnapshot, prompt_id: str) -> dict[str, Any] | None:
        return next((role for role in snapshot.roles if role.get("id") == prompt_id), None)

    @staticmethod
    def _snapshot_common_instructions(snapshot: StoredPromptSnapshot, multi_agent: bool) -> str:
        return "\n\n".join(
            f"=== {str(block.get('label') or block.get('id')).upper()} ===\n{block['content']}"
            for block in snapshot.globals
            if block.get("scope") != "synthesis"
            and (block.get("scope") != "multi_agent" or multi_agent)
            and isinstance(block.get("content"), str)
            and block["content"]
        )

    @staticmethod
    def _mark_prompt_usage(
        snapshot: StoredPromptSnapshot,
        *,
        role_id: str | None = None,
        multi_agent: bool = False,
        synthesis: bool = False,
    ) -> None:
        for block in snapshot.globals:
            if block.get("scope") != "synthesis" and (
                block.get("scope") != "multi_agent" or multi_agent
            ):
                block_id = block.get("id")
                if isinstance(block_id, str) and block_id not in snapshot.used_global_ids:
                    snapshot.used_global_ids.append(block_id)
        if role_id and role_id not in snapshot.used_role_ids:
            snapshot.used_role_ids.append(role_id)
        if synthesis:
            snapshot.synthesis_used = True

    def _create_prompt_snapshot(
        self, material_context: MaterialContext, definition: Any | None
    ) -> StoredPromptSnapshot:
        self._load_prompts()
        roles = [
            {
                "id": str(item.id),
                "label": str(item.label),
                "role": str(item.role or ""),
                "task": str(item.task or ""),
                "output_format": str(item.output_format or ""),
            }
            for item in self._prompts.values()
        ]
        globals_ = [
            {
                "id": str(item.id),
                "label": str(item.label),
                "scope": str(item.scope or ""),
                "content": str(item.content),
            }
            for item in self.prompt_repo.list_globals()
        ]
        synthesis = next((item for item in globals_ if item["id"] == "round_synthesis"), None)
        return StoredPromptSnapshot(
            layout=perspective_prompt_layout(),
            session={
                "label": str(getattr(definition, "label", material_context.session_label)),
                "description": str(getattr(definition, "description", "")),
                "behavioral_guidance": str(getattr(definition, "body", "")),
            },
            globals=globals_,
            roles=roles,
            synthesis=(
                {"label": synthesis["label"], "content": synthesis["content"]}
                if synthesis
                else None
            ),
            target_language=material_context.target_language,
            context_policy={
                "include_unchanged_research_material_context_in_prompt": bool(
                    material_context.include_unchanged_research_material_context_in_prompt
                )
            },
        )

    def _load_common_instructions(self, multi_agent: bool = False) -> str:
        """Load global prompt blocks, optionally including multi-agent guidance."""
        return self.prompt_repo.get_common_instructions(multi_agent=multi_agent)

    def _store_round_memory(self, user_input: str, responses: list[AgentResponse]) -> None:
        """Keep the call site stable; round-memory persistence is not used."""
        return

    def build_user_prompt(
        self,
        material: str,
        question: str,
        material_context: MaterialContext | None = None,
    ) -> str:
        """Delegate pure user-message assembly."""

        return assemble_user_prompt(material, question, material_context)

    def estimate_start_context_budget(
        self,
        *,
        material: str,
        material_context: MaterialContext,
        agents: list[AgentConfig],
        synthesis: SynthesisConfig,
        sequential_mode: bool = False,
    ) -> dict[str, Any]:
        """Estimate complete first-round perspective requests without generation.

        This deliberately assembles the same system and user prompt sections
        used by a live start, but never changes service state or generates text.
        Future sequential or synthesis requests may remain unknown, but they
        must not hide an overflow already proven for an initial perspective.
        """

        self._validate_agent_configurations(agents)
        context = deepcopy(material_context)
        context.session_type = self._normalize_session_type(context.session_type)
        definition = self.session_type_repo.get(context.session_type)
        if definition is not None:
            context.set_session_inputs(list(definition.session_inputs))
            context.include_unchanged_research_material_context_in_prompt = (
                definition.include_unchanged_research_material_context_in_prompt
            )
        if not context.target_language:
            raise ValueError("target language must be non-empty")

        active_agents = [agent for agent in agents if agent.is_active]
        # Generation uses the tightest configured perspective window for every
        # request in a round. Setup must apply that same shared boundary.
        effective_window = self._effective_context_tokens(active_agents)
        context_windows = [self._context_tokens_for_agent(agent) for agent in active_agents]
        has_managed_agent = any(
            config.get("kind") == LOCAL_AI_HOST_KIND
            for agent in active_agents
            for config in self._host_configs_for_agent(agent)
        )
        future_request_unknown = (sequential_mode and len(active_agents) > 1) or synthesis.enabled
        if not active_agents:
            return {
                "known": False,
                "estimated_input_tokens": None,
                "available_input_tokens": None,
                "context_window_tokens": None,
                "reserved_output_tokens": CONTEXT_OUTPUT_RESERVE_TOKENS,
                "overflow": False,
            }

        normalized_material = material
        if material and material_type_uses_line_numbers(context.material_type):
            normalized_material = add_line_numbers_to_material(material)
        question = context.session_input_values.get("main_input", "")
        user_prompt = self.build_user_prompt(normalized_material, question, context)
        estimates: list[int] = []
        for position, agent in enumerate(active_agents):
            others = [
                (
                    f"Perspective {other.perspective_number}",
                    self._prompts.get(other.prompt_id).label
                    if self._prompts.get(other.prompt_id) is not None
                    else other.name,
                )
                for other in active_agents
                if other is not agent
            ]
            system_prompt = self.build_system_prompt(
                prompt_id=agent.prompt_id or "",
                agent_config=agent,
                agent_index=position,
                total_agents=len(active_agents),
                other_agents=others,
                material_context=context,
                use_prompt_snapshot=False,
            )
            if system_prompt is None:
                raise ValueError("unknown perspective")
            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
                count = self._offline_chat_estimate(messages)
                estimates.append(count)
            except TokenEstimatorUnavailable:
                return {
                    "known": False,
                    "estimated_input_tokens": None,
                    "available_input_tokens": None,
                    "context_window_tokens": None,
                    "reserved_output_tokens": CONTEXT_OUTPUT_RESERVE_TOKENS,
                    "overflow": False,
                }

        measured_requests = [
            (estimated, effective_window, max(0, effective_window - CONTEXT_OUTPUT_RESERVE_TOKENS))
            for estimated in estimates
            if effective_window is not None
        ]
        if not measured_requests:
            return {
                "known": False,
                "estimated_input_tokens": None,
                "available_input_tokens": None,
                "context_window_tokens": None,
                "reserved_output_tokens": CONTEXT_OUTPUT_RESERVE_TOKENS,
                "overflow": False,
            }

        limiting_request = min(measured_requests, key=lambda item: item[2] - item[0])
        estimated, context_window, available = limiting_request
        overflow = estimated > available
        if not overflow and (
            any(window is None for window in context_windows)
            or (future_request_unknown and not has_managed_agent)
        ):
            return {
                "known": False,
                "estimated_input_tokens": None,
                "available_input_tokens": None,
                "context_window_tokens": None,
                "reserved_output_tokens": CONTEXT_OUTPUT_RESERVE_TOKENS,
                "overflow": False,
            }
        return {
            "known": True,
            "estimated_input_tokens": estimated,
            "available_input_tokens": available,
            "context_window_tokens": context_window,
            "reserved_output_tokens": CONTEXT_OUTPUT_RESERVE_TOKENS,
            "overflow": overflow,
        }

    def build_synthesis_system_prompt(self, *, mark_prompt_usage: bool = True) -> str:
        """Return the dedicated synthesis instructions with final language precedence."""
        snapshot = self._prompt_snapshot()
        if snapshot is not None:
            if snapshot.synthesis is None:
                raise RuntimeError("round_synthesis_prompt_unavailable")
            if mark_prompt_usage:
                self._mark_prompt_usage(snapshot, synthesis=True)
            target_language = snapshot.target_language
            content = snapshot.synthesis["content"].strip()
        else:
            content = ""
            target_language = ""
        if snapshot is None:
            block = self.prompt_repo.get_global("round_synthesis")
            if block is None or block.scope != "synthesis" or not block.content.strip():
                raise RuntimeError("round_synthesis_prompt_unavailable")
            target_language = (
                self._material_context.target_language if self._material_context else ""
            ).strip()
            content = block.content.strip()
        if not target_language:
            raise TargetLanguageRequiredError()
        language_rule = (
            f"Write all synthesis prose and every category lead-in in {target_language}. "
            "Use only the four category types defined in the category schema, translate their "
            "visible labels into the required language, and do not output their internal IDs."
        )
        return content + "\n\n=== FINAL RESPONSE LANGUAGE REQUIREMENT ===\n" + language_rule

    def build_synthesis_user_prompt(
        self,
        *,
        question: str,
        active_agents: list[tuple[int, AgentConfig]],
        responses: list[AgentResponse],
    ) -> str:
        """Build a current-round-only synthesis prompt without source material."""
        material_context = self._material_context or MaterialContext()
        definition = self.session_type_repo.get(
            self._normalize_session_type(material_context.session_type)
        )
        session_label = (
            definition.label if definition is not None else material_context.session_label
        )
        session_description = definition.description if definition is not None else ""
        session_inputs = [
            (
                item.prompt_heading,
                effective_session_input_value(
                    item.key,
                    material_context.session_input_values.get(item.key, ""),
                    item.default_text,
                    material_context.include_unchanged_research_material_context_in_prompt,
                ),
            )
            for item in material_context.session_inputs
        ]
        participants = [
            (
                f"Perspective {agent.perspective_number}",
                self._prompts.get(agent.prompt_id).label
                if self._prompts.get(agent.prompt_id) is not None
                else agent.name,
            )
            for _, agent in active_agents
        ]
        contributions = [
            (
                f"Perspective {response.perspective_number or response.agent_index + 1}",
                response.theory_label,
                response.text,
                response.error,
            )
            for response in responses
        ]
        return build_synthesis_user_prompt(
            session_label=session_label,
            session_description=session_description,
            material_type_label=material_context.type_label,
            target_language=material_context.target_language,
            session_inputs=session_inputs,
            participants=participants,
            question=question,
            contributions=contributions,
        )

    def _run_round_synthesis(
        self,
        *,
        generation: _DiscussionGeneration,
        question: str,
        active_agents: list[tuple[int, AgentConfig]],
        responses: list[AgentResponse],
        on_start: Callable[[SynthesisResponse], None] | None,
        on_chunk: Callable[[SynthesisResponse], None] | None,
        on_complete: Callable[[SynthesisResponse], None] | None,
    ) -> SynthesisResponse | None:
        """Generate one non-participant synthesis after a completed round."""
        config = self.synthesis_config
        if config is None or not config.enabled or not self._is_current_generation(generation):
            return None

        # Perspective responses are durable before a separate provider call
        # begins.  A synthesis failure must never take their completed round
        # down with it.
        self._save_state_if_current(generation, self._save_current_state)

        message_id = str(uuid4())
        round_number = max(1, self.state.round_number)
        usable = [
            response
            for response in responses
            if response.status == "completed" and not response.error and response.text.strip()
        ]
        if not usable:
            response = SynthesisResponse(
                message_id=message_id,
                text="",
                round_number=round_number,
                is_complete=False,
                status="failed",
                error_code="synthesis_no_usable_contributions",
            )
            if on_start:
                on_start(response)
            if on_complete:
                on_complete(response)
            return response

        start_response = SynthesisResponse(
            message_id=message_id,
            text="",
            round_number=round_number,
        )
        full_text = ""
        error: str | None = None
        error_code: str | None = None
        error_params: dict[str, Any] = {}
        provider_usage: dict[str, int] | None = None
        started = False
        synthesis_agent = AgentConfig(
            name="Round synthesis",
            api_host=config.api_host,
            llm_id=config.llm_id,
            host_configuration_id=config.host_configuration_id,
            host_label=config.host_label,
            temperature=config.temperature,
        )
        try:
            system_prompt = self.build_synthesis_system_prompt()
            user_prompt = self.build_synthesis_user_prompt(
                question=question,
                active_agents=active_agents,
                responses=usable,
            )
            llm = self.llm_manager.get_llm(
                host=config.api_host,
                api_key=None,
                model_name=config.llm_id,
                **(
                    {"host_configuration_id": config.host_configuration_id}
                    if config.host_configuration_id
                    else {}
                ),
            )
            usage = self._preflight_context_usage(
                llm=llm,
                agent=synthesis_agent,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context_tokens=self._context_tokens_for_agent(synthesis_agent),
            )
            start_response.context_usage_available = usage.available
            start_response.input_context_tokens = usage.input_tokens
            start_response.context_window_tokens = usage.context_tokens
            start_response.context_tokens_exact = usage.exact
            if on_start:
                on_start(start_response)
            started = True

            def on_usage(value: dict[str, int]) -> None:
                nonlocal provider_usage
                provider_usage = value

            start_response.usage_available = False
            stream = llm.generate_stream(
                prompt=user_prompt,
                temperature=config.temperature,
                max_tokens=None,
                system_prompt=system_prompt,
                on_usage=on_usage,
                cancel_event=generation.cancelled,
            )
            streamed_text, stream_error = self._consume_synthesis_stream(
                generation,
                stream,
                message_id,
                round_number,
                on_chunk,
            )
            if streamed_text is None:
                return None
            full_text = streamed_text
            if stream_error is not None:
                raise stream_error
        except (_ContextPreflightFailure, LLMRequestError) as exc:
            error, error_code, error_params = self._synthesis_request_failure(exc, synthesis_agent)
        except Exception as exc:
            logger.warning("Round synthesis failed: %s", exc)
            error = str(exc)
            error_code = "synthesis_generation_failed"

        if not self._is_current_generation(generation):
            return None
        error, error_code, error_params = self._ensure_nonempty_provider_result(
            text=full_text,
            error=error,
            error_code=error_code,
            error_params=error_params,
            agent=synthesis_agent,
        )
        if not started and on_start:
            on_start(start_response)
        response = SynthesisResponse(
            message_id=message_id,
            text=full_text,
            round_number=round_number,
            is_complete=error is None,
            status="failed" if error else "completed",
            error=error,
            error_code=error_code,
            error_params=error_params,
            usage_available=True if provider_usage is not None else start_response.usage_available,
            prompt_tokens=(provider_usage or {}).get("prompt_tokens"),
            completion_tokens=(provider_usage or {}).get("completion_tokens"),
            total_tokens=(provider_usage or {}).get("total_tokens"),
            context_usage_available=start_response.context_usage_available,
            input_context_tokens=start_response.input_context_tokens,
            context_window_tokens=start_response.context_window_tokens,
            context_tokens_exact=start_response.context_tokens_exact,
        )
        if on_complete:
            on_complete(response)
        return response

    def _consume_synthesis_stream(
        self,
        generation: _DiscussionGeneration,
        stream: Any,
        message_id: str,
        round_number: int,
        on_chunk: Callable[[SynthesisResponse], None] | None,
    ) -> tuple[str | None, Exception | None]:
        """Consume one synthesis iterator while it belongs to the current run."""
        if not self._register_generation_stream(generation, stream):
            return None, None
        chunks: list[str] = []
        try:
            for chunk in stream:
                if not self._is_current_generation(generation):
                    return None, None
                chunks.append(chunk)
                if on_chunk:
                    on_chunk(
                        SynthesisResponse(
                            message_id=message_id,
                            text=chunk,
                            round_number=round_number,
                            status="in_progress",
                        )
                    )
            return "".join(chunks), None
        except Exception as error:
            return "".join(chunks), error
        finally:
            self._unregister_generation_stream(generation, stream)
            self._close_provider_stream(stream)

    def _begin_generation(self) -> _DiscussionGeneration:
        """Atomically cancel any previous generation and register a new one.

        Returns the new run-scoped handle. Callers must pass it through
        ``run_discussion`` and check ``generation.is_active()`` before any
        stateful side effect.
        """
        with self._run_lock:
            return self._begin_generation_locked()

    def _begin_generation_locked(self) -> _DiscussionGeneration:
        """Register a new generation. Caller must hold ``_run_lock``."""
        if self._active_generation is not None:
            previous = self._active_generation
            previous.cancelled.set()
            self._close_streams_async(self._take_generation_streams_locked(previous))
        new_generation = _DiscussionGeneration(
            id=str(uuid4()),
            cancelled=threading.Event(),
        )
        self._active_generation = new_generation
        return new_generation

    @staticmethod
    def _close_provider_stream(stream: Any) -> None:
        close_stream = getattr(stream, "close", None)
        if callable(close_stream):
            try:
                close_stream()
            except Exception:
                logger.debug("Provider stream close failed during cancellation.")

    def _close_streams_async(self, streams: list[Any]) -> None:
        """Abort superseded streams without blocking a caller that holds the run lock."""
        for stream in streams:
            threading.Thread(
                target=self._close_provider_stream,
                args=(stream,),
                daemon=True,
                name="discussion-stream-close",
            ).start()

    def _take_generation_streams_locked(self, generation: _DiscussionGeneration) -> list[Any]:
        return list(self._generation_streams.pop(generation.id, {}).values())

    def _register_generation_stream(self, generation: _DiscussionGeneration, stream: Any) -> bool:
        """Register a provider iterator only while its exact generation is current."""
        with self._run_lock:
            if not self._is_current_generation_locked(generation):
                registered = False
            else:
                self._generation_streams.setdefault(generation.id, {})[id(stream)] = stream
                registered = True
        if not registered:
            self._close_provider_stream(stream)
        return registered

    def _unregister_generation_stream(self, generation: _DiscussionGeneration, stream: Any) -> None:
        with self._run_lock:
            streams = self._generation_streams.get(generation.id)
            if streams is None:
                return
            streams.pop(id(stream), None)
            if not streams:
                self._generation_streams.pop(generation.id, None)

    def _is_current_generation_locked(self, generation: _DiscussionGeneration) -> bool:
        """Return True if ``generation`` is still the active, uncancelled run.

        Caller must hold ``_run_lock``. This helper keeps the check and the
        subsequent state mutation inside a single lock acquisition.
        """
        return self._active_generation is generation and not generation.cancelled.is_set()

    def _is_current_generation(self, generation: _DiscussionGeneration) -> bool:
        """Check whether a worker still owns the active generation."""
        with self._run_lock:
            return self._is_current_generation_locked(generation)

    def _mark_generation_finished(self, generation: _DiscussionGeneration) -> None:
        """Clear the UI-facing running flag for this generation, even if cancelled."""
        with self._run_lock:
            if self._active_generation is generation:
                self._generation_running = False

    def _finish_generation_with_status(self, generation: _DiscussionGeneration) -> bool:
        """Persist one idempotent terminal outcome for the active round."""
        with self._run_lock:
            if self._active_generation is not generation or generation.cancelled.is_set():
                return False
            current_round = max(1, self.state.round_number)
            has_error = any(
                message.round_number == current_round
                and (message.status == "failed" or bool(message.error))
                for message in self.state.messages
            )
            self.state.round_status = "failed" if has_error else "completed"
            self._generation_running = False
            self._save_current_state()
            return True

    def _mark_current_round_messages(self, status: str) -> None:
        """Mark unfinished cards with the same durable outcome as their round."""
        current_round = max(1, self.state.round_number)
        for message in self.state.messages:
            if message.round_number == current_round and message.status == "in_progress":
                message.status = status

    def _fail_generation(self, generation: _DiscussionGeneration) -> None:
        """Record an unexpected worker failure without rewriting another run."""
        with self._run_lock:
            if self._active_generation is not generation or generation.cancelled.is_set():
                return
            self._mark_current_round_messages("failed")
            self.state.round_status = "failed"
            self._generation_running = False
            self._save_current_state()

    def active_generation_token(self) -> str | None:
        """Return the opaque identity of the generation currently owning state."""
        with self._run_lock:
            return self._active_generation.id if self._active_generation is not None else None

    def _cancel_generation_locked(self, generation: _DiscussionGeneration) -> bool:
        if (
            self._active_generation is not generation
            or generation.cancelled.is_set()
            or self.state.round_status != "in_progress"
        ):
            return False
        generation.cancelled.set()
        streams = self._take_generation_streams_locked(generation)
        try:
            # Cancellation is a persisted round outcome. The worker may be
            # blocked in provider code and cannot be trusted to run another state
            # callback before the app is reloaded or quit.
            self.state.round_status = "interrupted"
            self._mark_current_round_messages("interrupted")
            self._generation_running = False
            self._save_current_state_locked()
        finally:
            self._close_streams_async(streams)
        return True

    def cancel_generation(self, generation_token: str) -> bool:
        """Cancel only the active generation matching an originating stream token."""
        with self._run_lock:
            active = self._active_generation
            if active is None or active.id != generation_token:
                return False
            return self._cancel_generation_locked(active)

    def cancel_active_generation(self) -> bool:
        """Request cancellation of the currently active generation.

        Idempotent: returns ``True`` the first time a currently running
        generation is cancelled; ``False`` if no uncancelled generation is
        active. The originating worker still invokes ``on_all_complete`` so
        that the SSE channel can terminate, but all state mutations are
        skipped after cancellation.
        """
        with self._run_lock:
            active = self._active_generation
            if active is None:
                return False
            return self._cancel_generation_locked(active)

    def _other_agents(
        self, active_agents: list[tuple[int, AgentConfig]], current_index: int
    ) -> list[tuple[str, str]]:
        """Return the configured peers visible to one perspective prompt."""

        return [
            (
                f"Perspective {agent.perspective_number}",
                self._prompts.get(agent.prompt_id).label
                if self._prompts.get(agent.prompt_id)
                else agent.name,
            )
            for index, agent in active_agents
            if index != current_index
        ]

    @staticmethod
    def _new_agent_start_response(
        agent_index: int, agent: AgentConfig, theory_label: str
    ) -> AgentResponse:
        return AgentResponse(
            message_id=str(uuid4()),
            agent_index=agent_index,
            agent_name=agent.name,
            client_id=agent.client_id,
            perspective_number=agent.perspective_number,
            theory_label=theory_label,
            color=agent.color,
            text="",
            is_complete=False,
        )

    @staticmethod
    def _apply_context_usage(response: AgentResponse, usage: ContextUsage) -> None:
        response.context_usage_available = usage.available
        response.input_context_tokens = usage.input_tokens
        response.context_window_tokens = usage.context_tokens
        response.context_tokens_exact = usage.exact
        response.omitted_round_numbers = usage.omitted_round_numbers

    def _emit_context_usage(
        self,
        response: AgentResponse,
        usage: ContextUsage,
        callback: Callable[[AgentResponse, ContextUsage], None] | None,
    ) -> None:
        self._apply_context_usage(response, usage)
        if callback:
            callback(response, usage)

    def _stream_agent_output(
        self,
        generation: _DiscussionGeneration,
        llm: Any,
        agent_index: int,
        agent: AgentConfig,
        theory_label: str,
        start_response: AgentResponse,
        prompt: str,
        system_prompt: str,
        on_chunk: Callable[[AgentResponse], None] | None,
    ) -> tuple[str, dict[str, int] | None, Exception | None]:
        """Stream one provider request and stop consuming chunks once stale."""

        provider_usage: dict[str, int] | None = None

        def on_usage(usage: dict[str, int]) -> None:
            nonlocal provider_usage
            provider_usage = usage

        chunks: list[str] = []
        start_response.usage_available = False
        stream = None
        try:
            stream = llm.generate_stream(
                prompt=prompt,
                temperature=agent.temperature,
                max_tokens=agent.max_tokens,
                system_prompt=system_prompt,
                on_usage=on_usage,
                cancel_event=generation.cancelled,
            )
            if not self._register_generation_stream(generation, stream):
                return "", provider_usage, None
            for chunk in stream:
                if not self._is_current_generation(generation):
                    break
                chunks.append(chunk)
                if on_chunk:
                    on_chunk(
                        AgentResponse(
                            message_id=start_response.message_id,
                            agent_index=agent_index,
                            agent_name=agent.name,
                            perspective_number=agent.perspective_number,
                            theory_label=theory_label,
                            color=agent.color,
                            text=chunk,
                            is_complete=False,
                            status="in_progress",
                        )
                    )
        except Exception as error:
            return "".join(chunks), provider_usage, error
        finally:
            if stream is not None:
                self._unregister_generation_stream(generation, stream)
                self._close_provider_stream(stream)
        return "".join(chunks), provider_usage, None

    @staticmethod
    def _complete_agent_response(
        start_response: AgentResponse,
        agent_index: int,
        agent: AgentConfig,
        theory_label: str,
        text: str,
        error: str | None,
        error_code: str | None,
        error_params: dict[str, Any],
        provider_usage: dict[str, int] | None,
    ) -> AgentResponse:
        return AgentResponse(
            message_id=start_response.message_id,
            agent_index=agent_index,
            agent_name=agent.name,
            client_id=agent.client_id,
            perspective_number=agent.perspective_number,
            theory_label=theory_label,
            color=agent.color,
            text=text,
            is_complete=error is None,
            status="failed" if error else "completed",
            error=error,
            error_code=error_code or ("agent_generation_failed" if error else None),
            error_params=error_params,
            usage_available=True if provider_usage is not None else start_response.usage_available,
            prompt_tokens=(provider_usage or {}).get("prompt_tokens"),
            completion_tokens=(provider_usage or {}).get("completion_tokens"),
            total_tokens=(provider_usage or {}).get("total_tokens"),
            context_usage_available=start_response.context_usage_available,
            input_context_tokens=start_response.input_context_tokens,
            context_window_tokens=start_response.context_window_tokens,
            context_tokens_exact=start_response.context_tokens_exact,
            omitted_round_numbers=start_response.omitted_round_numbers,
        )

    def _provider_error_params(self, agent: AgentConfig) -> dict[str, Any]:
        """Return safe configured-host attribution for a provider failure."""
        resolved = self._configured_provider(
            agent.host_configuration_id,
            agent.api_host,
            agent.llm_id,
        )
        return {"host": resolved[1]} if resolved is not None else {}

    def _synthesis_request_failure(
        self,
        error: _ContextPreflightFailure | LLMRequestError,
        agent: AgentConfig,
    ) -> tuple[str, str, dict[str, Any]]:
        if isinstance(error, _ContextPreflightFailure):
            return str(error), error.code, error.params
        logger.warning("Round synthesis provider request failed: %s", error)
        code = (
            "generation_length_limit_reached"
            if isinstance(error, LLMGenerationLengthLimitError)
            else error.code
        )
        return str(error), code, self._provider_error_params(agent)

    def _ensure_nonempty_provider_result(
        self,
        *,
        text: str,
        error: str | None,
        error_code: str | None,
        error_params: dict[str, Any],
        agent: AgentConfig,
    ) -> tuple[str | None, str | None, dict[str, Any]]:
        if error is not None or text.strip():
            return error, error_code, error_params
        return (
            "The provider returned an empty response.",
            "provider_empty_response",
            self._provider_error_params(agent),
        )

    def _execute_agent(
        self,
        generation: _DiscussionGeneration,
        active_agents: list[tuple[int, AgentConfig]],
        position: int,
        agent_index: int,
        agent: AgentConfig,
        material_context: MaterialContext,
        effective_context_tokens: int,
        raw_user_prompt: str,
        context_state: DiscussionState | None,
        on_context_usage: Callable[[AgentResponse, ContextUsage], None] | None,
        on_chunk: Callable[[AgentResponse], None] | None,
        on_agent_start: Callable[[AgentResponse], None] | None,
    ) -> AgentResponse | None:
        """Run one perspective while keeping provider and cancellation boundaries explicit."""

        template = self._prompts.get(agent.prompt_id)
        theory_label = template.label if template else agent.name
        start_response = self._new_agent_start_response(agent_index, agent, theory_label)
        system_prompt = self.build_system_prompt(
            prompt_id=agent.prompt_id,
            agent_config=agent,
            agent_index=position,
            total_agents=len(active_agents),
            other_agents=self._other_agents(active_agents, agent_index),
            material_context=material_context,
        )
        text = ""
        error = None
        error_code = None
        error_params: dict[str, Any] = {}
        provider_usage: dict[str, int] | None = None
        start_emitted = False
        try:
            llm = self.llm_manager.get_llm(
                host=agent.api_host,
                api_key=agent.api_key,
                model_name=agent.llm_id,
                **(
                    {"host_configuration_id": agent.host_configuration_id}
                    if agent.host_configuration_id
                    else {}
                ),
            )
            if context_state is None:
                prompt = raw_user_prompt
                context_usage = self._preflight_context_usage(
                    llm=llm,
                    agent=agent,
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    context_tokens=effective_context_tokens,
                )
            else:
                previous_round = self.state.round_number - 1
                has_previous_round_note = (
                    previous_round > 0
                    and context_state.has_included_researcher_note_in_round(previous_round)
                )

                def build_context_prompt(context: str) -> str:
                    return append_perspective_user_reminders(
                        context,
                        target_language=material_context.target_language,
                        previous_round=previous_round,
                        has_previous_round_note=has_previous_round_note,
                    )

                prompt, context_usage = self._prepare_context_limited_prompt(
                    llm=llm,
                    agent=agent,
                    system_prompt=system_prompt,
                    effective_context_tokens=effective_context_tokens,
                    before_round=self.state.round_number,
                    context_state=context_state,
                    build_user_prompt=build_context_prompt,
                )
            self._emit_context_usage(start_response, context_usage, on_context_usage)
            if on_agent_start:
                on_agent_start(start_response)
            start_emitted = True
            logger.info(
                "Agent '%s' starts LLM request (host=%s, model=%s, max_tokens=%s)",
                agent.name,
                getattr(llm, "host", "n/a"),
                getattr(llm, "model_name", "n/a"),
                agent.max_tokens,
            )
            text, provider_usage, stream_error = self._stream_agent_output(
                generation,
                llm,
                agent_index,
                agent,
                theory_label,
                start_response,
                prompt,
                system_prompt,
                on_chunk,
            )
            if stream_error is not None:
                raise stream_error
        except _ContextPreflightFailure as exc:
            if exc.usage is not None:
                self._emit_context_usage(start_response, exc.usage, on_context_usage)
            if on_agent_start:
                on_agent_start(start_response)
            start_emitted = True
            error, error_code, error_params = str(exc), exc.code, exc.params
        except LLMGenerationLengthLimitError as exc:
            logger.warning("LLM generation length limit for %s: %s", agent.name, exc)
            error, error_code = str(exc), "generation_length_limit_reached"
        except LLMRequestError as exc:
            logger.warning("Provider request failed for %s: %s", agent.name, exc)
            error = str(exc)
            error_code = exc.code
            error_params = self._provider_error_params(agent)
        except Exception as exc:
            logger.error("LLM failure for %s: %s", agent.name, exc)
            error = str(exc)
        if error is not None and not start_emitted and on_agent_start:
            on_agent_start(start_response)
        if not self._is_current_generation(generation):
            return None
        error, error_code, error_params = self._ensure_nonempty_provider_result(
            text=text,
            error=error,
            error_code=error_code,
            error_params=error_params,
            agent=agent,
        )
        return self._complete_agent_response(
            start_response,
            agent_index,
            agent,
            theory_label,
            text,
            error,
            error_code,
            error_params,
            provider_usage,
        )

    def _run_agent_round(
        self,
        generation: _DiscussionGeneration,
        active_agents: list[tuple[int, AgentConfig]],
        material_context: MaterialContext,
        effective_context_tokens: int,
        raw_user_prompt: str,
        context_state_for_position: Callable[[int, list[AgentResponse]], DiscussionState | None],
        on_context_usage: Callable[[AgentResponse, ContextUsage], None] | None,
        on_chunk: Callable[[AgentResponse], None] | None,
        on_agent_start: Callable[[AgentResponse], None] | None,
        on_agent_complete: Callable[[AgentResponse], None] | None,
    ) -> list[AgentResponse]:
        """Execute the roster in order and publish only current-generation completions."""

        results: list[AgentResponse] = []
        for position, (agent_index, agent) in enumerate(active_agents):
            if not self._is_current_generation(generation):
                break
            response = self._execute_agent(
                generation,
                active_agents,
                position,
                agent_index,
                agent,
                material_context,
                effective_context_tokens,
                raw_user_prompt,
                context_state_for_position(position, results),
                on_context_usage,
                on_chunk,
                on_agent_start,
            )
            if response is None:
                break
            results.append(response)
            if on_agent_complete:
                self._mutate_state_if_current(
                    generation,
                    lambda response=response: on_agent_complete(response),
                )
        return results

    @staticmethod
    def _initial_round_context_state(
        round_start_state: DiscussionState,
        position: int,
        results: list[AgentResponse],
        sequential_mode: bool,
    ) -> DiscussionState | None:
        """Build later-perspective context without mutating the saved round state."""

        if not sequential_mode or position == 0:
            return None
        sequential_state = deepcopy(round_start_state)
        for response in results:
            sequential_state.add_agent_response(response)
        return sequential_state

    def _continuation_roster(
        self, agents: list[AgentConfig]
    ) -> tuple[list[tuple[int, AgentConfig]], bool]:
        """Return the executable roster and whether this round has any terminal work."""

        active_agents = [(index, agent) for index, agent in enumerate(agents) if agent.is_active]
        synthesis_enabled = bool(self._synthesis_config and self._synthesis_config.enabled)
        return active_agents, bool(active_agents or synthesis_enabled)

    def run_discussion(
        self,
        material: str,
        question: str,
        agents: list[AgentConfig],
        material_context: MaterialContext | None = None,
        on_context_usage: Callable[[AgentResponse, ContextUsage], None] | None = None,
        on_chunk: Callable[[AgentResponse], None] | None = None,
        on_agent_start: Callable[[AgentResponse], None] | None = None,
        on_agent_complete: Callable[[AgentResponse], None] | None = None,
        on_synthesis_start: Callable[[SynthesisResponse], None] | None = None,
        on_synthesis_chunk: Callable[[SynthesisResponse], None] | None = None,
        on_synthesis_complete: Callable[[SynthesisResponse], None] | None = None,
        on_all_complete: Callable[[], None] | None = None,
        sequential_mode: bool = False,
        *,
        _generation: _DiscussionGeneration | None = None,
    ) -> list[AgentResponse]:
        """Run all active agents and deliver lifecycle events through callbacks.

        ``_generation`` scopes every state mutation to one run; external callers
        must leave it unset.
        """
        agents = list(agents)
        effective_material_context = material_context or self._material_context
        if effective_material_context is None or not effective_material_context.target_language:
            raise TargetLanguageRequiredError()
        # The synchronous public entrypoint can be used without
        # ``start_new_discussion``. Keep the context available to its optional
        # synthesis phase as well, so every provider call uses the same
        # language contract.
        self._material_context = effective_material_context
        generation = _generation if _generation is not None else self._begin_generation()
        with self._run_lock:
            self.state.round_status = "in_progress"

        # Only enabled, fully configured agents execute.
        active_agents = [(i, a) for i, a in enumerate(agents) if a.is_active]

        if not active_agents:
            logger.warning("Keine aktiven Agenten für Diskussion")
            # A configured synthesis still closes this otherwise empty round
            # with its deterministic no-usable-contributions card.  This
            # gives the moderator a terminal result instead of making an
            # enabled feature silently disappear when all perspectives are
            # disabled.
            self._run_round_synthesis(
                generation=generation,
                question=question,
                active_agents=[],
                responses=[],
                on_start=on_synthesis_start,
                on_chunk=on_synthesis_chunk,
                on_complete=on_synthesis_complete,
            )
            if on_all_complete:
                on_all_complete()
            return []

        def get_other_agents(current_idx: int) -> list[tuple[str, str]]:
            """Return label pairs for all agents except the current one."""
            others = []
            for idx, agent in active_agents:
                if idx != current_idx:
                    template = self._prompts.get(agent.prompt_id)
                    label = template.label if template else agent.name
                    others.append((f"Perspective {agent.perspective_number}", label))
            return others

        # The normal entrypoint has already stored the opening user task.
        # Render that state so first-round, independent, and sequential calls
        # share the same authoritative-material/transcript contract.  The
        # public synchronous helper can still be called without setup state;
        # it receives the equivalent pure first-round envelope below.
        has_current_user_message = any(
            message.role == "user" and message.round_number == self.state.round_number
            for message in self.state.messages
        )
        user_prompt = (
            append_response_language_reminder(
                self.state.get_context_for_agents(),
                effective_material_context.target_language,
            )
            if has_current_user_message
            else self.build_user_prompt(
                material,
                question,
                material_context=effective_material_context,
            )
        )

        results: list[AgentResponse] = []
        effective_context_tokens = self._effective_context_tokens(
            [agent for _, agent in active_agents]
        )
        # Keep the public synchronous method semantically complete too: its
        # caller need not provide the API's persistence callback for later
        # sequential perspectives to see earlier answers.
        round_start_state = deepcopy(self.state)
        if not has_current_user_message:
            # Direct callers of ``run_discussion`` do not go through
            # ``start_new_discussion``. Build a non-persisted equivalent
            # state for later sequential perspectives.
            round_start_state.round_number = max(1, round_start_state.round_number)
            if not round_start_state.material:
                round_start_state.material = material
            round_start_state.add_user_message(question)

        results = self._run_agent_round(
            generation=generation,
            active_agents=active_agents,
            material_context=effective_material_context,
            effective_context_tokens=effective_context_tokens,
            raw_user_prompt=user_prompt,
            context_state_for_position=lambda position, responses: (
                self._initial_round_context_state(
                    round_start_state,
                    position,
                    responses,
                    sequential_mode,
                )
            ),
            on_context_usage=on_context_usage,
            on_chunk=on_chunk,
            on_agent_start=on_agent_start,
            on_agent_complete=on_agent_complete,
        )

        # Serialize round-memory mutation with persistence under the state guard.
        self._mutate_state_if_current(
            generation,
            lambda: self._store_round_memory(question, results),
        )

        self._run_round_synthesis(
            generation=generation,
            question=question,
            active_agents=active_agents,
            responses=results,
            on_start=on_synthesis_start,
            on_chunk=on_synthesis_chunk,
            on_complete=on_synthesis_complete,
        )

        if on_all_complete:
            on_all_complete()

        return results

    def _invoke_if_current_locked(
        self,
        generation: _DiscussionGeneration,
        callback: Callable[[], None],
    ) -> bool:
        """Execute ``callback`` only while ``generation`` is still active.

        ``_run_lock`` must be held; the current-generation test and the
        callback run atomically. Used to guard state mutation/persistence
        inside completion/autosave wrappers.
        """
        if self._is_current_generation_locked(generation):
            callback()
            return True
        return False

    def _mutate_state_if_current(
        self,
        generation: _DiscussionGeneration,
        mutation: Callable[[], None],
    ) -> bool:
        """Atomically test generation and run ``mutation`` under ``_run_lock``."""
        with self._run_lock:
            return self._invoke_if_current_locked(generation, mutation)

    def _save_state_if_current(
        self,
        generation: _DiscussionGeneration,
        save_fn: Callable[[], Path | None],
    ) -> Path | None:
        """Atomically test generation and run ``save_fn`` under ``_run_lock``."""
        result: Path | None = None

        def guarded():
            nonlocal result
            result = save_fn()

        self._mutate_state_if_current(generation, guarded)
        return result

    def run_discussion_async(
        self,
        material: str,
        question: str,
        agents: list[AgentConfig],
        material_context: MaterialContext | None = None,
        on_context_usage: Callable[[AgentResponse, ContextUsage], None] | None = None,
        on_chunk: Callable[[AgentResponse], None] | None = None,
        on_agent_start: Callable[[AgentResponse], None] | None = None,
        on_agent_complete: Callable[[AgentResponse], None] | None = None,
        on_synthesis_start: Callable[[SynthesisResponse], None] | None = None,
        on_synthesis_chunk: Callable[[SynthesisResponse], None] | None = None,
        on_synthesis_complete: Callable[[SynthesisResponse], None] | None = None,
        on_all_complete: Callable[[], None] | None = None,
        on_unexpected_error: Callable[[], None] | None = None,
        sequential_mode: bool = False,
        *,
        _generation: _DiscussionGeneration | None = None,
    ) -> DiscussionMessage:
        """Run ``run_discussion`` in a daemon worker and return immediately."""
        generation = _generation if _generation is not None else self._begin_generation()

        def run_worker() -> None:
            try:
                self.run_discussion(
                    material,
                    question,
                    agents,
                    material_context=material_context,
                    on_context_usage=on_context_usage,
                    on_chunk=on_chunk,
                    on_agent_start=on_agent_start,
                    on_agent_complete=on_agent_complete,
                    on_synthesis_start=on_synthesis_start,
                    on_synthesis_chunk=on_synthesis_chunk,
                    on_synthesis_complete=on_synthesis_complete,
                    on_all_complete=on_all_complete,
                    sequential_mode=sequential_mode,
                    _generation=generation,
                )
            except Exception:
                logger.exception("Unexpected discussion worker failure")
                self._mark_generation_finished(generation)
                if on_unexpected_error:
                    on_unexpected_error()

        thread = threading.Thread(target=run_worker)
        thread.daemon = True
        thread.start()

    def start_new_discussion(  # noqa: C901
        self,
        material: str,
        question: str,
        agents: list[AgentConfig],
        title: str = "",
        material_context: MaterialContext | None = None,
        on_context_usage: Callable[[AgentResponse, ContextUsage], None] | None = None,
        on_chunk: Callable[[AgentResponse], None] | None = None,
        on_agent_start: Callable[[AgentResponse], None] | None = None,
        on_agent_complete: Callable[[AgentResponse], None] | None = None,
        synthesis_config: SynthesisConfig | None = None,
        on_synthesis_start: Callable[[SynthesisResponse], None] | None = None,
        on_synthesis_chunk: Callable[[SynthesisResponse], None] | None = None,
        on_synthesis_complete: Callable[[SynthesisResponse], None] | None = None,
        on_all_complete: Callable[[], None] | None = None,
        on_unexpected_error: Callable[[], None] | None = None,
        sequential_mode: bool = False,
    ) -> None:
        """Create, persist, and start the first round of a discussion."""
        # Acquire lifecycle ownership *before* any shared state mutation so a
        # still-deferred old child can never wake up and supersede this run.
        with self._run_lock:
            agents = list(agents)
            self._validate_agent_configurations(agents)
            effective_material_context = material_context or MaterialContext()
            # Validation must precede generation allocation and shared-state mutation.
            if not material.strip():
                raise MaterialRequiredError()
            if not effective_material_context.target_language:
                raise TargetLanguageRequiredError()

            generation = self._begin_generation_locked()
            self._generation_running = True

            # The new generation must own the state before replacing it.
            self.state.clear()
            self.state.initial_question = question
            self.state.round_number = 1
            self.state.round_status = "in_progress"

            effective_material_context.session_type = self._normalize_session_type(
                effective_material_context.session_type
            )
            definition = self.session_type_repo.get(effective_material_context.session_type)
            if definition is not None:
                # Capture the current schema on the discussion itself.  This
                # protects resumed sessions from subsequent editor changes.
                effective_material_context.set_session_inputs(list(definition.session_inputs))
                effective_material_context.include_unchanged_research_material_context_in_prompt = (
                    definition.include_unchanged_research_material_context_in_prompt
                )
            self._material_context = effective_material_context

            self._sequential_mode = bool(sequential_mode)
            self._synthesis_config = deepcopy(synthesis_config)
            self._round_provider_provenance = {}

            # Line numbers make model references stable in stored and exported sessions.
            if material and material_type_uses_line_numbers(
                effective_material_context.material_type
            ):
                self.state.material = add_line_numbers_to_material(material)
            else:
                self.state.material = material

            # A non-empty explicit title takes precedence over the generated title.
            now = datetime.now()
            if title and title.strip():
                resolved_title = title.strip()
            else:
                resolved_title = generate_default_discussion_title(now, self.state.material)

            self._current_stored = self.storage.create_new(resolved_title)
            self._current_stored.prompt_snapshot = self._create_prompt_snapshot(
                effective_material_context, definition
            )
            self._current_agents = list(agents)
            self._round_provider_provenance[1] = self._capture_provider_provenance(
                agents,
                self._synthesis_config,
                self._current_stored.prompt_snapshot,
            )

            # The setup task is stored as the moderator's opening message.
            # During round one it is rendered only at the current-task
            # boundary; from later rounds onward it appears once in history.
            user_message = self.state.add_user_message(question)

            # A new session must be recoverable before its worker can run or block.
            self._save_current_state_locked()

            def on_agent_start_with_save(response: AgentResponse):
                self._mutate_state_if_current(
                    generation,
                    lambda: self.state.upsert_agent_response(response),
                )
                if on_agent_start and self._is_current_generation(generation):
                    on_agent_start(response)

            def on_chunk_with_save(response: AgentResponse):
                self._mutate_state_if_current(
                    generation,
                    lambda: self.state.upsert_agent_response(response, append_text=True),
                )
                if on_chunk and self._is_current_generation(generation):
                    on_chunk(response)

            # Persist completed responses only while this generation is current.
            # A cancelled/stale worker cannot mutate a newer run's state.
            def on_complete_with_save(response: AgentResponse):
                def add_response():
                    self.state.add_agent_response(response)

                self._mutate_state_if_current(generation, add_response)
                if on_agent_complete and self._is_current_generation(generation):
                    on_agent_complete(response)

            # Persist completion only for the current generation; the outer
            # callback is still invoked so stale SSE generators can terminate.
            def on_all_complete_with_save():
                self._finish_generation_with_status(generation)
                if on_all_complete:
                    on_all_complete()

            def on_synthesis_start_with_save(response: SynthesisResponse):
                self._mutate_state_if_current(
                    generation,
                    lambda: self.state.upsert_synthesis_response(response),
                )
                if on_synthesis_start and self._is_current_generation(generation):
                    on_synthesis_start(response)

            def on_synthesis_chunk_with_save(response: SynthesisResponse):
                self._mutate_state_if_current(
                    generation,
                    lambda: self.state.upsert_synthesis_response(response, append_text=True),
                )
                if on_synthesis_chunk and self._is_current_generation(generation):
                    on_synthesis_chunk(response)

            def on_synthesis_complete_with_save(response: SynthesisResponse):
                self._mutate_state_if_current(
                    generation,
                    lambda: self.state.add_synthesis_response(response),
                )
                if on_synthesis_complete and self._is_current_generation(generation):
                    on_synthesis_complete(response)

            def on_unexpected_error_with_save():
                self._fail_generation(generation)
                if on_unexpected_error:
                    on_unexpected_error()

            self.run_discussion_async(
                material=self.state.material,
                question=question,
                agents=agents,
                material_context=effective_material_context,
                on_context_usage=on_context_usage,
                on_chunk=on_chunk_with_save,
                on_agent_start=on_agent_start_with_save,
                on_agent_complete=on_complete_with_save,
                on_synthesis_start=on_synthesis_start_with_save,
                on_synthesis_chunk=on_synthesis_chunk_with_save,
                on_synthesis_complete=on_synthesis_complete_with_save,
                on_all_complete=on_all_complete_with_save,
                on_unexpected_error=on_unexpected_error_with_save,
                sequential_mode=sequential_mode,
                _generation=generation,
            )
        return user_message

    def continue_discussion(  # noqa: C901
        self,
        user_input: str,
        agents: list[AgentConfig],
        focus_segment: str | None = None,
        on_context_usage: Callable[[AgentResponse, ContextUsage], None] | None = None,
        on_chunk: Callable[[AgentResponse], None] | None = None,
        on_agent_start: Callable[[AgentResponse], None] | None = None,
        on_agent_complete: Callable[[AgentResponse], None] | None = None,
        on_synthesis_start: Callable[[SynthesisResponse], None] | None = None,
        on_synthesis_chunk: Callable[[SynthesisResponse], None] | None = None,
        on_synthesis_complete: Callable[[SynthesisResponse], None] | None = None,
        on_all_complete: Callable[[], None] | None = None,
        on_unexpected_error: Callable[[], None] | None = None,
        sequential_mode: bool = False,
        rebind_configuration_id: str | None = None,
        rebind_model_id: str | None = None,
    ) -> DiscussionMessage | None:
        """Continue the open discussion with one moderator follow-up."""
        # Acquire lifecycle ownership before checking or mutating shared
        # state. Otherwise reset/open can clear the session between a stale
        # pre-lock check and the continuation's first mutation.
        with self._run_lock:
            agents = list(agents)
            self._validate_agent_configurations(agents)
            if self.state.round_number == 0:
                logger.warning("Keine aktive Diskussion zum Fortsetzen")
                return None

            # Persisted sessions without a target language remain
            # readable/exportable. Continuing requires an explicit
            # output-language contract before another model call.
            if self._current_stored is not None and not (
                self._material_context and self._material_context.target_language
            ):
                raise TargetLanguageRequiredError()

            agents, next_synthesis = self.resolve_continuation_configuration(
                agents,
                rebind_configuration_id=rebind_configuration_id,
                rebind_model_id=rebind_model_id,
            )

            previous_synthesis = self._synthesis_config
            self._synthesis_config = next_synthesis
            try:
                self._require_current_continuation_providers(agents)
            except Exception:
                self._synthesis_config = previous_synthesis
                raise

            # Validate the executable roster before beginning a generation or
            # changing round/session state. A rejected continuation must be a
            # true no-op in memory as well as on disk.
            active_agents, has_terminal_work = self._continuation_roster(agents)
            if not has_terminal_work:
                logger.warning("Keine aktiven Agenten für Folgerunde")
                self._synthesis_config = previous_synthesis
                if on_all_complete:
                    on_all_complete()
                return None

            previous_state = deepcopy(self.state)
            previous_agents = list(self._current_agents)
            previous_sequential_mode = self._sequential_mode
            previous_provenance = deepcopy(self._round_provider_provenance)
            previous_generation = self._active_generation
            previous_generation_running = self._generation_running
            previous_stored = deepcopy(self._current_stored)

            # Authoritative round increment — must happen *before* the
            # context builder reads state.round_number and *before* the
            # editable roster is synced so the new agents are tagged
            # with the upcoming round.
            self.state.round_number += 1
            self.state.round_status = "in_progress"

            # Sync the editable roster + sequential-mode flag with
            # the caller's current values.  These two mirrors are part
            # of the resume contract: a follow-up PUT /api/sessions/...
            # /open and the upcoming context construction must see
            # exactly what the UI just sent.  The authoritative round
            # increment above happens *first* so the in-memory
            # current state is always consistent before the new
            # roster is captured for the next round.
            self._current_agents = list(agents)
            self._sequential_mode = bool(sequential_mode)
            self._round_provider_provenance[self.state.round_number] = (
                self._capture_provider_provenance(agents, self._synthesis_config)
            )

            # Store the full moderator task once.  Prompts only add a generic
            # instruction around this rendered context, preventing the
            # follow-up input from appearing twice.
            user_message = self.state.add_user_message(
                self._moderator_message_content(user_input, focus_segment)
            )
            round_start_state = deepcopy(self.state)

            # A continuation is recoverable immediately, before its first
            # provider byte arrives.
            try:
                self._save_current_state_locked()
            except Exception:
                self.state = previous_state
                self._current_agents = previous_agents
                self._sequential_mode = previous_sequential_mode
                self._synthesis_config = previous_synthesis
                self._round_provider_provenance = previous_provenance
                self._active_generation = previous_generation
                self._generation_running = previous_generation_running
                self._current_stored = previous_stored
                raise

            generation = self._begin_generation_locked()
            self._generation_running = True

            def on_agent_start_with_save(response: AgentResponse):
                self._mutate_state_if_current(
                    generation,
                    lambda: self.state.upsert_agent_response(response),
                )
                if on_agent_start and self._is_current_generation(generation):
                    on_agent_start(response)

            def on_chunk_with_save(response: AgentResponse):
                self._mutate_state_if_current(
                    generation,
                    lambda: self.state.upsert_agent_response(response, append_text=True),
                )
                if on_chunk and self._is_current_generation(generation):
                    on_chunk(response)

            # Persist completed responses only while this generation is current.
            def on_complete_with_save(response: AgentResponse):
                def add_response():
                    self.state.add_agent_response(response)

                self._mutate_state_if_current(generation, add_response)
                if on_agent_complete and self._is_current_generation(generation):
                    on_agent_complete(response)

            effective_context_tokens = self._effective_context_tokens(
                [agent for _, agent in active_agents]
            )

            _save_current_state = self._save_current_state

            # Persist completion only for the current generation; the outer
            # callback is still invoked so stale SSE generators can terminate.
            def on_all_complete_with_save():
                self._finish_generation_with_status(generation)
                if on_all_complete:
                    on_all_complete()

            def on_synthesis_complete_with_save(response: SynthesisResponse):
                self._mutate_state_if_current(
                    generation,
                    lambda: self.state.add_synthesis_response(response),
                )
                if on_synthesis_complete and self._is_current_generation(generation):
                    on_synthesis_complete(response)

            def on_synthesis_start_with_save(response: SynthesisResponse):
                self._mutate_state_if_current(
                    generation,
                    lambda: self.state.upsert_synthesis_response(response),
                )
                if on_synthesis_start and self._is_current_generation(generation):
                    on_synthesis_start(response)

            def on_synthesis_chunk_with_save(response: SynthesisResponse):
                self._mutate_state_if_current(
                    generation,
                    lambda: self.state.upsert_synthesis_response(response, append_text=True),
                )
                if on_synthesis_chunk and self._is_current_generation(generation):
                    on_synthesis_chunk(response)

            def on_unexpected_error_with_save():
                self._fail_generation(generation)
                if on_unexpected_error:
                    on_unexpected_error()

        def run_round() -> None:
            try:
                results = self._run_agent_round(
                    generation=generation,
                    active_agents=active_agents,
                    material_context=self._material_context,
                    effective_context_tokens=effective_context_tokens,
                    raw_user_prompt="",
                    context_state_for_position=lambda position, _responses: (
                        self.state if sequential_mode and position > 0 else round_start_state
                    ),
                    on_context_usage=on_context_usage,
                    on_chunk=on_chunk_with_save,
                    on_agent_start=on_agent_start_with_save,
                    on_agent_complete=on_complete_with_save,
                )
                self._mutate_state_if_current(
                    generation,
                    lambda: self._store_round_memory(user_input, results),
                )
                self._run_round_synthesis(
                    generation=generation,
                    question=user_input,
                    active_agents=active_agents,
                    responses=results,
                    on_start=on_synthesis_start_with_save,
                    on_chunk=on_synthesis_chunk_with_save,
                    on_complete=on_synthesis_complete_with_save,
                )
                on_all_complete_with_save()
            except Exception:
                logger.exception("Unexpected continuation worker failure")
                on_unexpected_error_with_save()

        thread = threading.Thread(target=run_round)
        thread.daemon = True
        thread.start()
        return user_message

    def reset_discussion(self) -> None:
        """Clear the live discussion and invalidate its active generation."""
        with self._run_lock:
            active = self._active_generation
            if active is not None:
                active.cancelled.set()
            self.state.clear()
            self._current_stored = None
            self._current_agents = []
            self._material_context = None
            self._sequential_mode = False
            self._synthesis_config = None
            self._round_provider_provenance = {}
            self._generation_running = False

    @property
    def has_active_discussion(self) -> bool:
        """Return whether a discussion has an active round."""
        return self.state.round_number > 0

    def _save_current_state(self) -> Path | None:
        """Persist the live state while holding the service run lock."""
        with self._run_lock:
            return self._save_current_state_locked()

    def _save_current_state_locked(self) -> Path | None:
        """Persist the live state; caller must hold ``_run_lock``."""
        if self._current_stored is None:
            return None

        self._current_stored.material = self.state.material
        self._current_stored.initial_question = self.state.initial_question
        if self._material_context is not None:
            self._current_stored.material_type = self._material_context.material_type
            self._current_stored.session_type = self._normalize_session_type(
                self._material_context.session_type
            )
            self._current_stored.target_language = self._material_context.target_language
            self._current_stored.session_input_values = dict(
                self._material_context.session_input_values
            )
            self._current_stored.session_inputs = [
                item.model_dump(mode="json", exclude_none=True)
                for item in self._material_context.session_inputs
            ]
            self._current_stored.include_unchanged_research_material_context_in_prompt = bool(
                self._material_context.include_unchanged_research_material_context_in_prompt
            )
        else:
            raise RuntimeError("cannot persist a discussion without material context")

        self._current_stored.sequential_mode = bool(self._sequential_mode)
        config = getattr(self, "_synthesis_config", None) or SynthesisConfig(
            enabled=False, api_host=None, llm_id=None, temperature=None
        )
        self._current_stored.synthesis = StoredSynthesisConfig(
            enabled=bool(config.enabled),
            api_host=config.api_host,
            llm_id=config.llm_id,
            host_configuration_id=config.host_configuration_id,
            host_label=config.host_label,
            temperature=config.temperature,
        )

        # Persist the full editable roster, including disabled agents, but never API keys.
        self._current_stored.agents = [
            StoredAgent(
                name=a.name,
                client_id=a.client_id,
                prompt_id=a.prompt_id or "",
                prompt_label=(
                    # A stale prompt ID falls back to the display name during autosave.
                    str(snapshot_role.get("label"))
                    if (
                        (snapshot := self._prompt_snapshot()) is not None
                        and (snapshot_role := self._snapshot_role(snapshot, a.prompt_id or ""))
                        is not None
                    )
                    else (
                        template.label
                        if (template := self._prompts.get(a.prompt_id)) is not None
                        else a.name
                    )
                ),
                color=a.color,
                temperature=a.temperature,
                llm_id=a.llm_id,
                api_host=a.api_host,
                host_configuration_id=a.host_configuration_id,
                host_label=a.host_label,
                max_tokens=a.max_tokens,
                enabled=bool(a.enabled),
                perspective_number=a.perspective_number,
            )
            for a in self._current_agents
        ]

        # Group messages into their persisted rounds.
        self._sync_messages_to_rounds()

        return self.storage.save(self._current_stored)

    def _sync_messages_to_rounds(self) -> None:
        """Synchronize live messages into persisted round structures."""
        if self._current_stored is None:
            return

        # Rebuild persisted rounds from the live message sequence.
        rounds: dict[int, StoredRound] = {}

        for msg in self.state.messages:
            current_round = max(1, getattr(msg, "round_number", 1))
            if msg.role == "user":
                # A moderator message begins its round.
                if current_round not in rounds:
                    rounds[current_round] = StoredRound(
                        round_number=current_round,
                        status=(
                            self.state.round_status
                            if current_round == self.state.round_number
                            else "completed"
                        ),
                        provider_provenance=list(
                            self._round_provider_provenance.get(current_round, [])
                        ),
                    )

                rounds[current_round].messages.append(
                    StoredMessage(
                        id=msg.id,
                        role="user",
                        content=msg.content,
                        status=msg.status,
                        include_in_agent_context=msg.include_in_agent_context,
                        note=msg.note,
                        include_note_in_agent_context=msg.include_note_in_agent_context,
                    )
                )
            elif msg.role in {"agent", "synthesis"}:
                if current_round not in rounds:
                    rounds[current_round] = StoredRound(
                        round_number=current_round,
                        status=(
                            self.state.round_status
                            if current_round == self.state.round_number
                            else "completed"
                        ),
                        provider_provenance=list(
                            self._round_provider_provenance.get(current_round, [])
                        ),
                    )

                # Keep the persisted agent identity and completion metadata.
                rounds[current_round].messages.append(
                    StoredMessage(
                        id=msg.id,
                        role=msg.role,
                        content=msg.content,
                        status=msg.status,
                        agent_name=msg.agent_name,
                        theory_label=msg.theory_label,
                        include_in_agent_context=(
                            False if msg.role == "synthesis" else msg.include_in_agent_context
                        ),
                        note=msg.note,
                        include_note_in_agent_context=msg.include_note_in_agent_context,
                        client_id=msg.client_id,
                        color=msg.color,
                        agent_index=msg.agent_index,
                        perspective_number=msg.perspective_number,
                        error=msg.error,
                        error_code=msg.error_code,
                        error_params=dict(msg.error_params),
                        usage_available=msg.usage_available,
                        prompt_tokens=msg.prompt_tokens,
                        completion_tokens=msg.completion_tokens,
                        total_tokens=msg.total_tokens,
                        context_usage_available=msg.context_usage_available,
                        input_context_tokens=msg.input_context_tokens,
                        context_window_tokens=msg.context_window_tokens,
                        context_tokens_exact=msg.context_tokens_exact,
                        omitted_round_numbers=list(msg.omitted_round_numbers),
                    )
                )

        # Round ordering follows the current message round numbers.
        self._current_stored.rounds = [rounds[key] for key in sorted(rounds)]

    def _hydrate_from_stored_locked(self, stored: StoredDiscussion) -> None:
        """Atomically replace the live state with the given StoredDiscussion.

        Caller must hold ``_run_lock``.
        """
        self.state.clear()
        self.state.material = stored.material
        self.state.initial_question = stored.initial_question
        self.state.round_status = None

        for round_data in stored.rounds:
            self.state.round_number = max(self.state.round_number, round_data.round_number)
            if round_data.round_number == self.state.round_number:
                self.state.round_status = round_data.status
            for msg in round_data.messages:
                if msg.role == "user":
                    self.state.messages.append(
                        DiscussionMessage(
                            id=msg.id,
                            role="user",
                            content=msg.content,
                            round_number=round_data.round_number,
                            status=msg.status,
                            include_in_agent_context=msg.include_in_agent_context,
                            note=msg.note,
                            include_note_in_agent_context=msg.include_note_in_agent_context,
                        )
                    )
                elif msg.role in {"agent", "synthesis"}:
                    self.state.messages.append(
                        DiscussionMessage(
                            id=msg.id,
                            role=msg.role,
                            content=msg.content,
                            round_number=round_data.round_number,
                            status=msg.status,
                            agent_name=msg.agent_name,
                            theory_label=msg.theory_label,
                            include_in_agent_context=(
                                False if msg.role == "synthesis" else msg.include_in_agent_context
                            ),
                            note=msg.note,
                            include_note_in_agent_context=msg.include_note_in_agent_context,
                            color=msg.color,
                            agent_index=msg.agent_index,
                            perspective_number=msg.perspective_number,
                            client_id=msg.client_id,
                            error=msg.error,
                            error_code=msg.error_code,
                            error_params=dict(msg.error_params),
                            usage_available=msg.usage_available,
                            prompt_tokens=msg.prompt_tokens,
                            completion_tokens=msg.completion_tokens,
                            total_tokens=msg.total_tokens,
                            context_usage_available=msg.context_usage_available,
                            input_context_tokens=msg.input_context_tokens,
                            context_window_tokens=msg.context_window_tokens,
                            context_tokens_exact=msg.context_tokens_exact,
                            omitted_round_numbers=tuple(msg.omitted_round_numbers),
                        )
                    )

        self._current_stored = stored
        # Rehydrate disabled agents for editing; execution filters them via ``is_active``.
        self._current_agents = [
            AgentConfig(
                name=agent.name,
                client_id=agent.client_id,
                prompt_id=agent.prompt_id or None,
                color=agent.color,
                temperature=agent.temperature,
                llm_id=agent.llm_id,
                api_host=agent.api_host,
                host_configuration_id=agent.host_configuration_id,
                host_label=agent.host_label,
                max_tokens=agent.max_tokens,
                enabled=bool(agent.enabled),
                perspective_number=agent.perspective_number,
                # Provider credentials are resolved at request time, never from snapshots.
            )
            for agent in stored.agents
        ]
        stored_inputs = [
            SessionInputDefinition.model_validate(item) for item in stored.session_inputs
        ]
        self._material_context = MaterialContext(
            material_type=stored.material_type,
            session_type=self._normalize_session_type(stored.session_type),
            target_language=stored.target_language,
            session_input_values=dict(stored.session_input_values),
            session_inputs=stored_inputs,
            include_unchanged_research_material_context_in_prompt=(
                stored.include_unchanged_research_material_context_in_prompt
            ),
        )
        self._sequential_mode = bool(stored.sequential_mode)
        self._synthesis_config = SynthesisConfig(
            enabled=stored.synthesis.enabled,
            api_host=stored.synthesis.api_host,
            llm_id=stored.synthesis.llm_id,
            host_configuration_id=stored.synthesis.host_configuration_id,
            host_label=stored.synthesis.host_label,
            temperature=stored.synthesis.temperature,
        )
        self._round_provider_provenance = {
            round_data.round_number: list(round_data.provider_provenance)
            for round_data in stored.rounds
        }

    def open_session(self, file_id: str) -> bool:
        """Open one exact safe session id and invalidate any older generation.

        Hydration restores the persisted material, messages, context, roster,
        and sequential setting without exposing provider secrets.
        """
        with self._run_lock:
            filepath = self.storage.resolve_file_id(file_id)
            if filepath is None:
                return False

            # Invalidate any in-flight generation so a deferred old
            # worker can never mutate the state we are about to
            # hydrate.  We register a fresh generation token so any
            # later auto-save is also bound to a real current run.
            active = self._active_generation
            if active is not None and self._generation_running:
                active.cancelled.set()
                self.state.round_status = "interrupted"
                self._mark_current_round_messages("interrupted")
                self._generation_running = False
                self._save_current_state_locked()
            self._begin_generation_locked()

            stored = self.storage.load(file_id)
            if stored is None:
                return False
            self._hydrate_from_stored_locked(stored)
            return True

    def list_sessions(self) -> list[dict[str, Any]]:
        """List path-free metadata for every persisted discussion."""
        return self.storage.list_all()

    def current_session_file_id(self) -> str | None:
        """Return the canonical id of the currently open session, if any."""
        with self._run_lock:
            if self._current_stored is None:
                return None
            return self.storage.file_id_for(self._current_stored)

    def current_session_title(self) -> str | None:
        """Return the title of the currently open session, if any."""
        with self._run_lock:
            return self._current_stored.title if self._current_stored is not None else None

    def rename_session(self, file_id: str, new_title: str) -> bool:
        """Rename a session and update the open in-memory snapshot atomically."""
        with self._run_lock:
            ok = self.storage.rename(file_id, new_title)
            if (
                ok
                and self._current_stored is not None
                and self._current_stored.title != new_title
                and self.current_session_file_id() == file_id
            ):
                self._current_stored.title = new_title
            return ok

    def set_session_favorite(self, file_id: str, is_favorite: bool) -> bool:
        """Update a session favorite flag and its open snapshot atomically."""
        with self._run_lock:
            ok = self.storage.set_favorite(file_id, bool(is_favorite))
            if (
                ok
                and self._current_stored is not None
                and self._current_stored.is_favorite != bool(is_favorite)
                and self.current_session_file_id() == file_id
            ):
                self._current_stored.is_favorite = bool(is_favorite)
            return ok

    def delete_session(self, file_id: str) -> dict[str, Any]:
        """Delete one safe session id and clear live state only if it was open."""
        with self._run_lock:
            filepath = self.storage.resolve_file_id(file_id)
            if filepath is None:
                return {"deleted": False, "deleted_ids": [], "was_active": False}

            was_active = (
                self._current_stored is not None and self.current_session_file_id() == file_id
            )

            deleted = self.storage.delete(file_id)
            if deleted and was_active:
                self._reset_deleted_session_state_locked()

            return {
                "deleted": deleted,
                "deleted_ids": [file_id] if deleted else [],
                "was_active": bool(was_active and deleted),
            }

    def delete_sessions(
        self,
        mode: Literal["all", "except_favorites"],
        expected_file_ids: list[str],
    ) -> dict[str, Any]:
        """Delete stored sessions as one locked operation, optionally preserving favorites.

        The listing, favorite-based selection, deletion, and possible live-state
        reset all run while holding ``_run_lock``.  This prevents an autosave or
        another session mutation from interleaving with the bulk operation.

        Returns authoritative deleted IDs and count plus whether the open
        session was removed. The live state is reset at most once.
        """
        if mode not in ("all", "except_favorites"):
            raise ValueError("mode must be 'all' or 'except_favorites'")

        with self._run_lock:
            sessions = self.storage.list_all()
            selected_ids = [
                str(session["file_id"])
                for session in sessions
                if mode == "all" or not bool(session.get("is_favorite", False))
            ]
            active_file_id = self.current_session_file_id()
            if set(expected_file_ids) != set(selected_ids) or len(expected_file_ids) != len(
                selected_ids
            ):
                raise ValueError("session_catalog_changed")

            try:
                deleted_ids = self.storage.delete_many_transactional(selected_ids)
            except SessionDeletionRollbackError as exc:
                was_active = active_file_id is not None and active_file_id in exc.deleted_ids
                if was_active:
                    self._reset_deleted_session_state_locked()
                exc.was_active = was_active
                raise

            was_active = active_file_id is not None and active_file_id in deleted_ids
            if was_active:
                self._reset_deleted_session_state_locked()

            return {
                "deleted_count": len(deleted_ids),
                "deleted_ids": deleted_ids,
                "was_active": was_active,
            }

    def _reset_deleted_session_state_locked(self) -> None:
        """Clear state after deleting the open session; caller holds the run lock."""
        # Reset state so the deleted session can no longer be resumed / referenced.
        self._begin_generation_locked()
        self.state.clear()
        self._current_stored = None
        self._current_agents = []
        self._material_context = None
        self._sequential_mode = False
        self._synthesis_config = None
        self._round_provider_provenance = {}
        self._generation_running = False

    def session_path_for_reveal(self, file_id: str) -> Path | None:
        """Return a path only for an existing exact and safe session id."""
        return self.storage.session_path_for_reveal(file_id)

    def snapshot_open_session(self, file_id: str) -> dict[str, Any] | None:
        """Open one session and return a detached, secret-free snapshot.

        The run lock covers hydration and serialization so concurrent workers
        cannot expose a mixed snapshot. The only session identifier is
        ``file_id``; provider keys and filesystem aliases are omitted.
        """
        with self._run_lock:
            ok = self.open_session(file_id)
            if not ok:
                return None

            stored = self._current_stored
            if stored is None:
                return None

            # Copy values under the lock so deferred workers cannot alter the snapshot.
            messages_payload: list[dict[str, Any]] = []
            for msg in self.state.messages:
                messages_payload.append(
                    {
                        "id": str(msg.id),
                        "role": str(msg.role),
                        "content": str(msg.content),
                        "round_number": int(msg.round_number),
                        "status": msg.status,
                        "agent_name": msg.agent_name,
                        "theory_label": msg.theory_label,
                        "color": msg.color,
                        "agent_index": msg.agent_index,
                        "perspective_number": msg.perspective_number,
                        "note": str(msg.note or ""),
                        "include_note_in_agent_context": bool(msg.include_note_in_agent_context),
                        "error": msg.error,
                        "error_code": msg.error_code,
                        "error_params": dict(msg.error_params),
                        # Always emit a boolean; false also excludes the message from prompts.
                        "include_in_agent_context": bool(msg.include_in_agent_context),
                        # Stable public key joining persisted messages to roster rows.
                        "client_id": msg.client_id,
                        "usage_available": msg.usage_available,
                        "prompt_tokens": msg.prompt_tokens,
                        "completion_tokens": msg.completion_tokens,
                        "total_tokens": msg.total_tokens,
                        "context_usage_available": msg.context_usage_available,
                        "input_context_tokens": msg.input_context_tokens,
                        "context_window_tokens": msg.context_window_tokens,
                        "context_tokens_exact": msg.context_tokens_exact,
                        "omitted_round_numbers": list(msg.omitted_round_numbers),
                    }
                )

            agents_payload: list[dict[str, Any]] = []
            for agent in self._current_agents:
                # Include disabled agents because this snapshot drives roster editing.
                agents_payload.append(
                    {
                        "name": str(agent.name),
                        "client_id": agent.client_id,
                        "prompt_id": agent.prompt_id,
                        "color": str(agent.color or ""),
                        # ``None`` means no provider temperature override.
                        "temperature": agent.temperature,
                        "llm_id": agent.llm_id,
                        "api_host": agent.api_host,
                        "host_configuration_id": agent.host_configuration_id,
                        "host_label": agent.host_label,
                        "max_tokens": agent.max_tokens,
                        "enabled": bool(agent.enabled),
                        "perspective_number": agent.perspective_number,
                        # Omitting API keys prevents downstream serializers from exposing them.
                    }
                )

            mc = self._material_context
            material_context_payload: dict[str, Any] | None
            if mc is None:
                material_context_payload = None
            else:
                material_context_payload = {
                    "material_type": str(mc.material_type),
                    "session_type": str(mc.session_type),
                    "target_language": str(mc.target_language),
                    "input_values": dict(mc.session_input_values),
                    "input_definitions": [
                        item.model_dump(mode="json", exclude_none=True)
                        for item in mc.session_inputs
                    ],
                    "include_unchanged_research_material_context_in_prompt": bool(
                        mc.include_unchanged_research_material_context_in_prompt
                    ),
                }

            synthesis = self._synthesis_config or SynthesisConfig(
                enabled=False,
                api_host=None,
                llm_id=None,
                temperature=None,
            )

            return {
                "file_id": str(file_id),
                "title": str(stored.title),
                "material": str(self.state.material or ""),
                "initial_question": str(self.state.initial_question or ""),
                "messages": messages_payload,
                "material_context": material_context_payload,
                "agents": agents_payload,
                "synthesis": {
                    "enabled": bool(synthesis.enabled),
                    "api_host": synthesis.api_host,
                    "llm_id": synthesis.llm_id,
                    "host_configuration_id": synthesis.host_configuration_id,
                    "host_label": synthesis.host_label,
                    "temperature": synthesis.temperature,
                },
                "sequential_mode": bool(self._sequential_mode),
                "round_number": int(self.state.round_number),
                "round_status": self.state.round_status,
                "has_active_discussion": bool(self.state.round_number > 0),
                "round_provider_provenance": [
                    {
                        "round_number": round_number,
                        "providers": [
                            {
                                "kind": provider.kind,
                                "client_id": provider.client_id,
                                "prompt_id": provider.prompt_id,
                                "prompt_label": provider.prompt_label,
                                "perspective_number": provider.perspective_number,
                                "temperature": provider.temperature,
                                "host_configuration_id": provider.host_configuration_id,
                                "host_label": provider.host_label,
                                "api_host": provider.api_host,
                                "model_id": provider.model_id,
                            }
                            for provider in providers
                        ],
                    }
                    for round_number, providers in sorted(self._round_provider_provenance.items())
                ],
            }

    def get_message(self, message_id: str) -> DiscussionMessage | None:
        """Return one message from the live discussion state."""
        return self.state.get_message(message_id)

    def set_message_note(
        self,
        message_id: str,
        note: str,
        include_note_in_agent_context: bool = False,
    ) -> bool:
        """Update a note and persist it atomically with the live snapshot."""
        with self._run_lock:
            message = self.state.get_message(message_id)
            if message is None:
                return False

            message.note = note.strip()
            # A note has no independent referent: only agent-authored notes
            # with non-empty content can enter future agent context.
            message.include_note_in_agent_context = bool(
                message.role == "agent"
                and message.include_in_agent_context
                and message.note
                and include_note_in_agent_context
            )
            self._save_current_state_locked()
            return True

    def clear_message_note(self, message_id: str) -> bool:
        """Clear one message note."""
        return self.set_message_note(message_id, "", False)

    def update_next_round_configuration(
        self,
        file_id: str,
        agents: list[AgentConfig],
        synthesis: SynthesisConfig,
    ) -> str:
        """Atomically persist a validated full configuration for the next round."""
        with self._run_lock:
            if self._generation_running:
                return "generation_active"
            if self._current_stored is None:
                return "no_active_session"
            if self.storage.file_id_for(self._current_stored) != file_id:
                return "session_mismatch"

            self._validate_agent_configurations(agents)
            current_shape = {
                agent.client_id: agent.perspective_number for agent in self._current_agents
            }
            requested_shape = {agent.client_id: agent.perspective_number for agent in agents}
            if requested_shape != current_shape or len(agents) != len(self._current_agents):
                return "roster_changed"

            snapshot = deepcopy(self._current_stored.prompt_snapshot)
            normalized_agents: list[AgentConfig] = []
            for submitted in agents:
                prompt_id = (submitted.prompt_id or "").strip()
                role = self._snapshot_role(snapshot, prompt_id) if prompt_id else None
                if prompt_id and role is None:
                    current_role = self.prompt_repo.get_template(prompt_id)
                    if current_role is not None:
                        role = {
                            "id": str(current_role.id),
                            "label": str(current_role.label),
                            "role": str(current_role.role or ""),
                            "task": str(current_role.task or ""),
                            "output_format": str(current_role.output_format or ""),
                        }
                        snapshot.roles.append(role)
                if role is None and submitted.enabled:
                    return "role_changed"

                normalized = deepcopy(submitted)
                normalized.prompt_id = str(role["id"]) if role is not None else None
                if role is not None:
                    normalized.name = str(role["label"])
                normalized.api_key = None
                has_provider = any(
                    (normalized.host_configuration_id, normalized.api_host, normalized.llm_id)
                )
                if normalized.enabled or has_provider:
                    resolved = self._configured_provider(
                        normalized.host_configuration_id,
                        normalized.api_host,
                        normalized.llm_id,
                    )
                    if resolved is None:
                        return "provider_changed"
                    configuration_id, label, api_host, model_id = resolved
                    normalized.host_configuration_id = configuration_id
                    normalized.host_label = label
                    normalized.api_host = api_host
                    normalized.llm_id = model_id
                else:
                    normalized.host_label = None
                normalized_agents.append(normalized)

            normalized_synthesis = deepcopy(synthesis)
            synthesis_has_provider = any(
                (
                    normalized_synthesis.host_configuration_id,
                    normalized_synthesis.api_host,
                    normalized_synthesis.llm_id,
                )
            )
            if normalized_synthesis.enabled or synthesis_has_provider:
                resolved = self._configured_provider(
                    normalized_synthesis.host_configuration_id,
                    normalized_synthesis.api_host,
                    normalized_synthesis.llm_id,
                )
                if resolved is None:
                    return "provider_changed"
                configuration_id, label, api_host, model_id = resolved
                normalized_synthesis.host_configuration_id = configuration_id
                normalized_synthesis.host_label = label
                normalized_synthesis.api_host = api_host
                normalized_synthesis.llm_id = model_id
            else:
                normalized_synthesis.host_label = None

            previous_agents = deepcopy(self._current_agents)
            previous_synthesis = deepcopy(self._synthesis_config)
            previous_stored = deepcopy(self._current_stored)
            self._current_agents = normalized_agents
            self._synthesis_config = normalized_synthesis
            self._current_stored.prompt_snapshot = snapshot
            try:
                self._save_current_state_locked()
            except BaseException:
                self._current_agents = previous_agents
                self._synthesis_config = previous_synthesis
                self._current_stored = previous_stored
                raise
            return "updated"

    def update_current_agents(self, agents: list[AgentConfig]) -> bool:
        """Replace the editable roster and autosave it under the run lock."""
        with self._run_lock:
            if self._current_stored is None:
                return False

            self._validate_agent_configurations(agents)
            self._current_agents = list(agents)
            self._save_current_state_locked()
            return True

    def set_message_context_inclusion(
        self, message_id: str, include: bool
    ) -> Literal["updated", "not_found", "locked"]:
        """Set a message's next-round context flag and autosave atomically.

        This does not change roster execution; it only controls the next prompt
        assembled by :meth:`DiscussionState.get_context_for_agents`.
        """
        with self._run_lock:
            message = self.state.get_message(message_id)
            if message is None:
                return "not_found"

            if message.role == "synthesis":
                return "locked"

            if message.round_number != self.state.round_number:
                return "locked"

            message.include_in_agent_context = bool(include)
            if not message.include_in_agent_context:
                message.include_note_in_agent_context = False
            self._save_current_state_locked()
            return "updated"

    def get_current_filepath(self) -> Path | None:
        """Return the current persisted path, if a discussion is open."""
        if self._current_stored is None:
            return None
        return self.storage.storage_dir / f"{self.storage.file_id_for(self._current_stored)}.json"

    def get_markdown(self, locale: str = "de") -> str | None:
        """Return the synchronized discussion as Markdown."""

        return export_markdown(
            self._current_stored,
            synchronize_rounds=self._sync_messages_to_rounds,
            prompt_documentation=self._export_prompt_documentation,
            locale=locale,
        )

    def _export_prompt_documentation(self) -> list[tuple[str, str, str]]:
        """Reconstruct current messages without implying past provider payloads."""

        if self._current_stored is None or self._prompt_snapshot() is None:
            return []
        from src.prompts.preview import build_preview_user_prompt

        material_context = self._material_context
        if material_context is None:
            return []
        active_agents = [
            (index, agent) for index, agent in enumerate(self._current_agents) if agent.is_active
        ]
        user_prompt = build_preview_user_prompt(
            material_context, discussion_state=self.state
        )
        messages: list[tuple[str, str, str]] = []
        for position, (index, agent) in enumerate(active_agents):
            system_prompt = self.build_system_prompt(
                prompt_id=agent.prompt_id or "",
                agent_config=agent,
                agent_index=position,
                total_agents=len(active_agents),
                other_agents=self._other_agents(active_agents, index),
                material_context=material_context,
                mark_prompt_usage=False,
            )
            if system_prompt:
                messages.append(
                    (f"Perspective {agent.perspective_number or position + 1}", system_prompt, user_prompt)
                )
        if (
            self._current_stored.prompt_snapshot.synthesis_used
            and self._current_stored.prompt_snapshot.target_language
        ):
            responses = [
                AgentResponse(
                    message_id=message.id,
                    agent_index=message.agent_index,
                    agent_name=message.agent_name,
                    theory_label=message.theory_label,
                    color=message.color,
                    perspective_number=message.perspective_number,
                    text=message.content,
                    error=message.error,
                )
                for message in self.state.messages
                if message.role == "agent" and message.round_number == self.state.round_number
            ]
            question = next(
                (
                    message.content
                    for message in self.state.messages
                    if message.role == "user" and message.round_number == self.state.round_number
                ),
                "",
            )
            messages.append(
                (
                    "Round Synthesis",
                    self.build_synthesis_system_prompt(mark_prompt_usage=False),
                    (
                        self.build_synthesis_user_prompt(
                            question=question, active_agents=active_agents, responses=responses
                        )
                        if responses and question
                        else ""
                    ),
                )
            )
        return messages
