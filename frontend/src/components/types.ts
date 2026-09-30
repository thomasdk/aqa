import type {
  AgentConfigContract,
  BulkDeleteSessionsContract,
  DeleteSessionContract,
  DiscussionMessageContract,
  DiscussionStateContract,
  DiscussionSessionTypeContract,
  GlobalBlockContract,
  HostInfoContract,
  LocalAIDiagnosticsContract,
  LocalAIDeleteModelContract,
  LocalAIInventoryContract,
  LocalAIRuntimeSelectionContract,
  LocalAIStatusContract,
  OpenSessionAgentContract,
  OpenSessionContract,
  OpenSessionMaterialContextContract,
  OpenSessionMessageContract,
  SessionInputDefinitionContract,
  SessionSummaryContract,
  PerspectiveContract,
  PromptSessionTypeContract,
  RoleContract,
  StartMaterialContextContract,
  SynthesisConfigContract,
} from "../api/contracts";

/** Normalized editable roster state built from the generated request DTO. */
export type AgentConfig = Omit<
  AgentConfigContract,
  | "api_host"
  | "api_key"
  | "host_configuration_id"
  | "host_label"
  | "llm_id"
  | "max_tokens"
  | "prompt_id"
  | "temperature"
> & {
  api_host: string | null;
  api_key: string | null;
  host_configuration_id?: string | null;
  host_label?: string | null;
  llm_id: string | null;
  max_tokens: number | null;
  prompt_id: string | null;
  temperature: number | null;
};

export type SynthesisConfig = SynthesisConfigContract;

/** Current session types define their own input keys, beyond bundled defaults. */
export type MaterialContext = Omit<StartMaterialContextContract, "input_values"> & {
  input_values: Record<string, string>;
};

/** One ordered user-editable input rendered by Setup for a session type. */
export type SessionInputDefinition = SessionInputDefinitionContract;

export type Perspective = PerspectiveContract;
export type SessionType = DiscussionSessionTypeContract;
export type DiscussionMessage = Omit<DiscussionMessageContract, "status"> & {
  status?: DiscussionMessageContract["status"];
};
export type DiscussionState = DiscussionStateContract;

/**
 * Safe, summary-level metadata for one saved session. Returned by
 * `GET /api/sessions`. Contains no path or content fields; the UI must
 * fetch a full snapshot via `POST /api/sessions/{file_id}/open` before
 * resuming a discussion.
 */
export type SessionSummary = SessionSummaryContract;

export type SessionMessage = Omit<OpenSessionMessageContract, "status"> & {
  status?: OpenSessionMessageContract["status"];
};
export type SessionMaterialContext = Omit<OpenSessionMaterialContextContract, "input_values"> & {
  input_values: Record<string, string>;
};
export type SessionAgent = OpenSessionAgentContract;
export type SessionSnapshot = Omit<OpenSessionContract, "material_context" | "messages"> & {
  material_context: SessionMaterialContext;
  messages: SessionMessage[];
};
export type RoundProviderProvenance = SessionSnapshot["round_provider_provenance"][number];
export type DeleteSessionResult = DeleteSessionContract;
export type BulkDeleteSessionsResult = BulkDeleteSessionsContract;

export type HostInfo = HostInfoContract;

/** Preflight context measurement for the request currently being generated. */
export type { ContextUsage, DiscussionStreamEvent as SSEEvent } from "../api/discussion-events";

export type RoleOrigin = "shipped_default" | "shipped_modified" | "custom";

export type PromptConfigOrigin = "shipped_default" | "shipped_modified" | "custom";

export type Role = RoleContract;

export type SessionTypeDetail = PromptSessionTypeContract;
export type GlobalBlock = GlobalBlockContract;

export type LocalAIModelId = LocalAIDeleteModelContract["model_id"];

export type LocalAIState = LocalAIStatusContract["state"];
export type LocalAIIntegrity = LocalAIInventoryContract["integrity"];
export type LocalAIDiagnostics = LocalAIDiagnosticsContract;
export type LocalAIModelInventory = LocalAIInventoryContract;
export type LocalAIRuntimeSelection = LocalAIRuntimeSelectionContract;

export type LocalAIModelCatalogEntry = {
  id: LocalAIModelId;
  label: string;
  description: string;
  memory: string;
  model_size: string;
  draft_size: string;
  model_url: string;
  model_bytes: number;
  draft_bytes: number;
};

/**
 * Sanitized state returned by the Local AI routes.  It deliberately contains
 * no paths, commands, raw logs, or other operational details.  The explicit
 * Local AI diagnostics endpoint owns the operational display; the runtime
 * explanation here lives in ``runtime_selection`` (see ``LocalAIRuntimeSelection``).
 */
export type LocalAIStatus = LocalAIStatusContract;
