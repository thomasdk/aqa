import type { HostInfo, LocalAIStatus } from "./types";

export type HostModelSource = Pick<HostInfo, "models"> & Partial<Pick<HostInfo, "model">>;

export type HostSelectionHost = HostModelSource &
  Pick<HostInfo, "configuration_id" | "label" | "url" | "models" | "is_favorite" | "model">;

function cleanModel(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const model = value.trim();
  return model || null;
}

function uniqueModels(values: readonly unknown[]): string[] {
  const result: string[] = [];
  for (const value of values) {
    const model = cleanModel(value);
    if (model && !result.includes(model)) result.push(model);
  }
  return result;
}

/**
 * Return the selectable model list for a host without making a request.
 *
 * `models` is the authoritative stored list.
 */
export function normalizeHostModels(host: HostModelSource): string[] {
  return uniqueModels(host.models);
}

/** Managed choices require verified local artifacts; external catalogues are independent. */
export function isHostModelAvailable(
  host: HostInfo | undefined,
  model: string,
  localStatus: LocalAIStatus | null,
): boolean {
  if (!host || !normalizeHostModels(host).includes(model)) return false;
  if (host.kind !== "local_ai") return true;
  return Boolean(
    localStatus?.models?.some(
      (entry) => entry.api_alias === model && entry.installed && entry.integrity === "verified",
    ),
  );
}

function pickDefaultHost(hosts: readonly HostSelectionHost[]): HostSelectionHost {
  const favoriteHosts = hosts.filter((host) => (host as HostInfo).is_favorite);
  return favoriteHosts[0] ?? hosts[0];
}

/**
 * Resolve a host/model pair after initial host loading or a host change.
 * A model is retained only when it is selectable on the chosen host;
 * otherwise the chosen host's preferred (first) model is selected.
 */
export function resolveHostAndModelSelection(
  _currentHost: string | null | undefined,
  currentModel: string | null | undefined,
  hosts: readonly HostSelectionHost[],
  currentHostConfigurationId?: string | null,
): AgentHostSelection {
  if (hosts.length === 0)
    return { api_host: null, llm_id: null, host_configuration_id: null, host_label: null };

  const selectedHost = currentHostConfigurationId
    ? (hosts.find((host) => host.configuration_id === currentHostConfigurationId) ??
      pickDefaultHost(hosts))
    : pickDefaultHost(hosts);
  const selectableModels = normalizeHostModels(selectedHost);
  const normalizedCurrentModel = cleanModel(currentModel);
  const selectedModel =
    normalizedCurrentModel && selectableModels.includes(normalizedCurrentModel)
      ? normalizedCurrentModel
      : (selectableModels[0] ?? null);

  return {
    api_host: selectedHost.url,
    llm_id: selectedModel,
    host_configuration_id: selectedHost.configuration_id,
    host_label: selectedHost.label,
  };
}

/**
 * Unconditionally select the target host, resetting the model to the target
 * host's preferred (first) model. Use this for explicit host dropdown changes
 * so the user sees the new preferred model even if their previous model name
 * also exists on the target host.
 */
export function selectHostAndPreferredModel(
  targetHost: string | null | undefined,
  hosts: readonly HostSelectionHost[],
): AgentHostSelection {
  if (hosts.length === 0 || !targetHost) {
    return { api_host: null, llm_id: null, host_configuration_id: null, host_label: null };
  }

  const selectedHost = hosts.find((host) => host.configuration_id === targetHost);
  if (!selectedHost)
    return { api_host: null, llm_id: null, host_configuration_id: null, host_label: null };

  const selectableModels = normalizeHostModels(selectedHost);
  return {
    api_host: selectedHost.url,
    llm_id: selectableModels[0] ?? null,
    host_configuration_id: selectedHost.configuration_id,
    host_label: selectedHost.label,
  };
}

/** Normalize a preferred model plus editable rows for a CRUD payload. */
export function normalizeModelNames(
  preferredModel: string | null | undefined,
  modelRows: readonly string[] = [],
): string[] {
  return uniqueModels([preferredModel, ...modelRows]);
}

/** The host/model selection stored on a Setup draft agent. */
export type AgentHostSelection = {
  api_host: string | null;
  llm_id: string | null;
  host_configuration_id?: string | null;
  host_label?: string | null;
};

