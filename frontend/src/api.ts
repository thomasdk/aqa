import type { AppLocale } from "./i18n";
import type {
  DraftHostTestContract,
  DefaultAgentIdsContract,
  DefaultMaterialContract,
  DetectedModelImportJobContract,
  DeletePromptConfigurationContract,
  CancelDiscussionContract,
  ContextEstimateRequestContract,
  ContextEstimateResponseContract,
  GlobalUpdateContract,
  HostCreateContract,
  HostDeleteContract,
  HostDeletePreviewContract,
  HostDeletePreviewRequestContract,
  HostDeleteRequestContract,
  HostUpdateContract,
  LocalAICancelContract,
  LocalAIDeleteModelContract,
  LocalAIInstallOptionsContract,
  LocalAIStartContract,
  ImportStartContract,
  JobContract,
  MaterialTokenEstimateContract,
  MaterialLineNumberContract,
  PromptConfigurationAcknowledgementContract,
  QuickActionContract,
  QuickActionCreateContract,
  QuickActionDeleteContract,
  QuickActionListContract,
  QuickActionRestoreContract,
  QuickActionUpdateContract,
  RevealGlobalsDirectoryContract,
  RevealLocalAIModelsDirectoryContract,
  RevealRoleContract,
  RevealRolesDirectoryContract,
  RevealSessionTypesDirectoryContract,
  RestoreDefaultsContract,
  RoleCreateContract,
  RoleUpdateContract,
  SavedHostTestContract,
  SessionTypeCreateContract,
  SessionTypeUpdateContract,
  TestHostContract,
  UIPreferencesContract,
  UIPreferencesUpdateContract,
  UpdateNextRoundConfigurationRequestContract,
  UpdateNextRoundConfigurationResponseContract,
} from "./api/contracts";
import type {
  AgentConfig,
  SynthesisConfig,
  Perspective,
  SessionType,
  DiscussionState,
  HostInfo,
  Role,
  SessionTypeDetail,
  GlobalBlock,
  LocalAIModelId,
  LocalAIDiagnostics,
  LocalAIStatus,
  RoundProviderProvenance,
} from "./components/types";
import { ApiError, apiErrorPayload, fetchJSON } from "./api/client";

export { ApiError } from "./api/client";
export type { HealthResponse } from "./api/contracts";
export {
  continueDiscussionStream,
  DiscussionStreamIncompleteError,
  isSSEEvent,
  parseSSEStream,
  startDiscussionStream,
} from "./api/discussion-stream";
export type {
  ContinueDiscussionParams,
  DiscussionStreamOptions,
  StartDiscussionParams,
} from "./api/discussion-stream";
export { getPromptPreview, listPreviewTemplates } from "./api/preview";
export type { PreviewTemplate, PromptPreviewResult } from "./api/preview";
export { getApplicationActivity } from "./api/activity";
export type {
  ApplicationActivityEvent,
  ApplicationActivityLevel,
  ApplicationActivityResponse,
} from "./api/activity";
export {
  bulkDeleteSessions,
  deleteSession,
  listSessions,
  openSession,
  renameSession,
  revealSession,
  setSessionFavorite,
} from "./api/sessions";

export type {
  LocalAIIntegrity,
  LocalAIDiagnostics,
  LocalAIModelId,
  LocalAIModelCatalogEntry,
  LocalAIState,
  LocalAIStatus,
  SessionSnapshot,
  SessionMessage,
  SessionSummary,
  SessionMaterialContext,
  SessionAgent,
  DeleteSessionResult,
  BulkDeleteSessionsResult,
  SynthesisConfig,
} from "./components/types";

export type { HostInfo };

export async function getApplicationPreferences(): Promise<UIPreferencesContract> {
  return fetchJSON("/api/application/preferences");
}

export async function updateApplicationPreferences(
  preferences: UIPreferencesUpdateContract,
): Promise<UIPreferencesContract> {
  return fetchJSON("/api/application/preferences", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(preferences),
  });
}

