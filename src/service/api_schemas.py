"""Stable request and response DTOs for the AQA HTTP API.

Keeping transport schemas separate from route handlers makes the OpenAPI
contract reviewable without importing process-management implementation.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from src.prompts.session_types import (
    SessionInputDefinition,
    validate_session_inputs,
)


class AgentConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    client_id: str = Field(..., min_length=1)
    prompt_id: str | None = None
    color: str = "#333333"
    temperature: float | None = Field(
        default=None,
        strict=True,
        ge=0.0,
        le=2.0,
    )
    llm_id: str | None = None
    api_host: str | None = None
    host_configuration_id: str | None = None
    host_label: str | None = None
    api_key: str | None = None
    max_tokens: StrictInt | None = Field(default=None, gt=0)
    enabled: bool = True
    perspective_number: StrictInt = Field(..., gt=0)


class SynthesisConfigModel(BaseModel):
    """Safe settings for the dedicated non-participant synthesis phase."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    # Nullable provider values are still part of the strict replacement
    # contract.  Omitting one would otherwise silently reset it during a
    # between-round update.
    api_host: str | None
    llm_id: str | None
    host_configuration_id: str | None = None
    host_label: str | None = None
    temperature: float | None = Field(..., strict=True, ge=0.0, le=2.0)


class SessionInputValuesModel(BaseModel):
    """The immutable semantic values submitted for every session type."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    research_material_context: str
    main_input: str
    additional_instructions: str


class MaterialContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    material_type: str = Field(..., min_length=1)
    session_type: str = Field(..., min_length=1)
    # This is intentionally independent from the UI locale.  A new
    # discussion must always name the language in which the models respond.
    target_language: str = Field(..., min_length=1)
    input_values: SessionInputValuesModel


class ApplicationActivityEvent(BaseModel):
    """A public, privacy-safe application diagnostic event."""

    sequence: int = Field(ge=1)
    timestamp: str
    level: Literal["info", "warning", "error"]
    code: str
    params: dict[str, str | int]


class ApplicationActivityResponse(BaseModel):
    """A cursor page from the process-local application activity feed."""

    events: list[ApplicationActivityEvent]
    next_cursor: int = Field(ge=0)
    truncated: bool


class UIPreferencesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ui_locale: Literal["de", "en"]
    appearance: Literal["system", "light", "dark"]
    ai_source: Literal["integrated", "external"]
    local_ai_context_tokens: int = Field(ge=8_192, le=262_144)
    local_ai_context_default_tokens: int = Field(ge=8_192, le=262_144)
    local_ai_mtp_enabled: bool
    notifications_enabled: bool
    notification_permission_auto_attempted: bool
    prevent_sleep_while_generating: bool
    last_active_discussion_id: str | None = Field(
        pattern=r"^[^\\/\s]+$",
    )


class UIPreferencesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ui_locale: Literal["de", "en"] | None = None
    appearance: Literal["system", "light", "dark"] | None = None
    ai_source: Literal["integrated", "external"] | None = None
    local_ai_context_tokens: int | None = Field(default=None, ge=8_192, le=262_144)
    local_ai_context_model_id: Literal["gemma-4-e2b", "gemma-4-e4b", "gemma-4-12b"] | None = None
    local_ai_mtp_enabled: bool | None = None
    notifications_enabled: bool | None = Field(default=None, strict=True)
    notification_permission_auto_attempted: Literal[True] | None = None
    prevent_sleep_while_generating: bool | None = Field(default=None, strict=True)
    last_active_discussion_id: str | None = Field(
        default=None,
        pattern=r"^[^\\/\s]+$",
    )


class StartDiscussionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material: str = ""
    agents: list[AgentConfigModel]
    title: str = ""
    material_context: MaterialContextModel = Field(...)
    synthesis: SynthesisConfigModel
    sequential_mode: bool = False


class ContextEstimateRequest(BaseModel):
    """First-round context estimate for the current Setup draft without generation."""

    model_config = ConfigDict(extra="forbid")

    material: str = ""
    agents: list[AgentConfigModel]
    material_context: MaterialContextModel = Field(...)
    synthesis: SynthesisConfigModel
    sequential_mode: bool = False


class ContextEstimateResponse(BaseModel):
    """Safe context-budget facts without prompt or material content."""

    model_config = ConfigDict(extra="forbid")

    known: bool
    estimated_input_tokens: int | None = Field(default=None, ge=0)
    available_input_tokens: int | None = Field(default=None, ge=0)
    context_window_tokens: int | None = Field(default=None, ge=0)
    reserved_output_tokens: int = Field(ge=0)
    overflow: bool = False


class ProviderRebindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configuration_id: str = Field(..., min_length=1)
    model_id: str = Field(..., min_length=1)


class ContinueDiscussionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_input: str
    agents: list[AgentConfigModel]
    focus_segment: str | None = None
    sequential_mode: bool = False
    provider_rebind: ProviderRebindRequest | None = None


class NoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = ""
    include_note_in_agent_context: bool = False


class UpdateDiscussionAgentsRequest(BaseModel):
    """Strict roster update contract."""

    model_config = ConfigDict(extra="forbid")
    agents: list[AgentConfigModel]


class UpdateSynthesisRequest(BaseModel):
    """Strict replacement contract for between-round synthesis settings."""

    model_config = ConfigDict(extra="forbid")

    file_id: str
    synthesis: SynthesisConfigModel


class NextRoundAgentConfigModel(BaseModel):
    """Complete secret-free configuration for one stable session participant."""

    model_config = ConfigDict(extra="forbid")

    name: str
    client_id: str = Field(..., min_length=1)
    prompt_id: str | None = None
    color: str = "#333333"
    temperature: float | None = Field(default=None, strict=True, ge=0.0, le=2.0)
    llm_id: str | None = None
    api_host: str | None = None
    host_configuration_id: str | None = None
    max_tokens: StrictInt | None = Field(default=None, gt=0)
    enabled: bool = True
    perspective_number: StrictInt = Field(..., gt=0)


class NextRoundSynthesisConfigModel(BaseModel):
    """Complete secret-free synthesis configuration for the next round."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    api_host: str | None
    llm_id: str | None
    host_configuration_id: str | None = None
    temperature: float | None = Field(..., strict=True, ge=0.0, le=2.0)


