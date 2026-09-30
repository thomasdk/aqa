import {
  useState,
  useEffect,
  useCallback,
  useRef,
  type Dispatch,
  type MouseEvent,
  type ReactNode,
  type SetStateAction,
} from "react";
import { useTranslation } from "react-i18next";
import { translateErrorCode } from "../i18n";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import MaterialSymbol from "./MaterialSymbol";
import type { DiscussionMessage, AgentConfig } from "./types";
import { ActionGroup, Button, Textarea } from "./design-system";

/**
 * Make material line references readable even when a model omits the requested
 * Markdown backticks. Existing inline/fenced code is left untouched.
 */
const formatMaterialLineReferences = (text: string): string =>
  text
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part, index) => {
      if (index % 2 === 1) return part;
      const lineReferences = part.replace(
        /(^|[^\w`])(Z\d{4}(?:[-\u2010\u2011\u2013\u2014]Z\d{4})?)(?![\w`])/g,
        (_match, prefix: string, reference: string) =>
          `${prefix}\`${reference.replace(/[\u2010\u2011\u2013\u2014]/g, "-")}\``,
      );
      return lineReferences.replace(/(^|[^\w`])(Perspective\s+\d+)(?![\w`])/g, "$1`$2`");
    })
    .join("");

/**
 * Keep model output on react-markdown's safe path: raw HTML remains disabled
 * and links use its URL sanitizer.
 */
const renderMarkdownContent = (text: string): ReactNode => (
  <ReactMarkdown
    remarkPlugins={[remarkGfm]}
    components={{
      a: ({ node: _node, children, ...props }) => (
        <a {...props} target="_blank" rel="noopener noreferrer">
          {children}
        </a>
      ),
    }}
  >
    {formatMaterialLineReferences(text)}
  </ReactMarkdown>
);

export type StreamingAgent = {
  message_id: string;
  agent_index: number;
  agent_name: string;
  client_id: string;
  perspective_number: number;
  theory_label: string;
  color: string;
  text: string;
  is_complete: boolean;
  status?: "in_progress" | "completed" | "interrupted" | "failed" | null;
  error: string | null;
  error_code?: string | null;
  error_params?: Record<string, unknown>;
};

/** A temporary synthesis card; deliberately separate from the agent stream. */
export type StreamingSynthesis = {
  message_id: string;
  round_number: number;
  text: string;
  error: string | null;
  error_code?: string | null;
  status?: "in_progress" | "completed" | "interrupted" | "failed" | null;
  error_params?: Record<string, unknown>;
};

export type QuickAction = {
  id: string;
  label: string;
  prompt: string;
  origin?: string;
};

const SHIPPED_QUICK_ACTION_KEYS = {
  debate: "quickDebate",
  deepen: "quickDeepen",
  challenge: "quickChallenge",
  focus: "quickFocus",
  explore: "quickExplore",
} as const;

type Props = {
  messages: DiscussionMessage[];
  streamingAgents: StreamingAgent[];
  streamingSynthesis?: StreamingSynthesis | null;
  isStreaming: boolean;
  isSynthesisSaving?: boolean;
  isContinuePending?: boolean;
  /** Optional controlled draft keeps a follow-up intact while recovery opens another view. */
  followUpDraft?: string;
  onFollowUpDraftChange?: Dispatch<SetStateAction<string>>;
  currentAgents?: AgentConfig[];
  usesIntegratedAI?: boolean;
  independentAnswers?: boolean;
  /** Global System-configured actions. They are intentionally not session state. */
  quickActions?: readonly QuickAction[];
  onContinue: (
    userInput: string,
    focusSegment: string | null,
    targetMessageId: string | null,
  ) => void | Promise<void | boolean>;
  onSetNote: (messageId: string, note: string, includeInAgentContext: boolean) => void;
  /** Layout persists this optimistic update and recovers from conflicts. */
  onSetContextInclusion: (messageId: string, include: boolean) => void;
  isContextInclusionSaving?: boolean;
};