export async function getPerspectives(): Promise<Perspective[]> {
  return fetchJSON("/api/discussions/perspectives");
}

export async function getSessionTypes(signal?: AbortSignal): Promise<SessionType[]> {
  return fetchJSON("/api/discussions/session-types", { signal });
}

export async function getDefaultAgents(sessionType: string): Promise<DefaultAgentIdsContract> {
  return fetchJSON(
    `/api/discussions/defaults/agents?session_type=${encodeURIComponent(sessionType)}`,
  );
}

export async function getDefaultMaterial(): Promise<DefaultMaterialContract> {
  return fetchJSON("/api/defaults/material");
}

export async function getMaterialWithLineNumbers(
  material: string,
): Promise<MaterialLineNumberContract> {
  return fetchJSON("/api/material/with-line-numbers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ material }),
  });
}

export async function getDiscussionState(): Promise<DiscussionState> {
  return fetchJSON("/api/discussions/state");
}

export type MaterialTokenEstimate = MaterialTokenEstimateContract;

export async function estimateMaterialTokens(
  material: string,
  materialType: string,
  signal?: AbortSignal,
): Promise<MaterialTokenEstimate> {
  return fetchJSON("/api/material/token-estimate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ material, material_type: materialType }),
    signal,
  });
}

export type ContextEstimate = ContextEstimateResponseContract;

export async function estimateDiscussionContext(
  payload: ContextEstimateRequestContract,
  signal?: AbortSignal,
): Promise<ContextEstimate> {
  return fetchJSON("/api/discussions/context-estimate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
}

export async function resetDiscussion(): Promise<void> {
  await fetchJSON("/api/discussions/reset", { method: "POST" });
}

export async function updateNextRoundConfiguration(
  payload: UpdateNextRoundConfigurationRequestContract,
): Promise<UpdateNextRoundConfigurationResponseContract> {
  return fetchJSON("/api/discussions/next-round-configuration", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function exportDiscussionUrl(locale: AppLocale, downloadFilename: string): string {
  const params = new URLSearchParams({ locale, download_filename: downloadFilename });
  return `/api/discussions/export?${params}`;
}

export async function getDiscussionExport(
  locale: AppLocale,
  downloadFilename: string,
): Promise<string> {
  const response = await fetch(exportDiscussionUrl(locale, downloadFilename));
  if (!response.ok) {
    const error = apiErrorPayload(await response.text());
    throw new ApiError(response.status, error.detail, error.code, error.params);
  }
  return response.text();
}

export async function setMessageNote(
  messageId: string,
  note: string,
  includeNoteInAgentContext: boolean,
): Promise<void> {
  await fetchJSON(`/api/discussions/messages/${messageId}/note`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note, include_note_in_agent_context: includeNoteInAgentContext }),
  });
}

export async function clearMessageNote(messageId: string): Promise<void> {
  await fetchJSON(`/api/discussions/messages/${messageId}/note`, { method: "DELETE" });
}

export async function updateDiscussionAgents(agents: AgentConfig[]): Promise<void> {
  await fetchJSON("/api/discussions/agents", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agents }),
  });
}

export async function updateDiscussionSynthesis(
  fileId: string,
  synthesis: SynthesisConfig,
): Promise<void> {
  await fetchJSON("/api/discussions/synthesis", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_id: fileId, synthesis }),
  });
}

export async function setMessageContextInclusion(
  messageId: string,
  include: boolean,
): Promise<void> {
  await fetchJSON(`/api/discussions/messages/${encodeURIComponent(messageId)}/context-inclusion`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ include_in_agent_context: include }),
  });
}

export async function listHosts(): Promise<HostInfo[]> {
  return fetchJSON("/api/hosts");
}

export type HostCreatePayload = HostCreateContract;
export type HostUpdatePayload = HostUpdateContract;
export type HostDeletePreview = HostDeletePreviewContract;
export type TestHostResponse = TestHostContract;
export type DraftHostTestPayload = DraftHostTestContract;