class UpdateNextRoundConfigurationRequest(BaseModel):
    """Atomic full replacement of every editable between-round setting."""

    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(..., min_length=1)
    agents: list[NextRoundAgentConfigModel]
    synthesis: NextRoundSynthesisConfigModel


class UpdateNextRoundConfigurationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_count: int = Field(ge=0)


class MessageContextInclusionRequest(BaseModel):
    """Strict per-message context inclusion contract."""

    model_config = ConfigDict(extra="forbid")
    include_in_agent_context: bool


class UpdateDiscussionAgentsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_count: int


class MessageContextInclusionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool = True


class TemplateInfo(BaseModel):
    id: str
    label: str


class PromptSource(BaseModel):
    """One ordered source block used to assemble a prompt preview."""

    key: Literal["context", "globals", "role", "task", "output_format"]
    content: str


class PreviewResult(BaseModel):
    template_id: str
    label: str
    mode: str
    # Combined content length of the distinct system and user messages.  This
    # deliberately excludes artificial separators used only for estimation.
    char_count: int
    estimated_tokens: int | None
    tokenizer_name: str
    prompt_sources: list[PromptSource]
    system_prompt: str
    user_prompt: str
    scenario: str
    session_type: str
    session_label: str


class MaterialLineNumberRequest(BaseModel):
    material: str


class DefaultMaterialResponse(BaseModel):
    """The shipped starter material exposed to a fresh setup draft."""

    model_config = ConfigDict(extra="forbid")

    material: str
    material_type: str


class MaterialLineNumberResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material: str


class MaterialTokenEstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material: str = ""
    material_type: str = "document"


class MaterialTokenEstimateResponse(BaseModel):
    approximate_tokens: int = Field(ge=0)
    tokenizer: str


class RestoreDefaultsResponse(BaseModel):
    """Identifiers restored from the immutable shipped prompt baseline."""

    model_config = ConfigDict(extra="forbid")

    restored: list[str]


class DeletePromptConfigurationResponse(BaseModel):
    """Identifier of one deleted custom prompt configuration item."""

    model_config = ConfigDict(extra="forbid")

    deleted: str


