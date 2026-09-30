import { useTranslation } from "react-i18next";
import type { HostInfo, LocalAIStatus } from "./types";
import { MaterialSymbol } from "./MaterialSymbol";
import type { WorkbenchView } from "./ViewNavigation";
import { hasUsableExternalAI, type AISource } from "./aiSourceSelection";
import { getStartableLocalAIModelId } from "./localAIState";
import { ChoiceIndicator } from "./design-system";
import NoticeBanner from "./NoticeBanner";

type AIReadinessIndicatorProps = {
  hosts: HostInfo[];
  source: AISource;
  localStatus: LocalAIStatus | null;
  localStatusFailed: boolean;
  onSourceChange: (source: AISource) => void;
  onNavigate: (view: WorkbenchView) => void;
  /** Whether both AI readiness sources have finished loading. */
  readinessChecked?: boolean;
};

export function localAIReadinessKey(status: LocalAIStatus | null, failed: boolean): string {
  if (failed) return "error";
  if (!status) return "loading";
  if (status.host_ready && (status.state === "running" || status.state === "sleeping")) {
    return "ready";
  }
  if (["downloading", "importing", "starting", "cancelling"].includes(status.state)) {
    return "inProgress";
  }
  if (["installed", "stopped", "cancelled"].includes(status.state)) return "startNeeded";
  if (status.state === "not_installed") return "notInstalled";
  return "error";
}

export function isLocalAIUsable(status: LocalAIStatus | null): boolean {
  return Boolean(status?.host_ready && (status.state === "running" || status.state === "sleeping"));
}

const AIReadinessIndicator = ({
  hosts,
  source,
  localStatus,
  localStatusFailed,
  onSourceChange,
  onNavigate,
  readinessChecked = false,
}: AIReadinessIndicatorProps) => {
  const { t } = useTranslation();
  const externalCount = hosts.filter((host) => host.kind !== "local_ai").length;
  const localKey = localAIReadinessKey(localStatus, localStatusFailed);
  const selectedSourceReady =
    source === "integrated" ? isLocalAIUsable(localStatus) : hasUsableExternalAI(hosts);
  const selectedIntegratedAIStartable =
    source === "integrated" && getStartableLocalAIModelId(localStatus) !== null;
  const anyAIReady = isLocalAIUsable(localStatus) || hasUsableExternalAI(hosts);
  const sourceLabel = t(source === "integrated" ? "nav.localAi" : "nav.network");

  const sourceChooser = (
    <div className="ai-readiness-source-chooser">
      <p className="ai-readiness-bulk-default">{t("setup.aiAccess.bulkDefault")}</p>
      <fieldset className="ai-readiness-items">
        <legend className="visually-hidden">{t("setup.aiAccess.select")}</legend>
        <div className={`ai-readiness-item${source === "integrated" ? " is-selected" : ""}`}>
          <label className="ai-readiness-choice">
            <input
              className="choice-radio-input"
              type="radio"
              name="ai-source"
              value="integrated"
              checked={source === "integrated"}
              onChange={() => onSourceChange("integrated")}
            />
            <ChoiceIndicator
              className="ai-readiness-choice-marker"
              selected={source === "integrated"}
            />
            <span className="ai-readiness-choice-copy">
              <strong>{t("nav.localAi")}</strong>
              <small>{t(`setup.aiAccess.local.${localKey}`)}</small>
            </span>
          </label>
          <button
            type="button"
            className="agent-config-options-toggle ai-readiness-configure"
            onClick={() => onNavigate("local-ai")}
          >
            <MaterialSymbol name="tune" decorative />
            {t("setup.options")}
          </button>
        </div>
        <div className={`ai-readiness-item${source === "external" ? " is-selected" : ""}`}>
          <label className="ai-readiness-choice">
            <input
              className="choice-radio-input"
              type="radio"
              name="ai-source"
              value="external"
              checked={source === "external"}
              aria-describedby={
                source === "external" ? "ai-readiness-external-disclosure" : undefined
              }
              onChange={() => onSourceChange("external")}
            />
            <ChoiceIndicator
              className="ai-readiness-choice-marker"
              selected={source === "external"}
            />
            <span className="ai-readiness-choice-copy">
              <strong>{t("nav.network")}</strong>
              <small>
                {externalCount > 0
                  ? t("setup.aiAccess.external.configured", { count: externalCount })
                  : t("setup.aiAccess.external.notConfigured")}
              </small>
            </span>
          </label>
          <button
            type="button"
            className="agent-config-options-toggle ai-readiness-configure"
            onClick={() => onNavigate("network")}
          >
            <MaterialSymbol name="tune" decorative />
            {t("setup.options")}
          </button>
        </div>
      </fieldset>
      {source === "external" && (
        <NoticeBanner
          id="ai-readiness-external-disclosure"
          className="ai-readiness-external-disclosure"
          role="note"
          tone="warning"
        >
          {t("setup.aiAccess.external.disclosure")}
        </NoticeBanner>
      )}
    </div>
  );

  const availabilityNotice = readinessChecked &&
    !selectedSourceReady &&
    !selectedIntegratedAIStartable && (
      <NoticeBanner className="setup-ai-notice" role="alert" tone="warning">
        {anyAIReady
          ? t("setup.aiAccess.sourceNotConfigured", { source: sourceLabel })
          : t("setup.aiAccess.noUsableSource")}
      </NoticeBanner>
    );

  return (
    <section className="ai-readiness" aria-labelledby="ai-readiness-title">
      <div className="ai-readiness-title-row">
        <div>
          <p className="ai-readiness-eyebrow">{t("setup.aiAccess.eyebrow")}</p>
          <h2 id="ai-readiness-title">{t("setup.aiAccess.title")}</h2>
        </div>
      </div>
      {sourceChooser}
      {availabilityNotice}
    </section>
  );
};

export default AIReadinessIndicator;
