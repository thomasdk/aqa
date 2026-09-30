import { useTranslation } from "react-i18next";
import { displayHostLabel, displayModelName } from "./displayNames";
import {
  isHostModelAvailable,
  normalizeHostModels,
  selectHostAndPreferredModel,
} from "./hostModelSelection";
import MaterialSymbol from "./MaterialSymbol";
import type {
  AgentConfig,
  HostInfo,
  LocalAIStatus,
  Perspective,
  Role,
  SynthesisConfig,
} from "./types";
import { Select } from "./design-system";

export const TEMPERATURE_OVERRIDE_INIT = 1.0;

const shortPerspectiveDescription = (role: Role | undefined): string | null => {
  const source = role?.description?.trim();
  if (!source) return null;
  const firstLine = source.split(/\n\s*\n|\n/)[0].trim();
  return firstLine.length > 150 ? `${firstLine.slice(0, 147).trimEnd()}…` : firstLine;
};

const perspectiveDisplayName = (
  promptId: string | null,
  perspectives: readonly Perspective[],
): string | null => perspectives.find((item) => item.id === promptId)?.label ?? null;

export const hasValidProviderSelection = (
  selection: Pick<AgentConfig, "api_host" | "host_configuration_id" | "llm_id">,
  hosts: readonly HostInfo[],
  localStatus: LocalAIStatus | null = null,
): boolean => {
  if (
    selection.api_host === null &&
    (selection.host_configuration_id ?? null) === null &&
    selection.llm_id === null
  ) {
    return true;
  }
  const host = hosts.find(
    (item) =>
      item.configuration_id === selection.host_configuration_id &&
      item.url.replace(/\/$/, "") === selection.api_host?.replace(/\/$/, ""),
  );
  return Boolean(
    host && selection.llm_id && isHostModelAvailable(host, selection.llm_id, localStatus),
  );
};

type PerspectiveConfigurationProps = {
  agent: AgentConfig;
  index: number;
  perspectives: readonly Perspective[];
  roles: readonly Role[];
  hosts: readonly HostInfo[];
  localStatus?: LocalAIStatus | null;
  expanded: boolean;
  disabled?: boolean;
  fallbackToFirstHost?: boolean;
  idPrefix: string;
  onToggleExpanded: () => void;
  onChange: (patch: Partial<AgentConfig>) => void;
  inline?: boolean;
};