class PromptConfigurationAcknowledgementResponse(BaseModel):
    """Confirmation payload for a completed prompt configuration action."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"


class PerspectiveResponse(BaseModel):
    """One selectable discussion perspective."""

    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    description: str | None = None


class DiscussionSessionTypeResponse(BaseModel):
    """Setup metadata for one current session type."""

    model_config = ConfigDict(extra="forbid")
    key: str
    label: str
    description: str | None = None
    inputs: list[SessionInputDefinition]


class DiscussionMessageResponse(BaseModel):
    """Current in-memory discussion message returned by the state route."""

    model_config = ConfigDict(extra="forbid")
    id: str
    role: Literal["user", "agent", "synthesis", "system"]
    content: str
    round_number: int
    status: Literal["in_progress", "completed", "interrupted", "failed"] = "completed"
    agent_name: str | None = None
    theory_label: str | None = None
    color: str | None = None
    agent_index: int | None = None
    perspective_number: int | None = None
    client_id: str | None = None
    note: str = ""
    include_note_in_agent_context: bool | None = None
    include_in_agent_context: bool = True
    error: str | None = None
    error_code: str | None = None
    error_params: dict[str, Any] = Field(default_factory=dict)
    usage_available: bool | None = None
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    context_usage_available: bool | None = None
    input_context_tokens: int | None = Field(default=None, ge=0)
    context_window_tokens: int | None = Field(default=None, ge=0)
    context_tokens_exact: bool | None = None
    omitted_round_numbers: list[int] = Field(default_factory=list)


class DiscussionStateResponse(BaseModel):
    """The active in-memory discussion state."""

    model_config = ConfigDict(extra="forbid")
    material: str
    initial_question: str
    messages: list[DiscussionMessageResponse]
    has_errors: bool
    round_number: int
    round_status: Literal["in_progress", "completed", "interrupted", "failed"] | None = None
    has_active_discussion: bool


class CancelDiscussionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["cancelling", "idle"]


class DiscussionStreamEventResponse(BaseModel):
    """One JSON payload emitted on the discussion SSE stream."""

    model_config = ConfigDict(extra="forbid")
    type: Literal[
        "discussion_started",
        "user_message",
        "context_usage",
        "agent_start",
        "chunk",
        "agent_complete",
        "synthesis_start",
        "synthesis_chunk",
        "synthesis_complete",
        "synthesis_error",
        "all_complete",
        "error",
    ]
    file_id: str | None = None
    title: str | None = None
    message_id: str | None = None
    content: str | None = None
    text: str | None = None
    message: str | None = None
    round_number: int | None = None
    agent_index: int | None = None
    perspective_number: int | None = None
    agent_name: str | None = None
    theory_label: str | None = None
    color: str | None = None
    client_id: str | None = None
    available: bool | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    context_tokens: int | None = Field(default=None, ge=0)
    exact: bool | None = None
    omitted_round_numbers: list[int] | None = None
    is_complete: bool | None = None
    status: Literal["in_progress", "completed", "interrupted", "failed"] | None = None
    error: str | None = None
    error_code: str | None = None
    error_params: dict[str, Any] | None = None
    usage_available: bool | None = None
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    context_usage_available: bool | None = None
    context_window_tokens: int | None = Field(default=None, ge=0)
    context_tokens_exact: bool | None = None


class HostInfoResponse(BaseModel):
    """Path- and secret-free configured host metadata."""

    model_config = ConfigDict(extra="forbid")
    configuration_id: str
    label: str
    url: str
    model: str
    models: list[str]
    kind: str | None = None
    has_api_key: bool
    is_favorite: bool | None = None
    model_context_tokens: dict[str, int] = Field(default_factory=dict)
    context_tokens: int | None = None


class HostModelsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models: list[str]


class HostDeletePreviewRequest(BaseModel):
    """Stable host identity submitted before destructive confirmation."""

    model_config = ConfigDict(extra="forbid")
    label: str = Field(..., min_length=1)


class HostDeleteRequest(BaseModel):
    """Frozen preflight identity required to delete one configured host."""

    model_config = ConfigDict(extra="forbid")
    label: str = Field(..., min_length=1)
    revision: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class SavedSessionHostDependency(BaseModel):
    """Path-free saved-session identity retained after host deletion."""

    model_config = ConfigDict(extra="forbid")
    file_id: str
    title: str


class HostDeletePreviewResponse(BaseModel):
    """Secret-free consequences frozen for one host deletion confirmation."""

    model_config = ConfigDict(extra="forbid")
    label: str
    revision: str
    is_preferred: bool
    credential_will_be_removed: bool
    saved_sessions: list[SavedSessionHostDependency]


class HostDeleteResponse(BaseModel):
    """Bounded authoritative result of one host deletion."""

    model_config = ConfigDict(extra="forbid")
    deleted: bool
    label: str
    credential_removed: bool


class ProviderProvenanceResponse(BaseModel):
    """Safe role and provider selection frozen for one historical round."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["perspective", "synthesis"]
    client_id: str | None
    prompt_id: str
    prompt_label: str
    perspective_number: int | None
    temperature: float | None
    host_configuration_id: str | None
    host_label: str | None
    api_host: str
    model_id: str


class RoundProviderProvenanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    round_number: int = Field(ge=1)
    providers: list[ProviderProvenanceResponse]


class RoleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    role: str
    task: str
    output_format: str
    description: str | None = None
    editable: bool
    is_shipped: bool
    origin: Literal["shipped_default", "shipped_modified", "custom"]


class PromptSessionTypeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str
    description: str
    default_agent_prompt_ids: list[str]
    include_unchanged_research_material_context_in_prompt: bool
    body: str
    is_shipped: bool
    origin: Literal["shipped_default", "shipped_modified", "custom"]
    inputs: list[SessionInputDefinition]


class GlobalBlockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    scope: str | None
    content: str
    is_shipped: bool
    origin: Literal["shipped_default", "shipped_modified", "custom"]


class LocalAIImportFilesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    main: str
    draft: str


class LocalAIModelInventoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: Literal["gemma-4-e2b", "gemma-4-e4b", "gemma-4-12b"]
    api_alias: str | None = None
    installed: bool
    integrity: Literal["unknown", "verified", "failed"]
    model_bytes: int | None = Field(default=None, ge=0)
    draft_bytes: int | None = Field(default=None, ge=0)
    import_files: LocalAIImportFilesResponse | None = None


class LocalAIRuntimeSelectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_profile: str | None = None
    accelerator_label: str | None = None
    engine_name: Literal["llama-server", "llama-server.exe"] | None = None
    decision_basis: Literal["detected compatible runtime", "safe CPU fallback"] | None = None
    runtime_installed: bool | None = None
    acceleration_confirmed: bool


class LocalAIRuntimeSelectionAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    profile: str = Field(min_length=1, max_length=80)
    stage: Literal["device_probe", "runtime_preflight", "model_readiness", "runtime_update"]
    result: Literal["accepted", "rejected", "selected"]
    reason: (
        Literal[
            "missing_runtime_library",
            "driver_unavailable",
            "no_gpu",
            "probe_timeout",
            "probe_failed",
            "malformed_output",
            "model_offload_failed",
            "runtime_launch_failed",
            "runtime_options_unavailable",
            "runtime_incompatible",
            "accelerator_failed",
            "insufficient_resources",
            "port_conflict",
        ]
        | None
    ) = None


class LocalAIRuntimeSelectionRecord(BaseModel):
    """Exact allowlist of fields written by the bounded runtime-selection recorder."""

    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    operation: Literal["model_install", "runtime_update"]
    outcome: Literal["incomplete", "selected"]
    attempts: list[LocalAIRuntimeSelectionAttempt] = Field(max_length=12)
    selected_profile: str | None = Field(default=None, min_length=1, max_length=80)


class LocalAIRuntimeSelectionDiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["available", "missing", "invalid"]
    record: LocalAIRuntimeSelectionRecord | None = None