/** Choose the favourite host (otherwise first) and its first stored model. */
export function defaultHostAndPreferredModel(
  hosts: readonly HostSelectionHost[],
): AgentHostSelection {
  if (hosts.length === 0)
    return { api_host: null, llm_id: null, host_configuration_id: null, host_label: null };
  const host = pickDefaultHost(hosts);
  return {
    api_host: host.url,
    llm_id: normalizeHostModels(host)[0] ?? null,
    host_configuration_id: host.configuration_id,
    host_label: host.label,
  };
}

/**
 * Reconcile a snapshot of Setup draft agents against a new host catalogue.
 *
 * Only selections that were following a default follow the replacement:
 * - an agent exactly on the previous global default moves to the new default;
 * - an agent exactly on a host's previous preferred (first) model moves to that
 *   host's new preferred model;
 * - an explicit valid selection that is still present in the new catalogue is
 *   left untouched.
 *
 * Invalid selections (deleted host, removed model) are repaired against the
 * new catalogue. The result preserves array and per-agent identity when no
 * reconciliation is required, so callers can short-circuit `setState` updates.
 */
export function reconcileDraftAgentHostSelections<T extends AgentHostSelection>(
  agents: T[],
  previousHosts: readonly HostSelectionHost[],
  nextHosts: readonly HostSelectionHost[],
  defaultSelection: (
    hosts: readonly HostSelectionHost[],
  ) => AgentHostSelection = defaultHostAndPreferredModel,
): T[] {
  const previousDefault = defaultSelection(previousHosts);
  const nextDefault = defaultSelection(nextHosts);
  const catalogueIsEmpty = nextHosts.length === 0;

  let changed = false;
  const reconciled = agents.map((agent) => {
    // An empty catalogue invalidates every host selection.
    if (catalogueIsEmpty) {
      if (
        agent.api_host === null &&
        agent.llm_id === null &&
        !agent.host_configuration_id &&
        !agent.host_label
      )
        return agent;
      changed = true;
      return {
        ...agent,
        api_host: null,
        llm_id: null,
        host_configuration_id: null,
        host_label: null,
      };
    }

    const followedOldGlobalDefault =
      agent.host_configuration_id === previousDefault.host_configuration_id &&
      agent.api_host === previousDefault.api_host &&
      agent.llm_id === previousDefault.llm_id;
    const globalDefaultChanged =
      previousDefault.host_configuration_id !== nextDefault.host_configuration_id ||
      previousDefault.api_host !== nextDefault.api_host ||
      previousDefault.llm_id !== nextDefault.llm_id;
    if (followedOldGlobalDefault && globalDefaultChanged) {
      changed = true;
      return { ...agent, ...nextDefault };
    }

    const oldHost = previousHosts.find(
      (host) =>
        host.configuration_id === agent.host_configuration_id && host.url === agent.api_host,
    );
    const nextHost = nextHosts.find(
      (host) =>
        host.configuration_id === agent.host_configuration_id && host.url === agent.api_host,
    );
    const oldPreferred = oldHost ? (normalizeHostModels(oldHost)[0] ?? null) : null;
    const nextPreferred = nextHost ? (normalizeHostModels(nextHost)[0] ?? null) : null;
    if (nextHost && agent.llm_id === oldPreferred && oldPreferred !== nextPreferred) {
      changed = true;
      return { ...agent, api_host: nextHost.url, llm_id: nextPreferred };
    }

    // Only repair selections the catalogue can speak to: the host was known
    // before (so a missing entry means a deletion) or the host still exists
    // in the new catalogue (so the model can be re-validated). An orphan host
    // that was never in the catalogue is preserved as-is.
    if (!oldHost && !nextHost) {
      return agent;
    }

    const resolved = resolveHostAndModelSelection(
      agent.api_host,
      agent.llm_id,
      nextHosts,
      agent.host_configuration_id,
    );
    if (
      resolved.host_configuration_id === agent.host_configuration_id &&
      resolved.api_host === agent.api_host &&
      resolved.llm_id === agent.llm_id
    ) {
      return agent;
    }
    changed = true;
    return { ...agent, ...resolved };
  });
  return changed ? reconciled : agents;
}
