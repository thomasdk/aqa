/* eslint-disable jsx-a11y-x/no-noninteractive-tabindex -- Named overflow regions need keyboard scrolling. */
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Card, PageHeader, SectionHeader, Select } from "./design-system";
import { ApiError, getSessionTypes } from "../api";
import {
  getPromptPreview,
  listPreviewTemplates,
  type PreviewTemplate,
  type PromptPreviewResult,
} from "../api/preview";
import { formatNumber } from "../i18n";
import type { SessionType } from "./types";
import NoticeBanner from "./NoticeBanner";

type PerspectiveMode = "single" | "multiple";
type Round = "first_round" | "continuation";
type AnswerMode = "independent" | "sequential";

function scenarioFor(round: Round, answerMode: AnswerMode): string {
  return answerMode === "sequential" ? `${round}_sequential` : round;
}

const PromptPreview = () => {
  const { t } = useTranslation();
  const [templates, setTemplates] = useState<PreviewTemplate[]>([]);
  const [sessionTypes, setSessionTypes] = useState<SessionType[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selectedSessionType, setSelectedSessionType] = useState("");
  const [perspectiveMode, setPerspectiveMode] = useState<PerspectiveMode>("single");
  const [round, setRound] = useState<Round>("first_round");
  const [answerMode, setAnswerMode] = useState<AnswerMode>("independent");
  const [preview, setPreview] = useState<PromptPreviewResult | null>(null);
  const [loadingMetadata, setLoadingMetadata] = useState(true);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorSource, setErrorSource] = useState<"metadata" | "preview" | null>(null);

  const selectionRef = useRef({ id: selectedId, sessionType: selectedSessionType });
  const metadataRequestRef = useRef(0);
  const previewRequestRef = useRef(0);
  const metadataAbortRef = useRef<AbortController | null>(null);
  const previewAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    selectionRef.current = { id: selectedId, sessionType: selectedSessionType };
  }, [selectedId, selectedSessionType]);

  const refreshMetadata = useCallback(async () => {
    const requestId = ++metadataRequestRef.current;
    metadataAbortRef.current?.abort();
    const controller = new AbortController();
    metadataAbortRef.current = controller;
    setLoadingMetadata(true);
    setError(null);
    setErrorSource(null);

    try {
      const [availableTemplates, availableSessionTypes] = await Promise.all([
        listPreviewTemplates(controller.signal),
        getSessionTypes(controller.signal),
      ]);
      if (metadataRequestRef.current !== requestId) return;

      setTemplates(availableTemplates);
      setSessionTypes(availableSessionTypes);
      const current = selectionRef.current;
      setSelectedId(
        availableTemplates.some((template) => template.id === current.id)
          ? current.id
          : (availableTemplates[0]?.id ?? ""),
      );
      setSelectedSessionType(
        availableSessionTypes.some((session) => session.key === current.sessionType)
          ? current.sessionType
          : (availableSessionTypes[0]?.key ?? ""),
      );
    } catch (cause) {
      if (metadataRequestRef.current !== requestId) return;
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setError(t("prompts.metadataLoadError"));
      setErrorSource("metadata");
    } finally {
      if (metadataRequestRef.current === requestId) setLoadingMetadata(false);
    }
  }, [t]);

  useEffect(() => {
    void refreshMetadata();
  }, [refreshMetadata]);

  const multiAgent = perspectiveMode === "multiple";
  const effectiveAnswerMode: AnswerMode = multiAgent ? answerMode : "independent";
  const scenario = scenarioFor(round, effectiveAnswerMode);

  const loadPreview = useCallback(async () => {
    const requestId = ++previewRequestRef.current;
    previewAbortRef.current?.abort();
    if (!selectedId) {
      setPreview(null);
      setLoadingPreview(false);
      return;
    }

    const controller = new AbortController();
    previewAbortRef.current = controller;
    setPreview(null);
    setLoadingPreview(true);
    setError(null);
    setErrorSource(null);
    try {
      const result = await getPromptPreview(
        selectedId,
        multiAgent,
        selectedSessionType,
        scenario,
        controller.signal,
      );
      if (previewRequestRef.current === requestId) setPreview(result);
    } catch (cause) {
      if (previewRequestRef.current !== requestId) return;
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setError(
        cause instanceof ApiError ? t("prompts.templateLoadError") : t("prompts.backendError"),
      );
      setErrorSource("preview");
    } finally {
      if (previewRequestRef.current === requestId) setLoadingPreview(false);
    }
  }, [multiAgent, scenario, selectedId, selectedSessionType, t]);

  useEffect(() => {
    void loadPreview();
  }, [loadPreview]);

  useEffect(
    () => () => {
      metadataAbortRef.current?.abort();
      previewAbortRef.current?.abort();
    },
    [],
  );

  const isLoading = loadingMetadata || loadingPreview;

  return (
    <div className="preview-container" aria-busy={isLoading}>
      <PageHeader
        className="preview-header"
        title={t("nav.preview")}
        subtitle={t("prompts.previewSubtitle")}
      />

      <Card className="preview-setup-card" role="region" aria-labelledby="preview-setup-title">
        <SectionHeader
          className="preview-card-heading"
          titleId="preview-setup-title"
          title={t("prompts.previewSetup")}
        />
        <div className="preview-controls">
          <div className="preview-control-group">
            <label htmlFor="template-select">{t("prompts.perspective")}</label>
            <Select
              id="template-select"
              value={selectedId}
              onChange={(event) => setSelectedId(event.target.value)}
              disabled={loadingMetadata || templates.length === 0}
            >
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.label}
                </option>
              ))}
            </Select>
          </div>

          <div className="preview-control-group">
            <label htmlFor="preview-session-type">{t("setup.sessionType")}</label>
            <Select
              id="preview-session-type"
              value={selectedSessionType}
              onChange={(event) => setSelectedSessionType(event.target.value)}
              disabled={loadingMetadata || sessionTypes.length === 0}
            >
              {sessionTypes.map((session) => (
                <option key={session.key} value={session.key}>
                  {session.label}
                </option>
              ))}
            </Select>
          </div>

          <div className="preview-control-group">
            <label htmlFor="preview-perspectives">{t("setup.agents")}</label>
            <Select
              id="preview-perspectives"
              value={perspectiveMode}
              onChange={(event) => {
                const mode = event.target.value as PerspectiveMode;
                setPerspectiveMode(mode);
                setAnswerMode(mode === "multiple" ? "sequential" : "independent");
              }}
            >
              <option value="single">{t("prompts.singleAgent")}</option>
              <option value="multiple">{t("prompts.multiAgentLabel")}</option>
            </Select>
          </div>

          <div className="preview-control-group">
            <label htmlFor="preview-round">{t("prompts.round")}</label>
            <Select
              id="preview-round"
              value={round}
              onChange={(event) => setRound(event.target.value as Round)}
            >
              <option value="first_round">{t("prompts.previewScenarioFirstRound")}</option>
              <option value="continuation">{t("prompts.previewScenarioContinuation")}</option>
            </Select>
          </div>

          <div className="preview-control-group">
            <label htmlFor="preview-answer-mode">{t("setup.answerMode")}</label>
            <Select
              id="preview-answer-mode"
              value={effectiveAnswerMode}
              onChange={(event) => setAnswerMode(event.target.value as AnswerMode)}
              disabled={!multiAgent}
              aria-describedby={!multiAgent ? "preview-answer-mode-help" : undefined}
            >
              <option value="independent">{t("setup.independent")}</option>
              <option value="sequential">{t("setup.sequential")}</option>
            </Select>
            {!multiAgent && (
              <span id="preview-answer-mode-help" className="preview-control-help">
                {t("prompts.answerModeSinglePerspectiveHelp")}
              </span>
            )}
          </div>
        </div>

        {preview && (
          <div className="preview-metrics" aria-label={t("prompts.previewMetrics")}>
            <span className="preview-metric">
              <strong>{formatNumber(preview.char_count)}</strong> {t("prompts.characters")}
            </span>
            <span className="preview-metric">
              {preview.estimated_tokens === null ? (
                t("prompts.tokenEstimateUnavailable")
              ) : (
                <>
                  {t("prompts.estimatedTokens", {
                    count: formatNumber(preview.estimated_tokens),
                  })}
                </>
              )}
            </span>
          </div>
        )}
      </Card>

      {error && (
        <NoticeBanner className="preview-error" tone="error" onDismiss={() => setError(null)}>
          <span>{error}</span>
          <Button
            variant="secondary"
            size="small"
            onClick={() => void (errorSource === "metadata" ? refreshMetadata() : loadPreview())}
          >
            {t("prompts.retryPreview")}
          </Button>
        </NoticeBanner>
      )}

      {loadingPreview && (
        <p className="preview-loading" role="status" aria-live="polite">
          {t("prompts.loadingPreview")}
        </p>
      )}

      {preview && (
        <section className="preview-message-stack" aria-label={t("prompts.requestMessages")}>
          {round === "continuation" && (
            <p className="preview-control-help">{t("prompts.previewResearcherNoteCondition")}</p>
          )}
          <article className="preview-message-card">
            <header className="preview-card-heading">
              <h2>{t("prompts.fullPrompt")}</h2>
            </header>
            {/* Long prompts scroll locally and must accept keyboard focus. */}
            {/* eslint-disable-next-line jsx-a11y-x/no-noninteractive-tabindex */}
            <pre className="preview-prompt-text" tabIndex={0} aria-label={t("prompts.fullPrompt")}>
              {preview.system_prompt}
            </pre>
          </article>
          <article className="preview-message-card">
            <header className="preview-card-heading">
              <h2>{t("prompts.fullUserPrompt")}</h2>
            </header>
            {/* eslint-disable-next-line jsx-a11y-x/no-noninteractive-tabindex */}
            <pre
              className="preview-prompt-text"
              tabIndex={0}
              aria-label={t("prompts.fullUserPrompt")}
            >
              {preview.user_prompt}
            </pre>
          </article>
        </section>
      )}
    </div>
  );
};

export default PromptPreview;