class LocalAIStatusResponse(BaseModel):
    """Sanitized Integrated AI status with its complete model inventory."""

    model_config = ConfigDict(extra="forbid")
    state: Literal[
        "not_installed",
        "downloading",
        "importing",
        "installed",
        "starting",
        "running",
        "sleeping",
        "error",
        "stopped",
        "cancelling",
        "cancelled",
    ]
    model_id: Literal["gemma-4-e2b", "gemma-4-e4b", "gemma-4-12b"] | None = None
    model_name: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    preferred_model_id: Literal["gemma-4-e2b", "gemma-4-e4b", "gemma-4-12b"] | None = None
    download_bytes: int = Field(ge=0)
    download_total: int = Field(ge=0)
    available_disk_bytes: int | None = Field(default=None, ge=0)
    download_phase: (
        Literal["preparing", "runtime", "main_model", "mtp_drafter", "finalizing"] | None
    ) = None
    import_bytes: int | None = Field(default=None, ge=0)
    import_total: int | None = Field(default=None, ge=0)
    import_phase: Literal["copying", "verifying"] | None = None
    context_tokens: int | None = Field(default=None, ge=0)
    mtp_enabled: bool | None = None
    mtp_draft_tokens: int | None = Field(default=None, ge=1, le=6)
    job_id: str | None = None
    operation_kind: Literal["model_download", "model_import", "runtime_update"] | None = None
    operation_state: Literal["downloading", "importing", "cancelling", "error"] | None = None
    operation_model_id: Literal["gemma-4-e2b", "gemma-4-e4b", "gemma-4-12b"] | None = None
    error_code: str | None = Field(default=None, pattern=r"^[a-z_]{3,64}$")
    host_ready: bool
    message: str | None = None
    integrity: Literal["unknown", "verified", "failed"]
    accelerator_label: str | None = None
    os_label: str | None = None
    cpu_label: str | None = None
    logical_cpu_count: int | None = Field(default=None, ge=1)
    gpu_label: str | None = None
    ram_gb: int | None = Field(default=None, ge=1)
    inference_memory_gb: int | None = Field(default=None, ge=1)
    inference_memory_kind: Literal["ram", "vram", "unified"] | None = None
    model_bytes: int | None = Field(default=None, ge=0)
    draft_bytes: int | None = Field(default=None, ge=0)
    models: list[LocalAIModelInventoryResponse]
    runtime_installed: bool | None = None
    runtime_selection: LocalAIRuntimeSelectionResponse


class LocalAIDiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_reference: str | None = Field(default=None, max_length=2000)
    command_kind: Literal["active", "next_start", "last_attempt"] | None = None
    error_code: str | None = Field(default=None, pattern=r"^[a-z_]{3,64}$")
    exit_code: int | None = None
    log_tail: list[str] = Field(default_factory=list, max_length=12)
    runtime_selection_diagnostics: LocalAIRuntimeSelectionDiagnosticsResponse


class JobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str


class DetectedModelImportJobResponse(JobResponse):
    model_id: Literal["gemma-4-e2b", "gemma-4-e4b", "gemma-4-12b"]


class ImportStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    import_id: str


class SessionSummaryModel(BaseModel):
    """Public, path-free metadata for a stored discussion."""

    model_config = ConfigDict(extra="forbid")
    file_id: str
    title: str
    created: str
    updated: str
    session_type: str
    round_count: int
    is_open: bool
    is_favorite: bool


class _MessageSnapshotBase(BaseModel):
    """Fields shared by all entries in an open-session snapshot."""

    model_config = ConfigDict(extra="forbid")
    id: str
    role: str
    content: str
    round_number: int
    status: Literal["in_progress", "completed", "interrupted", "failed"] = "completed"
    note: str = ""
    include_note_in_agent_context: bool = False
    error: str | None = None
    error_code: str | None = None
    error_params: dict[str, Any] = Field(default_factory=dict)
    include_in_agent_context: bool = True
    usage_available: bool | None = None
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    context_usage_available: bool | None = None
    input_context_tokens: int | None = Field(default=None, ge=0)
    context_window_tokens: int | None = Field(default=None, ge=0)
    context_tokens_exact: bool | None = None
    omitted_round_numbers: list[int] = Field(default_factory=list)


class AgentMessageSnapshotModel(_MessageSnapshotBase):
    """An agent result with its required stable roster identity."""

    role: Literal["agent"]
    agent_name: str = Field(..., min_length=1)
    theory_label: str | None = None
    color: str = Field(..., min_length=1)
    agent_index: StrictInt = Field(..., ge=0)
    perspective_number: StrictInt = Field(..., ge=1)
    client_id: str = Field(..., min_length=1)


class NonAgentMessageSnapshotModel(_MessageSnapshotBase):
    """A user, synthesis, or system event with no roster identity."""

    role: Literal["user", "synthesis", "system"]
    agent_name: None = None
    theory_label: None = None
    color: None = None
    agent_index: None = None
    perspective_number: None = None
    client_id: None = None


MessageSnapshotModel = Annotated[
    AgentMessageSnapshotModel | NonAgentMessageSnapshotModel,
    Field(discriminator="role"),
]