export async function createHost(data: HostCreatePayload): Promise<HostInfo> {
  return fetchJSON("/api/hosts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function updateHost(index: number, data: HostUpdatePayload): Promise<HostInfo> {
  return fetchJSON(`/api/hosts/${index}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function previewHostDeletion(
  data: HostDeletePreviewRequestContract,
): Promise<HostDeletePreviewContract> {
  return fetchJSON("/api/hosts/delete-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function deleteHost(data: HostDeleteRequestContract): Promise<HostDeleteContract> {
  return fetchJSON("/api/hosts/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function getDiscussionProviderProvenance(): Promise<RoundProviderProvenance[]> {
  return fetchJSON("/api/discussions/provider-provenance");
}

export async function testHost(
  index: number,
  data: SavedHostTestContract,
): Promise<TestHostResponse> {
  return fetchJSON(`/api/hosts/${index}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function testDraftHost(data: DraftHostTestPayload): Promise<TestHostResponse> {
  return fetchJSON("/api/hosts/test-connection", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export type QuickAction = QuickActionContract;
export type QuickActionCreatePayload = QuickActionCreateContract;
export type QuickActionUpdatePayload = QuickActionUpdateContract;

export async function listQuickActions(): Promise<QuickActionListContract> {
  return fetchJSON("/api/quick-actions");
}

export async function createQuickAction(data: QuickActionCreatePayload): Promise<QuickAction> {
  return fetchJSON("/api/quick-actions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function updateQuickAction(
  id: string,
  data: QuickActionUpdatePayload,
): Promise<QuickAction> {
  return fetchJSON(`/api/quick-actions/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function deleteQuickAction(id: string): Promise<QuickActionDeleteContract> {
  return fetchJSON(`/api/quick-actions/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function restoreDefaultQuickAction(id: string): Promise<QuickActionRestoreContract> {
  return fetchJSON(`/api/quick-actions/${encodeURIComponent(id)}/restore-default`, {
    method: "POST",
  });
}

export async function restoreDefaultQuickActions(): Promise<QuickActionRestoreContract> {
  return fetchJSON("/api/quick-actions/restore-defaults", { method: "POST" });
}

export type RoleCreatePayload = RoleCreateContract;
export type RoleUpdatePayload = RoleUpdateContract;

export async function listRoles(): Promise<Role[]> {
  return fetchJSON("/api/prompts/roles");
}

export async function getRole(roleId: string): Promise<Role> {
  return fetchJSON(`/api/prompts/roles/${encodeURIComponent(roleId)}`);
}

export async function createRole(data: RoleCreatePayload): Promise<Role> {
  return fetchJSON("/api/prompts/roles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function updateRole(roleId: string, data: RoleUpdatePayload): Promise<Role> {
  return fetchJSON(`/api/prompts/roles/${encodeURIComponent(roleId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function deleteRole(
  roleId: string,
): Promise<PromptConfigurationAcknowledgementContract> {
  return fetchJSON(`/api/prompts/roles/${encodeURIComponent(roleId)}`, { method: "DELETE" });
}

export async function restoreDefaultRoles(): Promise<RestoreDefaultsContract> {
  return fetchJSON("/api/prompts/roles/restore-defaults", { method: "POST" });
}

export async function restoreDefaultRole(roleId: string): Promise<RestoreDefaultsContract> {
  return fetchJSON(`/api/prompts/roles/${encodeURIComponent(roleId)}/restore-default`, {
    method: "POST",
  });
}

// Managed-path reveal responses never expose local filesystem paths to the browser.
export async function revealRoleSource(roleId: string): Promise<RevealRoleContract> {
  return fetchJSON(`/api/prompts/roles/${encodeURIComponent(roleId)}/reveal`, { method: "POST" });
}

export async function revealRolesDirectory(): Promise<RevealRolesDirectoryContract> {
  return fetchJSON("/api/prompts/roles/reveal-directory", { method: "POST" });
}

export type SessionTypeCreatePayload = SessionTypeCreateContract;
export type SessionTypeUpdatePayload = SessionTypeUpdateContract;
export type GlobalUpdatePayload = GlobalUpdateContract;

export async function listPromptSessionTypes(): Promise<SessionTypeDetail[]> {
  return fetchJSON("/api/prompts/session-types");
}

export async function createPromptSessionType(
  data: SessionTypeCreatePayload,
): Promise<SessionTypeDetail> {
  return fetchJSON("/api/prompts/session-types", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function updatePromptSessionType(
  key: string,
  data: SessionTypeUpdatePayload,
): Promise<SessionTypeDetail> {
  return fetchJSON(`/api/prompts/session-types/${encodeURIComponent(key)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function deletePromptSessionType(
  key: string,
): Promise<DeletePromptConfigurationContract> {
  return fetchJSON(`/api/prompts/session-types/${encodeURIComponent(key)}`, {
    method: "DELETE",
  });
}

export async function restoreDefaultPromptSessionTypes(): Promise<RestoreDefaultsContract> {
  return fetchJSON("/api/prompts/session-types/restore-defaults", { method: "POST" });
}

export async function restoreDefaultPromptSessionType(
  key: string,
): Promise<RestoreDefaultsContract> {
  return fetchJSON(`/api/prompts/session-types/${encodeURIComponent(key)}/restore-default`, {
    method: "POST",
  });
}

export async function revealPromptSessionTypesDirectory(): Promise<RevealSessionTypesDirectoryContract> {
  return fetchJSON("/api/prompts/session-types/reveal-directory", { method: "POST" });
}

export async function listPromptGlobals(): Promise<GlobalBlock[]> {
  return fetchJSON("/api/prompts/globals");
}

export async function updatePromptGlobal(
  globalId: string,
  data: GlobalUpdatePayload,
): Promise<GlobalBlock> {
  return fetchJSON(`/api/prompts/globals/${encodeURIComponent(globalId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function restoreDefaultPromptGlobals(): Promise<RestoreDefaultsContract> {
  return fetchJSON("/api/prompts/globals/restore-defaults", { method: "POST" });
}

export async function restoreDefaultPromptGlobal(
  globalId: string,
): Promise<RestoreDefaultsContract> {
  return fetchJSON(`/api/prompts/globals/${encodeURIComponent(globalId)}/restore-default`, {
    method: "POST",
  });
}

export async function revealPromptGlobalsDirectory(): Promise<RevealGlobalsDirectoryContract> {
  return fetchJSON("/api/prompts/globals/reveal-directory", { method: "POST" });
}

export type LocalAIInstallPayload = LocalAIInstallOptionsContract & {
  model_id: LocalAIModelId;
};
export type LocalAICancelInstallPayload = LocalAICancelContract;
export type LocalAIStartPayload = LocalAIStartContract;

export type LocalAIDeleteModelPayload = LocalAIDeleteModelContract;
export type LocalAIInstallResult = JobContract;
export type LocalAIRuntimeUpdateResult = JobContract;

export type LocalAICancelInstallResult = LocalAIStatus;
export type LocalAIStartResult = LocalAIStatus;
export type LocalAIStopResult = LocalAIStatus;

export type LocalAIImportStartResult = ImportStartContract;
export type LocalAIBackgroundImportResult = DetectedModelImportJobContract;

export async function getLocalAIStatus(): Promise<LocalAIStatus> {
  return fetchJSON<LocalAIStatus>("/api/local-ai/status");
}

export async function getLocalAIDiagnostics(): Promise<LocalAIDiagnostics> {
  return fetchJSON<LocalAIDiagnostics>("/api/local-ai/diagnostics");
}

export async function revealLocalAIModelsDirectory(): Promise<RevealLocalAIModelsDirectoryContract> {
  return fetchJSON("/api/local-ai/models/reveal-directory", { method: "POST" });
}

export async function setLocalAIPreferredModel(modelId: LocalAIModelId): Promise<LocalAIStatus> {
  return fetchJSON<LocalAIStatus>("/api/local-ai/preferred-model", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId }),
  });
}

export async function installLocalAI(
  payload: LocalAIInstallPayload,
): Promise<LocalAIInstallResult> {
  return fetchJSON<LocalAIInstallResult>(
    `/api/local-ai/models/${encodeURIComponent(payload.model_id)}/install`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start_after_install: payload.start_after_install }),
    },
  );
}

export async function beginLocalAIModelImport(
  modelId: LocalAIModelId,
): Promise<LocalAIImportStartResult> {
  return fetchJSON(`/api/local-ai/models/${encodeURIComponent(modelId)}/import`, {
    method: "POST",
  });
}

export async function importLocalAIModelFromDirectory(
  sourcePath?: string,
): Promise<LocalAIBackgroundImportResult> {
  return fetchJSON("/api/local-ai/models/import-from-directory", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sourcePath ? { source_path: sourcePath } : {}),
  });
}

export async function uploadLocalAIImportPart(
  importId: string,
  artifact: "main" | "draft",
  file: File,
  onProgress?: (loaded: number, total: number) => void,
): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("PUT", `/api/local-ai/imports/${encodeURIComponent(importId)}/${artifact}`);
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.upload.onprogress = (event) => {
      const total = event.lengthComputable && event.total > 0 ? event.total : file.size;
      onProgress?.(event.loaded, total);
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        onProgress?.(file.size, file.size);
        resolve();
        return;
      }
      const error = apiErrorPayload(request.responseText);
      reject(new ApiError(request.status, error.detail, error.code, error.params));
    };
    request.onerror = () => reject(new ApiError(0, "Request failed"));
    request.onabort = () => reject(new ApiError(0, "Request failed"));
    request.send(file);
  });
}

export async function finalizeLocalAIModelImport(importId: string): Promise<LocalAIStatus> {
  return fetchJSON("/api/local-ai/imports/finalize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ import_id: importId }),
  });
}

export async function abortLocalAIModelImport(importId: string): Promise<void> {
  await fetchJSON(`/api/local-ai/imports/${encodeURIComponent(importId)}`, { method: "DELETE" });
}

export async function cancelLocalAIInstall(
  payload: LocalAICancelInstallPayload,
): Promise<LocalAICancelInstallResult> {
  return fetchJSON<LocalAICancelInstallResult>("/api/local-ai/install/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteLocalAIModel(
  payload: LocalAIDeleteModelPayload,
): Promise<LocalAIStatus> {
  return fetchJSON<LocalAIStatus>(`/api/local-ai/models/${encodeURIComponent(payload.model_id)}`, {
    method: "DELETE",
  });
}

export async function updateLocalAIRuntime(
  cpuFallback = false,
): Promise<LocalAIRuntimeUpdateResult> {
  const query = cpuFallback ? "?cpu_fallback=true" : "";
  return fetchJSON<LocalAIRuntimeUpdateResult>(`/api/local-ai/runtime/update${query}`, {
    method: "POST",
  });
}

export async function deleteLocalAIRuntime(): Promise<LocalAIStatus> {
  return fetchJSON<LocalAIStatus>("/api/local-ai/runtime", { method: "DELETE" });
}

export async function startLocalAI(payload: LocalAIStartPayload): Promise<LocalAIStartResult> {
  return fetchJSON<LocalAIStartResult>("/api/local-ai/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function stopLocalAI(): Promise<LocalAIStopResult> {
  return fetchJSON<LocalAIStopResult>("/api/local-ai/stop", { method: "POST" });
}

export type CancelDiscussionResult = CancelDiscussionContract;

export async function cancelDiscussionGeneration(): Promise<CancelDiscussionResult> {
  return fetchJSON<CancelDiscussionResult>("/api/discussions/cancel", {
    method: "POST",
  });
}
