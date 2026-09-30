import { fetchJSON } from "./client";
import type { PromptPreviewContract, TemplateInfoContract } from "./contracts";

export type PreviewTemplate = TemplateInfoContract;

export type PromptPreviewResult = PromptPreviewContract;

export function listPreviewTemplates(signal?: AbortSignal): Promise<PreviewTemplate[]> {
  return fetchJSON("/api/preview/templates", { signal });
}

export function getPromptPreview(
  templateId: string,
  multiAgent: boolean,
  sessionType: string,
  scenario: string,
  signal?: AbortSignal,
): Promise<PromptPreviewResult> {
  const params = new URLSearchParams({
    multi_agent: String(multiAgent),
    session_type: sessionType,
    scenario,
  });
  return fetchJSON(`/api/preview/${encodeURIComponent(templateId)}?${params}`, { signal });
}
