import type { AgentConfig, HostInfo, SynthesisConfig } from "./types";
import {
  defaultHostAndPreferredModel,
  normalizeHostModels,
  type AgentHostSelection,
} from "./hostModelSelection";

/** The persisted choice is deliberately browser-local, like the UI language. */
export const AI_SOURCE_STORAGE_KEY = "aqa.aiSource.v1";

export type AISource = "integrated" | "external";

const INTEGRATED_SOURCE: AISource = "integrated";

export function isAISource(value: unknown): value is AISource {
  return value === "integrated" || value === "external";
}

export function readPreferredAISource(): AISource {
  return readStoredPreferredAISource() ?? INTEGRATED_SOURCE;
}

export function readStoredPreferredAISource(): AISource | null {
  try {
    const stored = window.localStorage.getItem(AI_SOURCE_STORAGE_KEY);
    return isAISource(stored) ? stored : null;
  } catch {
    return null;
  }
}

export function persistPreferredAISource(source: AISource): void {
  try {
    window.localStorage.setItem(AI_SOURCE_STORAGE_KEY, source);
  } catch {
    // The in-memory selection remains usable when browser storage is unavailable.
  }
}

export function integratedHosts(hosts: readonly HostInfo[]): HostInfo[] {
  return hosts.filter((host) => host.kind === "local_ai");
}

export function externalHosts(hosts: readonly HostInfo[]): HostInfo[] {
  return hosts.filter((host) => host.kind !== "local_ai");
}

export function hasUsableExternalAI(hosts: readonly HostInfo[]): boolean {
  return externalHosts(hosts).some(
    (host) => Boolean(host.url.trim()) && normalizeHostModels(host).length > 0,
  );
}

/**
 * Whether the current discussion configuration has executable work assigned
 * to the managed Integrated AI host.  This deliberately uses the saved host
 * stable configuration ID rather than the browser-local preference so opened and mixed
 * sessions remain truthful.
 */
export function usesIntegratedAI(
  agents: readonly AgentConfig[],
  synthesis: SynthesisConfig | undefined,
  hosts: readonly HostInfo[],
): boolean {
  const integratedIds = new Set(integratedHosts(hosts).map((host) => host.configuration_id));
  const usesIntegratedHost = (enabled: boolean, configurationId: string | null | undefined) =>
    enabled && configurationId != null && integratedIds.has(configurationId);

  return (
    agents.some((agent) => usesIntegratedHost(agent.enabled, agent.host_configuration_id)) ||
    Boolean(synthesis && usesIntegratedHost(synthesis.enabled, synthesis.host_configuration_id))
  );
}

/** Resolve the standard host/model pair for the selected source. */
export function defaultSelectionForAISource(
  source: AISource,
  hosts: readonly HostInfo[],
): AgentHostSelection {
  if (source === "external") {
    const usableExternalHosts = externalHosts(hosts).filter(
      (host) => Boolean(host.url.trim()) && normalizeHostModels(host).length > 0,
    );
    return defaultHostAndPreferredModel(usableExternalHosts);
  }
  const integrated = integratedHosts(hosts)[0];
  return integrated
    ? {
        api_host: integrated.url,
        llm_id: normalizeHostModels(integrated)[0] ?? null,
        host_configuration_id: integrated.configuration_id,
        host_label: integrated.label,
      }
    : { api_host: null, llm_id: null, host_configuration_id: null, host_label: null };
}