class AgentSnapshotModel(BaseModel):
    """Non-secret portion of a persisted agent configuration."""

    model_config = ConfigDict(extra="forbid")
    name: str
    client_id: str = Field(..., min_length=1)
    prompt_id: str | None = None
    color: str = "#333333"
    temperature: float | None = None
    llm_id: str | None = None
    api_host: str | None = None
    host_configuration_id: str | None = None
    host_label: str | None = None
    max_tokens: int | None = None
    enabled: bool = True
    perspective_number: int = Field(..., gt=0)


class MaterialContextSnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    material_type: str
    session_type: str
    target_language: str = Field(..., min_length=1)
    input_values: SessionInputValuesModel
    input_definitions: list[SessionInputDefinition]
    include_unchanged_research_material_context_in_prompt: bool

    @field_validator("input_definitions")
    @classmethod
    def _validate_input_definitions(
        cls, value: list[SessionInputDefinition]
    ) -> list[SessionInputDefinition]:
        return validate_session_inputs(value)


class OpenSessionResponse(BaseModel):
    """Complete path- and secret-free snapshot of an opened session."""

    model_config = ConfigDict(extra="forbid")
    file_id: str
    title: str
    material: str
    initial_question: str
    messages: list[MessageSnapshotModel]
    material_context: MaterialContextSnapshotModel
    agents: list[AgentSnapshotModel]
    synthesis: SynthesisConfigModel
    sequential_mode: bool
    round_number: int
    round_status: Literal["in_progress", "completed", "interrupted", "failed"] | None = None
    has_active_discussion: bool
    round_provider_provenance: list[RoundProviderProvenanceResponse]


class RenameSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(..., min_length=1, max_length=500)


class SetSessionFavoriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_favorite: bool


class DeleteSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted: bool
    was_open: bool
    deleted_ids: list[str]
    deleted_count: int = Field(ge=0)


class BulkDeleteSessionsRequest(BaseModel):
    """Selection mode for one locked stored-session bulk deletion."""

    model_config = ConfigDict(extra="forbid")
    mode: Literal["all", "except_favorites"]
    expected_file_ids: list[str]


class BulkDeleteSessionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted_count: int = Field(ge=0)
    was_open: bool
    deleted_ids: list[str]


class RevealSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"


class RevealRoleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"


class RevealRolesDirectoryResponse(BaseModel):
    """Success payload for opening the active roles directory."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"


class RevealSessionTypesDirectoryResponse(BaseModel):
    """Success payload for opening the active session-types directory."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"


class RevealGlobalsDirectoryResponse(BaseModel):
    """Success payload for opening the active global-prompts directory."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"


class RevealLocalAIModelsDirectoryResponse(BaseModel):
    """Success payload for opening the local AI models directory."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"


__all__ = [
    "AgentConfigModel",
    "AgentSnapshotModel",
    "BulkDeleteSessionsRequest",
    "BulkDeleteSessionsResponse",
    "DefaultMaterialResponse",
    "DeletePromptConfigurationResponse",
    "ContinueDiscussionRequest",
    "DeleteSessionResponse",
    "HostDeletePreviewRequest",
    "HostDeletePreviewResponse",
    "HostDeleteRequest",
    "HostDeleteResponse",
    "MaterialContextModel",
    "MaterialLineNumberRequest",
    "MaterialLineNumberResponse",
    "MaterialTokenEstimateRequest",
    "MaterialTokenEstimateResponse",
    "MessageContextInclusionRequest",
    "MessageContextInclusionResponse",
    "AgentMessageSnapshotModel",
    "MessageSnapshotModel",
    "NonAgentMessageSnapshotModel",
    "NoteRequest",
    "OpenSessionResponse",
    "PromptSource",
    "PromptConfigurationAcknowledgementResponse",
    "PreviewResult",
    "ProviderProvenanceResponse",
    "RenameSessionRequest",
    "RestoreDefaultsResponse",
    "RevealGlobalsDirectoryResponse",
    "RevealLocalAIModelsDirectoryResponse",
    "RevealRoleResponse",
    "RevealRolesDirectoryResponse",
    "RevealSessionTypesDirectoryResponse",
    "RevealSessionResponse",
    "RoundProviderProvenanceResponse",
    "SavedSessionHostDependency",
    "SessionSummaryModel",
    "SessionInputValuesModel",
    "SetSessionFavoriteRequest",
    "StartDiscussionRequest",
    "TemplateInfo",
    "UpdateDiscussionAgentsRequest",
    "UpdateDiscussionAgentsResponse",
]
