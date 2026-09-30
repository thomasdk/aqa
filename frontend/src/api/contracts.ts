import type { components, paths } from "./generated";

/** Public health payload as described by FastAPI's OpenAPI document. */
export type HealthResponse =
  paths["/api/health"]["get"]["responses"][200]["content"]["application/json"];

/** Path-free summary returned by the stored-session API. */
export type SessionSummaryContract = components["schemas"]["SessionSummaryModel"];

/** A source fragment, ordered as the request is assembled for inspection. */
export type PromptSource = components["schemas"]["PromptSource"];

/** Prompt preview DTO generated from the backend response model. */
export type PromptPreviewContract = components["schemas"]["PreviewResult"];

/** Complete, current-format snapshot returned when a stored session is opened. */
export type OpenSessionContract = components["schemas"]["OpenSessionResponse"];
export type OpenSessionMessageContract = OpenSessionContract["messages"][number];
export type OpenSessionMaterialContextContract = OpenSessionContract["material_context"];
export type OpenSessionAgentContract = OpenSessionContract["agents"][number];

/** Current roster entry accepted by discussion start and update requests. */
export type AgentConfigContract = components["schemas"]["AgentConfigModel"];
export type SynthesisConfigContract = components["schemas"]["SynthesisConfigModel"];
export type UpdateNextRoundConfigurationRequestContract =
  components["schemas"]["UpdateNextRoundConfigurationRequest"];
export type UpdateNextRoundConfigurationResponseContract =
  components["schemas"]["UpdateNextRoundConfigurationResponse"];
export type StartMaterialContextContract = components["schemas"]["MaterialContextModel"];
export type ContextEstimateRequestContract = components["schemas"]["ContextEstimateRequest"];
export type ContextEstimateResponseContract = components["schemas"]["ContextEstimateResponse"];
export type SessionInputDefinitionContract = components["schemas"]["SessionInputDefinition"];
export type DeleteSessionContract = components["schemas"]["DeleteSessionResponse"];
export type BulkDeleteSessionsContract = components["schemas"]["BulkDeleteSessionsResponse"];
export type RevealSessionContract = components["schemas"]["RevealSessionResponse"];
export type DefaultMaterialContract = components["schemas"]["DefaultMaterialResponse"];
export type MaterialLineNumberContract = components["schemas"]["MaterialLineNumberResponse"];
export type RestoreDefaultsContract = components["schemas"]["RestoreDefaultsResponse"];
export type DeletePromptConfigurationContract =
  components["schemas"]["DeletePromptConfigurationResponse"];
export type PromptConfigurationAcknowledgementContract =
  components["schemas"]["PromptConfigurationAcknowledgementResponse"];
export type QuickActionDeleteContract = components["schemas"]["QuickActionDeleteResponse"];
export type QuickActionListContract = components["schemas"]["QuickActionListResponse"];
export type QuickActionRestoreContract = components["schemas"]["QuickActionRestoreResponse"];
export type RevealRoleContract = components["schemas"]["RevealRoleResponse"];
export type RevealRolesDirectoryContract = components["schemas"]["RevealRolesDirectoryResponse"];
export type RevealSessionTypesDirectoryContract =
  components["schemas"]["RevealSessionTypesDirectoryResponse"];
export type RevealGlobalsDirectoryContract =
  components["schemas"]["RevealGlobalsDirectoryResponse"];
export type RevealLocalAIModelsDirectoryContract =
  components["schemas"]["RevealLocalAIModelsDirectoryResponse"];
export type ApplicationActivityResponseContract =
  components["schemas"]["ApplicationActivityResponse"];
export type UIPreferencesContract = components["schemas"]["UIPreferencesResponse"];
export type UIPreferencesUpdateContract = components["schemas"]["UIPreferencesUpdateRequest"];
export type TemplateInfoContract = components["schemas"]["TemplateInfo"];
export type DefaultAgentIdsContract =
  paths["/api/discussions/defaults/agents"]["get"]["responses"][200]["content"]["application/json"];

/** Generated request DTOs used by the API facade. */
export type HostCreateContract = components["schemas"]["HostCreateRequest"];
export type HostUpdateContract = components["schemas"]["HostUpdateRequest"];
export type HostDeletePreviewRequestContract = components["schemas"]["HostDeletePreviewRequest"];
export type HostDeletePreviewContract = components["schemas"]["HostDeletePreviewResponse"];
export type HostDeleteRequestContract = components["schemas"]["HostDeleteRequest"];
export type HostDeleteContract = components["schemas"]["HostDeleteResponse"];
export type DraftHostTestContract = components["schemas"]["DraftHostTestRequest"];
export type SavedHostTestContract = components["schemas"]["SavedHostTestRequest"];
export type TestHostContract = components["schemas"]["TestHostResponse"];
export type QuickActionContract = components["schemas"]["QuickActionInfo"];
export type QuickActionCreateContract = components["schemas"]["QuickActionCreateRequest"];
export type QuickActionUpdateContract = components["schemas"]["QuickActionUpdateRequest"];
export type RoleCreateContract = components["schemas"]["RoleCreateRequest"];
export type RoleUpdateContract = components["schemas"]["RoleUpdateRequest"];
export type SessionTypeCreateContract = components["schemas"]["SessionTypeCreateRequest"];
export type SessionTypeUpdateContract = components["schemas"]["SessionTypeUpdateRequest"];
export type GlobalUpdateContract = components["schemas"]["GlobalUpdateRequest"];
export type LocalAIInstallOptionsContract = components["schemas"]["LocalAIInstallOptions"];
export type LocalAICancelContract = components["schemas"]["LocalAICancelRequest"];
export type LocalAIDeleteModelContract = components["schemas"]["LocalAIDeleteModelRequest"];
export type LocalAIStartContract = components["schemas"]["LocalAIStartRequest"];

/** Generated response DTOs used directly at the API boundary. */
export type PerspectiveContract = components["schemas"]["PerspectiveResponse"];
export type DiscussionSessionTypeContract = components["schemas"]["DiscussionSessionTypeResponse"];
export type DiscussionMessageContract = components["schemas"]["DiscussionMessageResponse"];
export type DiscussionStateContract = components["schemas"]["DiscussionStateResponse"];
export type CancelDiscussionContract = components["schemas"]["CancelDiscussionResponse"];
export type DiscussionStreamEventContract = components["schemas"]["DiscussionStreamEventResponse"];
export type HostInfoContract = components["schemas"]["HostInfoResponse"];
export type HostModelsContract = components["schemas"]["HostModelsResponse"];
export type RoleContract = components["schemas"]["RoleResponse"];
export type PromptSessionTypeContract = components["schemas"]["PromptSessionTypeResponse"];
export type GlobalBlockContract = components["schemas"]["GlobalBlockResponse"];
export type LocalAIStatusContract = components["schemas"]["LocalAIStatusResponse"];
export type LocalAIDiagnosticsContract = components["schemas"]["LocalAIDiagnosticsResponse"];
export type LocalAIInventoryContract = components["schemas"]["LocalAIModelInventoryResponse"];
export type LocalAIRuntimeSelectionContract =
  components["schemas"]["LocalAIRuntimeSelectionResponse"];
export type JobContract = components["schemas"]["JobResponse"];
export type DetectedModelImportJobContract =
  components["schemas"]["DetectedModelImportJobResponse"];
export type ImportStartContract = components["schemas"]["ImportStartResponse"];
export type MaterialTokenEstimateContract = components["schemas"]["MaterialTokenEstimateResponse"];