export const PerspectiveConfigurationControls = ({
  agent,
  index,
  perspectives,
  roles,
  hosts,
  localStatus = null,
  expanded,
  disabled = false,
  fallbackToFirstHost = false,
  idPrefix,
  onToggleExpanded,
  onChange,
  inline = false,
}: PerspectiveConfigurationProps) => {
  const { t } = useTranslation();
  const slotKey = agent.client_id || String(index);
  const selectId = `${idPrefix}-perspective-slot-${slotKey}`;
  const optionsId = `${idPrefix}-perspective-options-${slotKey}`;
  const temperatureId = `${idPrefix}-perspective-temperature-${slotKey}`;
  const role = roles.find((item) => item.id === agent.prompt_id);
  const perspectiveDescription = shortPerspectiveDescription(role);
  const exactHost = hosts.find(
    (item) =>
      item.configuration_id === agent.host_configuration_id &&
      item.url.replace(/\/$/, "") === agent.api_host?.replace(/\/$/, ""),
  );
  const hasProviderSelection = Boolean(
    agent.host_configuration_id || agent.api_host || agent.llm_id,
  );
  const selectedHost =
    exactHost ?? (!hasProviderSelection && fallbackToFirstHost ? hosts[0] : undefined);
  const hostMissing =
    (agent.enabled && !hasProviderSelection) || (hasProviderSelection && !exactHost);
  const selectedModels = selectedHost ? normalizeHostModels(selectedHost) : [];
  const modelMissing =
    Boolean(agent.llm_id) && !isHostModelAvailable(selectedHost, agent.llm_id ?? "", localStatus);
  const roleMissing =
    Boolean(agent.prompt_id) && !perspectives.some((item) => item.id === agent.prompt_id);

  return (
    <section
      className={`agent-config-row${inline ? " activity-inline-config" : ""}${roleMissing || hostMissing || modelMissing ? " is-invalid" : ""}`}
      style={{ borderLeft: `3px solid ${agent.color}` }}
    >
      <div className="agent-config-summary">
        <span className="agent-config-summary-copy">
          <label htmlFor={selectId}>
            {t("setup.perspectiveSlot", { number: agent.perspective_number || index + 1 })}
          </label>
          <Select
            id={selectId}
            value={agent.prompt_id ?? ""}
            disabled={disabled}
            aria-label={t("setup.choosePerspective")}
            aria-invalid={roleMissing || undefined}
            onChange={(event) => {
              const promptId = event.target.value || null;
              const selectedName = perspectiveDisplayName(promptId, perspectives);
              onChange({
                prompt_id: promptId,
                enabled: Boolean(promptId),
                ...(selectedName ? { name: selectedName } : {}),
              });
            }}
          >
            {roleMissing && (
              <option value={agent.prompt_id ?? ""}>{t("activity.roleUnavailable")}</option>
            )}
            <option value="">{t("setup.noPerspectiveOption")}</option>
            {perspectives.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </Select>
          <small>{perspectiveDescription ?? t("setup.noPerspectiveDescription")}</small>
        </span>
        {!inline && (
          <button
            type="button"
            className="agent-config-options-toggle"
            aria-controls={optionsId}
            aria-expanded={expanded}
            disabled={disabled}
            title={t("setup.options")}
            onClick={onToggleExpanded}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onToggleExpanded();
              }
            }}
          >
            <MaterialSymbol name="tune" decorative />
            {t("setup.options")}
          </button>
        )}
      </div>

      {roleMissing && (
        <p className="configuration-invalid-notice">{t("activity.roleUnavailable")}</p>
      )}
      {expanded && (
        <div
          id={optionsId}
          className="agent-config-advanced"
          role="region"
          aria-label={t("setup.optionsForPerspective", { number: index + 1 })}
        >
          <div className="agent-controls">
            <label className="agent-config-field">
              <span>{t("setup.host")}</span>
              <Select
                value={agent.host_configuration_id ?? ""}
                disabled={disabled}
                aria-label={t("setup.agentHost", { name: agent.name })}
                aria-invalid={hostMissing || undefined}
                onChange={(event) =>
                  onChange(selectHostAndPreferredModel(event.target.value, hosts))
                }
              >
                {hostMissing && (
                  <option value={agent.host_configuration_id ?? ""}>
                    {t("activity.providerUnavailable")}
                  </option>
                )}
                {hosts.map((item) => (
                  <option key={item.configuration_id} value={item.configuration_id}>
                    {displayHostLabel(item, t)}
                  </option>
                ))}
              </Select>
            </label>
            <label className="agent-config-field">
              <span>{t("setup.model")}</span>
              <Select
                value={modelMissing ? "" : (agent.llm_id ?? "")}
                disabled={disabled || !selectedHost}
                aria-label={t("setup.agentModel", { name: agent.name })}
                aria-invalid={modelMissing || undefined}
                onChange={(event) => {
                  if (!isHostModelAvailable(selectedHost, event.target.value, localStatus)) return;
                  onChange({ llm_id: event.target.value });
                }}
              >
                {modelMissing && (
                  <option value="">
                    {t("activity.modelUnavailable")}: {displayModelName(agent.llm_id ?? "")}
                  </option>
                )}
                {selectedModels.map((model) => (
                  <option
                    key={model}
                    value={model}
                    disabled={!isHostModelAvailable(selectedHost, model, localStatus)}
                  >
                    {displayModelName(model)}
                  </option>
                ))}
              </Select>
            </label>
            {(hostMissing || modelMissing) && (
              <p className="configuration-invalid-notice" role="alert">
                {t(
                  hostMissing
                    ? "activity.providerUnavailableHelp"
                    : "activity.modelUnavailableHelp",
                )}
              </p>
            )}
            <label className="checkbox">
              <input
                type="checkbox"
                checked={agent.temperature !== null}
                disabled={disabled}
                onChange={(event) =>
                  onChange({
                    temperature: event.target.checked ? TEMPERATURE_OVERRIDE_INIT : null,
                  })
                }
              />
              {t("setup.temperatureOverride")}
            </label>
            {agent.temperature !== null && (
              <div className="agent-temperature-control">
                <label htmlFor={temperatureId}>
                  {t("setup.temperature")}: {agent.temperature.toFixed(1)}
                </label>
                <input
                  id={temperatureId}
                  type="range"
                  min="0"
                  max="2"
                  step="0.1"
                  value={agent.temperature}
                  disabled={disabled}
                  onChange={(event) => onChange({ temperature: Number(event.target.value) })}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
};

type SynthesisConfigurationProps = {
  synthesis: SynthesisConfig;
  hosts: readonly HostInfo[];
  localStatus?: LocalAIStatus | null;
  expanded: boolean;
  disabled?: boolean;
  fallbackToFirstHost?: boolean;
  idPrefix: string;
  onToggleExpanded: () => void;
  onChange: (patch: Partial<SynthesisConfig>) => void;
  inline?: boolean;
};

export const SynthesisConfigurationControls = ({
  synthesis,
  hosts,
  localStatus = null,
  expanded,
  disabled = false,
  fallbackToFirstHost = false,
  idPrefix,
  onToggleExpanded,
  onChange,
  inline = false,
}: SynthesisConfigurationProps) => {
  const { t } = useTranslation();
  const exactHost = hosts.find(
    (item) =>
      item.configuration_id === synthesis.host_configuration_id &&
      item.url.replace(/\/$/, "") === synthesis.api_host?.replace(/\/$/, ""),
  );
  const hasProviderSelection = Boolean(
    synthesis.host_configuration_id || synthesis.api_host || synthesis.llm_id,
  );
  const selectedHost =
    exactHost ?? (!hasProviderSelection && fallbackToFirstHost ? hosts[0] : undefined);
  const hostMissing =
    (synthesis.enabled && !hasProviderSelection) || (hasProviderSelection && !exactHost);
  const models = selectedHost ? normalizeHostModels(selectedHost) : [];
  const modelMissing =
    Boolean(synthesis.llm_id) &&
    !isHostModelAvailable(selectedHost, synthesis.llm_id ?? "", localStatus);
  const controlsDisabled = disabled || !synthesis.enabled;
  const optionsId = `${idPrefix}-synthesis-options`;
  const temperatureId = `${idPrefix}-synthesis-temperature`;

  return (
    <section
      className={`synthesis-config${inline ? " activity-inline-config" : ""}${hostMissing || modelMissing ? " is-invalid" : ""}`}
      aria-labelledby={`${idPrefix}-synthesis-title`}
    >
      {!inline && (
        <div className="synthesis-config-summary">
          <div>
            <h2 id={`${idPrefix}-synthesis-title`}>{t("setup.synthesis.title")}</h2>
            <p>{t("setup.synthesis.description")}</p>
          </div>
          <div className="synthesis-config-actions">
            <label className="checkbox synthesis-enabled-toggle">
              <input
                type="checkbox"
                checked={synthesis.enabled}
                disabled={disabled}
                onChange={(event) => onChange({ enabled: event.target.checked })}
              />
              {t("common.active")}
            </label>
            <button
              type="button"
              className="agent-config-options-toggle"
              aria-controls={optionsId}
              aria-expanded={expanded}
              disabled={disabled}
              onClick={onToggleExpanded}
            >
              <MaterialSymbol name="tune" decorative />
              {t("setup.options")}
            </button>
          </div>
        </div>
      )}
      {expanded && (
        <div id={optionsId} className="agent-controls synthesis-config-controls">
          <label className="agent-config-field">
            <span>{t("setup.host")}</span>
            <Select
              value={synthesis.host_configuration_id ?? ""}
              disabled={controlsDisabled}
              aria-label={t("setup.synthesis.host")}
              aria-invalid={hostMissing || undefined}
              onChange={(event) => onChange(selectHostAndPreferredModel(event.target.value, hosts))}
            >
              {hostMissing && (
                <option value={synthesis.host_configuration_id ?? ""}>
                  {t("activity.providerUnavailable")}
                </option>
              )}
              {hosts.map((item) => (
                <option key={item.configuration_id} value={item.configuration_id}>
                  {displayHostLabel(item, t)}
                </option>
              ))}
            </Select>
          </label>
          <label className="agent-config-field">
            <span>{t("setup.model")}</span>
            <Select
              value={modelMissing ? "" : (synthesis.llm_id ?? "")}
              disabled={controlsDisabled || !selectedHost}
              aria-label={t("setup.synthesis.model")}
              aria-invalid={modelMissing || undefined}
              onChange={(event) => {
                if (!isHostModelAvailable(selectedHost, event.target.value, localStatus)) return;
                onChange({ llm_id: event.target.value });
              }}
            >
              {modelMissing && (
                <option value="">
                  {t("activity.modelUnavailable")}: {displayModelName(synthesis.llm_id ?? "")}
                </option>
              )}
              {models.map((model) => (
                <option
                  key={model}
                  value={model}
                  disabled={!isHostModelAvailable(selectedHost, model, localStatus)}
                >
                  {displayModelName(model)}
                </option>
              ))}
            </Select>
          </label>
          {(hostMissing || modelMissing) && (
            <p className="configuration-invalid-notice" role="alert">
              {t(
                hostMissing ? "activity.providerUnavailableHelp" : "activity.modelUnavailableHelp",
              )}
            </p>
          )}
          <label className="checkbox">
            <input
              type="checkbox"
              checked={synthesis.temperature !== null}
              disabled={controlsDisabled}
              onChange={(event) =>
                onChange({
                  temperature: event.target.checked ? TEMPERATURE_OVERRIDE_INIT : null,
                })
              }
            />
            {t("setup.temperatureOverride")}
          </label>
          {synthesis.temperature !== null && (
            <div className="agent-temperature-control">
              <label htmlFor={temperatureId}>
                {t("setup.temperature")}: {synthesis.temperature.toFixed(1)}
              </label>
              <input
                id={temperatureId}
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={synthesis.temperature}
                disabled={controlsDisabled}
                onChange={(event) => onChange({ temperature: Number(event.target.value) })}
              />
            </div>
          )}
        </div>
      )}
    </section>
  );
};