function formatMessageAsFollowupContext(
  translate: (key: string, params: Record<string, string | number>) => string,
  content: string,
  perspectiveNumber: number | null | undefined,
  maxChars = 1600,
): string {
  let text = (content || "").trim();
  if (text.length > maxChars) {
    text = text.slice(0, maxChars).trimEnd() + "\n[... truncated ...]";
  }
  const quotedText = text
    .split("\n")
    .map((line) => `> ${line}`)
    .join("\n");
  return translate("discussion.referenceFollowupContext", {
    perspective: perspectiveNumber ?? "?",
    content: quotedText,
  });
}

const DiscussionView = ({
  messages,
  streamingAgents,
  streamingSynthesis = null,
  isStreaming,
  isSynthesisSaving = false,
  isContinuePending = false,
  followUpDraft,
  onFollowUpDraftChange,
  usesIntegratedAI = false,
  independentAnswers = false,
  quickActions = [],
  onContinue,
  onSetNote,
  onSetContextInclusion,
  isContextInclusionSaving = false,
}: Props) => {
  const { t } = useTranslation();
  const visibleQuickActions = quickActions.map((action) => {
    const keys =
      action.origin === "shipped_default"
        ? SHIPPED_QUICK_ACTION_KEYS[action.id as keyof typeof SHIPPED_QUICK_ACTION_KEYS]
        : undefined;
    return keys ? { ...action, label: t(`discussion.${keys}`) } : action;
  });
  const [localFollowUp, setLocalFollowUp] = useState("");
  const followUp = followUpDraft ?? localFollowUp;
  const setFollowUp = onFollowUpDraftChange ?? setLocalFollowUp;
  const [editingNoteFor, setEditingNoteFor] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [includeNoteDraft, setIncludeNoteDraft] = useState(false);
  const [recentlyArrived, setRecentlyArrived] = useState<Set<string>>(new Set());
  const [statusAnnouncement, setStatusAnnouncement] = useState({ id: 0, text: "" });
  const [alertAnnouncement, setAlertAnnouncement] = useState({ id: 0, text: "" });
  const noteTriggerRefs = useRef(new Map<string, HTMLElement>());
  const noteEditorRef = useRef<HTMLTextAreaElement>(null);
  const pendingNoteFocusRef = useRef<string | null>(null);
  const previousStreamingRef = useRef(isStreaming);
  const previousAgentStatesRef = useRef(
    new Map(
      streamingAgents.map((agent) => [
        agent.message_id,
        { complete: agent.is_complete, status: agent.status, error: agent.error },
      ]),
    ),
  );
  const previousSynthesisRef = useRef(streamingSynthesis);
  const encounteredLiveErrorRef = useRef(false);
  const previousItemCountRef = useRef(
    messages.length + streamingAgents.length + Number(Boolean(streamingSynthesis)),
  );
  const lastRound = messages.length ? Math.max(...messages.map((m) => m.round_number)) : 0;
  const lastRoundErrors = messages.filter(
    (m) =>
      m.round_number === lastRound &&
      m.status !== "interrupted" &&
      (Boolean(m.error || m.error_code) || m.status === "failed"),
  );
  const lastRoundHasErrors = lastRoundErrors.length > 0;
  const lastRoundOnlyHasContextLimitErrors =
    lastRoundHasErrors &&
    lastRoundErrors.every((message) => message.error_code === "context_limit_exceeded");
  const lastRoundHasMixedContextErrors =
    lastRoundErrors.some((message) => message.error_code === "context_limit_exceeded") &&
    !lastRoundOnlyHasContextLimitErrors;

  useEffect(() => {
    if (messages.length === 0) return;
    const lastId = messages[messages.length - 1].id;
    setRecentlyArrived((prev) => {
      if (prev.has(lastId)) return prev;
      const next = new Set(prev);
      next.add(lastId);
      return next;
    });
    const t = setTimeout(() => {
      setRecentlyArrived((prev) => {
        const next = new Set(prev);
        next.delete(lastId);
        return next;
      });
    }, 800);
    return () => clearTimeout(t);
  }, [messages]);

  const announceStatus = useCallback((text: string) => {
    setStatusAnnouncement((previous) => ({ id: previous.id + 1, text }));
  }, []);

  const announceAlert = useCallback((text: string) => {
    setAlertAnnouncement((previous) => ({ id: previous.id + 1, text }));
  }, []);

  useEffect(() => {
    const wasStreaming = previousStreamingRef.current;
    const previousAgents = previousAgentStatesRef.current;
    const previousSynthesis = previousSynthesisRef.current;
    const completedAgents = streamingAgents.filter((agent) => {
      const previous = previousAgents.get(agent.message_id);
      const complete = agent.is_complete || agent.status === "completed";
      return Boolean(
        complete &&
        (previous ? !previous.complete && previous.status !== "completed" : wasStreaming),
      );
    });
    const newAgentErrors = streamingAgents.filter((agent) => {
      const previous = previousAgents.get(agent.message_id);
      return Boolean(agent.error && (previous ? !previous.error : wasStreaming));
    });
    const synthesisStarted = !previousSynthesis && Boolean(streamingSynthesis);
    const synthesisCompleted = Boolean(
      previousSynthesis &&
      previousSynthesis.status !== "completed" &&
      streamingSynthesis?.status === "completed",
    );
    const synthesisFailed = Boolean(streamingSynthesis?.error && !previousSynthesis?.error);

    if (!wasStreaming && isStreaming) {
      encounteredLiveErrorRef.current = false;
      setAlertAnnouncement((previous) => ({ id: previous.id + 1, text: "" }));
      announceStatus(t("discussion.generationStartedStatus"));
    } else if (completedAgents.length > 0) {
      announceStatus(
        completedAgents
          .map((agent) =>
            t("discussion.perspectiveCompletedStatus", {
              number: agent.perspective_number,
              label: agent.theory_label,
            }),
          )
          .join(" "),
      );
    } else if (synthesisStarted) {
      announceStatus(t("discussion.synthesisStartedStatus"));
    } else if (synthesisCompleted) {
      announceStatus(t("discussion.synthesisCompletedStatus"));
    }

    if (newAgentErrors.length > 0) {
      encounteredLiveErrorRef.current = true;
      announceAlert(
        newAgentErrors
          .map((agent) =>
            t("discussion.perspectiveFailedAlert", {
              number: agent.perspective_number,
              label: agent.theory_label,
            }),
          )
          .join(" "),
      );
    } else if (synthesisFailed) {
      encounteredLiveErrorRef.current = true;
      announceAlert(t("discussion.synthesisFailedAlert"));
    }

    if (wasStreaming && !isStreaming) {
      const latestRound = messages.length
        ? Math.max(...messages.map((message) => message.round_number))
        : 0;
      const latestMessages = messages.filter((message) => message.round_number === latestRound);
      if (latestMessages.some((message) => message.status === "interrupted")) {
        announceStatus(t("discussion.generationInterruptedStatus"));
      } else if (
        latestMessages.some(
          (message) => message.status === "failed" || message.error || message.error_code,
        )
      ) {
        announceStatus(t("discussion.generationFailedStatus"));
        if (!encounteredLiveErrorRef.current) {
          announceAlert(t("discussion.generationFailedAlert"));
        }
      } else {
        announceStatus(t("discussion.generationCompletedStatus"));
      }
    }

    const itemCount =
      messages.length + streamingAgents.length + Number(Boolean(streamingSynthesis));
    if (!wasStreaming && previousItemCountRef.current > 0 && itemCount === 0 && !isStreaming) {
      announceStatus(t("discussion.empty"));
    }

    previousStreamingRef.current = isStreaming;
    previousAgentStatesRef.current = new Map(
      streamingAgents.map((agent) => [
        agent.message_id,
        { complete: agent.is_complete, status: agent.status, error: agent.error },
      ]),
    );
    previousSynthesisRef.current = streamingSynthesis;
    previousItemCountRef.current = itemCount;
  }, [
    announceAlert,
    announceStatus,
    isStreaming,
    messages,
    streamingAgents,
    streamingSynthesis,
    t,
  ]);

  useEffect(() => {
    if (editingNoteFor) {
      noteEditorRef.current?.focus();
      return;
    }
    const messageId = pendingNoteFocusRef.current;
    if (!messageId) return;
    pendingNoteFocusRef.current = null;
    noteTriggerRefs.current.get(messageId)?.focus();
  }, [editingNoteFor, messages]);

  const handleSubmit = async () => {
    if (isSynthesisSaving || isContinuePending) return;
    const accepted = await onContinue(followUp, null, null);
    if (accepted !== false) setFollowUp("");
  };

  const startEditNote = (msg: DiscussionMessage) => {
    setEditingNoteFor(msg.id);
    setNoteDraft(msg.note || "");
    setIncludeNoteDraft(Boolean(msg.include_note_in_agent_context));
  };

  const saveNote = (messageId: string) => {
    const normalizedNote = noteDraft.trim();
    const hasNote = normalizedNote.length > 0;
    const message = messages.find((candidate) => candidate.id === messageId);
    onSetNote(
      messageId,
      normalizedNote,
      hasNote && includeNoteDraft && Boolean(message?.include_in_agent_context),
    );
    pendingNoteFocusRef.current = messageId;
    setEditingNoteFor(null);
    setNoteDraft("");
    setIncludeNoteDraft(false);
  };

  const cancelNoteEdit = (messageId: string) => {
    pendingNoteFocusRef.current = messageId;
    setEditingNoteFor(null);
    setNoteDraft("");
    setIncludeNoteDraft(false);
  };

  const handleUseAsReference = (event: MouseEvent<HTMLButtonElement>, msg: DiscussionMessage) => {
    const messageElement = event.currentTarget.closest(".discussion-message");
    const messageContent = messageElement?.querySelector(".message-content");
    const selection = window.getSelection();
    const hasContainedSelection =
      selection &&
      !selection.isCollapsed &&
      selection.toString().trim().length > 0 &&
      messageContent &&
      selection.anchorNode &&
      selection.focusNode &&
      messageContent.contains(selection.anchorNode) &&
      messageContent.contains(selection.focusNode);
    const referencedContent = hasContainedSelection ? selection.toString() : msg.content;
    const followupText = formatMessageAsFollowupContext(
      t,
      referencedContent,
      msg.perspective_number,
    );
    setFollowUp((previous) => (previous ? `${previous}\n\n${followupText}` : followupText));
    announceStatus(t("discussion.referenceAddedStatus"));
    const followupArea = document.querySelector(".followup-area");
    if (followupArea && typeof followupArea.scrollIntoView === "function") {
      followupArea.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  const insertQuickAction = (action: QuickAction) => {
    setFollowUp((previous) => (previous ? `${previous}\n\n${action.prompt}` : action.prompt));
    announceStatus(t("discussion.quickActionInsertedStatus", { label: action.label }));
  };

  const allItems = [
    ...messages.map((m) => ({ type: "message" as const, data: m })),
    ...streamingAgents.map((a) => ({ type: "streaming" as const, data: a })),
    ...(streamingSynthesis
      ? [{ type: "streaming-synthesis" as const, data: streamingSynthesis }]
      : []),
  ];

  // Only idle messages from the latest round can change context inclusion.
  const persistedMessages = messages;
  const latestRound = persistedMessages.length
    ? Math.max(...persistedMessages.map((m) => m.round_number))
    : 0;
  const isContextEditable = (msg: DiscussionMessage): boolean =>
    !isStreaming && msg.round_number === latestRound;
  const isContextLocked = (msg: DiscussionMessage): boolean =>
    !isStreaming && persistedMessages.length > 0 && msg.round_number < latestRound;
  const contextIncludedLabel = t("discussion.included");
  const contextExcludedLabel = t("discussion.excluded");
  return (
    <div className={`discussion-view${allItems.length > 0 ? " has-discussion-content" : ""}`}>
      <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        <span key={statusAnnouncement.id}>{statusAnnouncement.text}</span>
      </div>
      <div className="visually-hidden" role="alert" aria-atomic="true">
        <span key={alertAnnouncement.id}>{alertAnnouncement.text}</span>
      </div>
      {independentAnswers && (
        <aside
          className="discussion-mode-notice"
          role="note"
          aria-labelledby="discussion-independent-answers-title"
        >
          <MaterialSymbol name="help" decorative />
          <div>
            <strong id="discussion-independent-answers-title">
              {t("discussion.independentAnswersTitle")}
            </strong>
            <p>{t("discussion.independentAnswersBody")}</p>
          </div>
        </aside>
      )}
      <div className="discussion-messages">
        {allItems.length === 0 && !isStreaming && (
          <div className="discussion-empty">{t("discussion.empty")}</div>
        )}
        {allItems.map((item) => {
          if (item.type === "message") {
            const msg = item.data;
            const isAgent = msg.role === "agent";
            const isSynthesis = msg.role === "synthesis";
            const isContextLimitError = msg.error_code === "context_limit_exceeded";
            // Synthesis is deliberately excluded from later perspective
            // context internally, but is not a user-excluded message and
            // must retain its dedicated synthesis appearance.
            const isExcluded = !isSynthesis && !msg.include_in_agent_context;
            const isLatestEditable = isContextEditable(msg);
            const isOlderLocked = isContextLocked(msg);
            // Preserve the same visible and accessible state label across editable and locked rounds.
            const stateLabel = isExcluded ? contextExcludedLabel : contextIncludedLabel;
            const messageClasses = [
              "discussion-message",
              `message-${msg.role}`,
              isExcluded ? "is-excluded-from-context" : "",
              recentlyArrived.has(msg.id) ? "is-just-arrived" : "",
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <div
                key={msg.id}
                className={messageClasses}
                style={isAgent && msg.color ? { borderLeft: `3px solid ${msg.color}` } : {}}
              >
                <div className="message-meta">
                  <span className="message-sender">
                    {msg.role === "user" ? (
                      t("discussion.moderator")
                    ) : isSynthesis ? (
                      <>
                        <MaterialSymbol name="account_tree" decorative />{" "}
                        {t("discussion.synthesisRound", { count: msg.round_number })}
                      </>
                    ) : isAgent ? (
                      `${t("setup.perspectiveSlot", { number: msg.perspective_number })}: ${
                        msg.theory_label || t("setup.choosePerspective")
                      }`
                    ) : null}
                  </span>
                  {!isSynthesis && (
                    <span className="message-round">
                      {t("discussion.round", { count: msg.round_number })}
                    </span>
                  )}
                </div>
                {(msg.content || (!msg.error && !msg.error_code)) && (
                  <div className="message-content md-content">
                    {renderMarkdownContent(
                      isAgent || isSynthesis
                        ? msg.content || t("discussion.emptyResponse")
                        : msg.content,
                    )}
                  </div>
                )}
                {msg.status && msg.status !== "completed" && (
                  <div className="message-status">
                    {msg.status === "interrupted"
                      ? t("discussion.roundInterrupted")
                      : msg.status === "failed"
                        ? t("discussion.roundFailed")
                        : t("discussion.roundInProgress")}
                  </div>
                )}
                {msg.status !== "interrupted" && (msg.error || msg.error_code) && (
                  <div className="message-error">
                    <strong>
                      <MaterialSymbol name="warning" decorative />{" "}
                      {t(isSynthesis ? "discussion.synthesisError" : "discussion.agentError")}
                    </strong>{" "}
                    {translateErrorCode(msg.error_code, msg.error_params)}
                    <div className="message-error-hint">
                      {t(
                        isContextLimitError
                          ? usesIntegratedAI
                            ? "discussion.integratedContextLimitErrorHint"
                            : "discussion.externalContextLimitErrorHint"
                          : isSynthesis
                            ? "discussion.synthesisErrorHint"
                            : usesIntegratedAI
                              ? "discussion.integratedErrorHint"
                              : "discussion.errorHint",
                      )}
                    </div>
                    {msg.error && msg.error !== msg.error_code && (
                      <details>
                        <summary>{t("common.technicalDetails")}</summary>
                        <code>{msg.error}</code>
                      </details>
                    )}
                  </div>
                )}

                {isAgent && !isStreaming && (
                  <div className="message-footer">
                    <div className="message-note-area message-footer-item">
                      {editingNoteFor === msg.id ? (
                        <div className="note-editor">
                          <Textarea
                            id={`discussion-note-${msg.id}`}
                            ref={noteEditorRef}
                            value={noteDraft}
                            onChange={(e) => setNoteDraft(e.target.value)}
                            placeholder={t("discussion.notePlaceholder")}
                            rows={2}
                          />
                          <label className="visually-hidden" htmlFor={`discussion-note-${msg.id}`}>
                            {t("discussion.editNote")}
                          </label>
                          <div className="note-editor-context">
                            <label className="checkbox note-context-checkbox">
                              <input
                                type="checkbox"
                                checked={includeNoteDraft}
                                disabled={!msg.include_in_agent_context || !noteDraft.trim()}
                                onChange={(event) => setIncludeNoteDraft(event.target.checked)}
                                aria-label={
                                  includeNoteDraft ? contextIncludedLabel : contextExcludedLabel
                                }
                              />
                              <span
                                className={`message-context-badge ${
                                  includeNoteDraft
                                    ? "message-context-badge--included"
                                    : "message-context-badge--excluded"
                                }`}
                              >
                                {includeNoteDraft ? contextIncludedLabel : contextExcludedLabel}
                              </span>
                            </label>
                          </div>
                          <ActionGroup className="note-editor-actions" align="start">
                            <Button variant="secondary" onClick={() => saveNote(msg.id)}>
                              {t("common.save")}
                            </Button>
                            <Button variant="secondary" onClick={() => cancelNoteEdit(msg.id)}>
                              {t("common.cancel")}
                            </Button>
                          </ActionGroup>
                        </div>
                      ) : msg.note ? (
                        <div
                          className="message-note"
                          role="button"
                          tabIndex={0}
                          onClick={() => startEditNote(msg)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              startEditNote(msg);
                            }
                          }}
                          title={t("discussion.clickToEdit")}
                          aria-label={
                            msg.include_note_in_agent_context
                              ? `${msg.note} (${t("discussion.noteIncluded")})`
                              : msg.note
                          }
                          ref={(element) => {
                            if (element) noteTriggerRefs.current.set(msg.id, element);
                            else noteTriggerRefs.current.delete(msg.id);
                          }}
                        >
                          <span className="message-note-content">
                            <MaterialSymbol name="edit" decorative /> {msg.note}
                          </span>
                          {msg.include_note_in_agent_context && (
                            <span
                              className="message-note-context-state message-context-badge message-context-badge--included is-included"
                              data-context-state="included"
                            >
                              {contextIncludedLabel}
                            </span>
                          )}
                        </div>
                      ) : (
                        <Button
                          variant="secondary"
                          className="note-add-btn"
                          onClick={() => startEditNote(msg)}
                          ref={(element) => {
                            if (element) noteTriggerRefs.current.set(msg.id, element);
                            else noteTriggerRefs.current.delete(msg.id);
                          }}
                        >
                          <MaterialSymbol name="edit" decorative />
                          {t("discussion.addNote")}
                        </Button>
                      )}
                    </div>

                    {!msg.error && !msg.error_code && (
                      <button
                        type="button"
                        className="message-bezugspunkt-btn message-footer-item"
                        onClick={(event) => handleUseAsReference(event, msg)}
                        title={t("discussion.useReference")}
                      >
                        <MaterialSymbol
                          name="south_east"
                          decorative
                          className="message-bezugspunkt-icon"
                        />
                        <span className="message-bezugspunkt-label">
                          {t("discussion.reference")}
                        </span>
                      </button>
                    )}

                    {!isSynthesis && isLatestEditable && (
                      <div className="message-context-row message-footer-item">
                        <label
                          className={`checkbox message-context-checkbox${isExcluded ? " is-excluded" : " is-included"}`}
                        >
                          <input
                            type="checkbox"
                            checked={msg.include_in_agent_context}
                            disabled={isContextInclusionSaving}
                            onChange={(event) =>
                              onSetContextInclusion(msg.id, event.target.checked)
                            }
                            aria-label={stateLabel}
                          />
                          <span
                            className={
                              isExcluded
                                ? "message-context-state message-context-state--excluded"
                                : "message-context-state message-context-state--included"
                            }
                          >
                            <span
                              className={`message-context-badge ${
                                isExcluded
                                  ? "message-context-badge--excluded"
                                  : "message-context-badge--included"
                              }`}
                            >
                              {stateLabel}
                            </span>
                          </span>
                        </label>
                      </div>
                    )}
                    {!isSynthesis && isOlderLocked && (
                      <div className="message-context-row message-footer-item message-context-row--locked">
                        <span
                          className={
                            isExcluded
                              ? "message-context-state message-context-state--excluded"
                              : "message-context-state message-context-state--included"
                          }
                        >
                          <span
                            className={`message-context-badge ${
                              isExcluded
                                ? "message-context-badge--excluded"
                                : "message-context-badge--included"
                            }`}
                          >
                            {stateLabel}
                          </span>
                        </span>
                      </div>
                    )}
                  </div>
                )}

                {!isSynthesis && !isAgent && isLatestEditable && (
                  <div className="message-context-row message-footer-item">
                    <label
                      className={`checkbox message-context-checkbox${isExcluded ? " is-excluded" : " is-included"}`}
                    >
                      <input
                        type="checkbox"
                        checked={msg.include_in_agent_context}
                        disabled={isContextInclusionSaving}
                        onChange={(event) => onSetContextInclusion(msg.id, event.target.checked)}
                        aria-label={stateLabel}
                      />
                      <span
                        className={
                          isExcluded
                            ? "message-context-state message-context-state--excluded"
                            : "message-context-state message-context-state--included"
                        }
                      >
                        <span
                          className={`message-context-badge ${
                            isExcluded
                              ? "message-context-badge--excluded"
                              : "message-context-badge--included"
                          }`}
                        >
                          {stateLabel}
                        </span>
                      </span>
                    </label>
                  </div>
                )}
                {!isSynthesis && !isAgent && isOlderLocked && (
                  <div className="message-context-row message-footer-item message-context-row--locked">
                    <span
                      className={
                        isExcluded
                          ? "message-context-state message-context-state--excluded"
                          : "message-context-state message-context-state--included"
                      }
                    >
                      <span
                        className={`message-context-badge ${
                          isExcluded
                            ? "message-context-badge--excluded"
                            : "message-context-badge--included"
                        }`}
                      >
                        {stateLabel}
                      </span>
                    </span>
                  </div>
                )}
              </div>
            );
          }
          if (item.type === "streaming-synthesis") {
            const synthesis = item.data;
            return (
              <div
                key={`streaming-synthesis-${synthesis.message_id}`}
                className="discussion-message message-synthesis streaming"
              >
                <div className="message-meta">
                  <span className="message-sender">
                    <MaterialSymbol name="account_tree" decorative />{" "}
                    {t("discussion.synthesisRound", { count: synthesis.round_number })}
                  </span>
                </div>
                <div className="message-content md-content">
                  {renderMarkdownContent(synthesis.text)}
                  <span className="streaming-caret" aria-hidden="true" />
                </div>
                {synthesis.status && synthesis.status !== "completed" && (
                  <div className="message-status">
                    {synthesis.status === "interrupted"
                      ? t("discussion.roundInterrupted")
                      : synthesis.status === "failed"
                        ? t("discussion.roundFailed")
                        : t("discussion.roundInProgress")}
                  </div>
                )}
                {synthesis.status !== "interrupted" &&
                  (synthesis.error || synthesis.error_code) && (
                    <div className="message-error">
                      <strong>
                        <MaterialSymbol name="warning" decorative />{" "}
                        {t("discussion.synthesisError")}
                      </strong>{" "}
                      {translateErrorCode(synthesis.error_code, synthesis.error_params)}
                      {synthesis.error && synthesis.error !== synthesis.error_code && (
                        <details>
                          <summary>{t("common.technicalDetails")}</summary>
                          <code>{synthesis.error}</code>
                        </details>
                      )}
                    </div>
                  )}
              </div>
            );
          }
          const agent = item.data;
          return (
            <div
              key={`streaming-${agent.message_id}`}
              className="discussion-message message-agent streaming"
              style={{ borderLeft: `3px solid ${agent.color}` }}
            >
              <div className="message-meta">
                <span className="message-sender">
                  {`${t("setup.perspectiveSlot", { number: agent.perspective_number })}: ${
                    agent.theory_label
                  }`}
                </span>
              </div>
              <div className="message-content md-content">
                {renderMarkdownContent(agent.text)}
                {!agent.is_complete && <span className="streaming-caret" aria-hidden="true" />}
              </div>
              {(agent.error || agent.error_code) && (
                <div className="message-error">
                  <MaterialSymbol name="warning" decorative />{" "}
                  {translateErrorCode(agent.error_code, agent.error_params)}
                  {agent.error && agent.error !== agent.error_code && (
                    <details>
                      <summary>{t("common.technicalDetails")}</summary>
                      <code>{agent.error}</code>
                    </details>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {!isStreaming && messages.length > 0 && (
        <div className="followup-area">
          <aside className="discussion-disclaimer" aria-labelledby="discussion-disclaimer-title">
            <MaterialSymbol name="warning" decorative />
            <div>
              <strong id="discussion-disclaimer-title">{t("discussion.disclaimerTitle")}</strong>
              <p>{t("discussion.disclaimerBody")}</p>
            </div>
          </aside>
          {lastRoundHasErrors && (
            <div className="followup-blocked">
              <strong>{t("discussion.lastRoundFailed")}</strong>{" "}
              {t(
                lastRoundOnlyHasContextLimitErrors
                  ? usesIntegratedAI
                    ? "discussion.integratedContextLimitAgentsReportedError"
                    : "discussion.externalContextLimitAgentsReportedError"
                  : lastRoundHasMixedContextErrors
                    ? "discussion.agentsReportedError"
                    : usesIntegratedAI
                      ? "discussion.integratedAgentsReportedError"
                      : "discussion.agentsReportedError",
              )}
            </div>
          )}
          <div className="quick-prompts">
            <span className="quick-prompts-label">{t("discussion.quickActions")}</span>
            <div className="quick-prompts-controls">
              {visibleQuickActions.map((action) => (
                <button
                  key={action.id}
                  type="button"
                  className="quick-prompt-chip"
                  title={action.prompt}
                  onClick={() => insertQuickAction(action)}
                  disabled={isSynthesisSaving || isContinuePending}
                >
                  {action.label}
                </button>
              ))}
            </div>
          </div>
          <label className="visually-hidden" htmlFor="discussion-follow-up">
            {t("discussion.followupLabel")}
          </label>
          <Textarea
            id="discussion-follow-up"
            value={followUp}
            onChange={(e) => setFollowUp(e.target.value)}
            placeholder={t("discussion.followupPlaceholder")}
            rows={3}
            disabled={isContinuePending}
          />
          <Button
            variant="primary"
            disabled={!followUp.trim() || isSynthesisSaving || isContinuePending}
            onClick={handleSubmit}
          >
            {isContinuePending ? t("localAi.starting") : t("discussion.continueRound")}
          </Button>
        </div>
      )}
    </div>
  );
};

export default DiscussionView;
