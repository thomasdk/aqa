/* eslint-disable jsx-a11y-x/no-noninteractive-tabindex -- Named overflow regions need keyboard scrolling. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import MaterialSymbol from "./MaterialSymbol";
import { IconButton } from "./IconButton";
import { ConfirmDialog, Modal } from "./Modal";
import NoticeBanner from "./NoticeBanner";
import QuickActionsManager from "./QuickActionsManager";
import {
  ActionGroup,
  Button,
  DialogFooter,
  EditorDialogBody,
  EditorDialogError,
  Field,
  Input,
  SectionHeader,
  Textarea,
} from "./design-system";
import { formatPromptScope } from "./promptScope";
import {
  listRoles,
  listPromptSessionTypes,
  createPromptSessionType,
  updatePromptSessionType,
  deletePromptSessionType,
  restoreDefaultPromptSessionType,
  revealPromptSessionTypesDirectory,
  listPromptGlobals,
  updatePromptGlobal,
  restoreDefaultPromptGlobal,
  revealPromptGlobalsDirectory,
  ApiError,
  createQuickAction,
  deleteQuickAction,
  listQuickActions,
  restoreDefaultQuickAction,
  restoreDefaultQuickActions,
  updateQuickAction,
  type SessionTypeCreatePayload,
  type GlobalUpdatePayload,
} from "../api";
import type { Role, SessionTypeDetail, GlobalBlock } from "./types";
import { sessionInputText } from "./sessionInputs";
import { hasNativeManagedPathReveal, revealManagedPath } from "../desktopBridge";
import {
  EMPTY_GLOBAL_FORM,
  EMPTY_SESSION_FORM,
  PROVENANCE_CLASS,
  PROVENANCE_LABEL_KEYS,
  globalFormFromBlock,
  provenanceTitleKey,
  sessionFormFromDetail,
  sessionTypePayloadDiff,
  uniqueOrdered,
  type GlobalFormState,
  type RestoreTarget,
  type SessionTypeFormState,
} from "./promptConfigurationModel";

type PromptConfigurationManagerProps = {
  /** Refresh the parent after persistence; rejection does not roll back saved data. */
  onConfigurationChanged: () => void | Promise<void>;
  /** Preselect a newly created session type after the parent refresh succeeds. */
  onSessionTypeCreated?: (key: string) => void;
  /** Refreshes the discussion's configured Quick Action buttons after an edit. */
  onQuickActionsChanged?: () => void | Promise<void>;
};

const PromptConfigurationManager = ({
  onConfigurationChanged,
  onSessionTypeCreated,
  onQuickActionsChanged,
}: PromptConfigurationManagerProps) => {
  const { t, i18n } = useTranslation();
  const quickActionsApi = useMemo(
    () => ({
      list: listQuickActions,
      create: createQuickAction,
      update: updateQuickAction,
      remove: deleteQuickAction,
      restore: restoreDefaultQuickAction,
      restoreAll: restoreDefaultQuickActions,
      // Quick Actions share the prompt-library directory with global blocks.
      reveal: async () => {
        if (hasNativeManagedPathReveal()) {
          await revealManagedPath("prompt_library");
          return { status: "ok" as const };
        }
        return revealPromptGlobalsDirectory();
      },
    }),
    [],
  );
  const actionError = useCallback(
    (err: unknown, fallbackKey: string, params: Record<string, unknown> = {}): string => {
      if (err instanceof ApiError && err.code) {
        const codeKeys: Record<string, string> = {
          request_validation_failed: "prompts.invalidInput",
          validation_failed: "prompts.invalidInput",
          forbidden: "prompts.accessDenied",
          not_found: "prompts.resourceNotFound",
          conflict: "prompts.conflict",
          service_unavailable: "prompts.serviceUnavailable",
        };
        const key = codeKeys[err.code];
        if (key && i18n.exists(key)) return t(key);
      }
      return t(fallbackKey, params);
    },
    [i18n, t],
  );
  const [roles, setRoles] = useState<Role[]>([]);
  const [sessionTypes, setSessionTypes] = useState<SessionTypeDetail[]>([]);
  const [globalBlocks, setGlobalBlocks] = useState<GlobalBlock[]>([]);

  const [dataLoading, setDataLoading] = useState(true);
  const [dataError, setDataError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState("");
  const newSessionButtonRef = useRef<HTMLButtonElement>(null);
  const pendingRoleFocusIdRef = useRef<string | null>(null);

  const [showSessionModal, setShowSessionModal] = useState(false);
  const [editingSessionKey, setEditingSessionKey] = useState<string | null>(null);
  const [sessionForm, setSessionForm] = useState<SessionTypeFormState>(EMPTY_SESSION_FORM);
  const [sessionSaving, setSessionSaving] = useState(false);
  const [sessionFormError, setSessionFormError] = useState<string | null>(null);
  const [sessionFormErrorTarget, setSessionFormErrorTarget] = useState<string | null>(null);
  const [deleteSessionTarget, setDeleteSessionTarget] = useState<SessionTypeDetail | null>(null);
  const [sessionDeleting, setSessionDeleting] = useState(false);

  const [showGlobalModal, setShowGlobalModal] = useState(false);
  const [editingGlobalId, setEditingGlobalId] = useState<string | null>(null);
  const [globalForm, setGlobalForm] = useState<GlobalFormState>(EMPTY_GLOBAL_FORM);
  const [globalSaving, setGlobalSaving] = useState(false);
  const [globalFormError, setGlobalFormError] = useState<string | null>(null);
  const [globalFormErrorTarget, setGlobalFormErrorTarget] = useState<string | null>(null);

  const [restoringTarget, setRestoringTarget] = useState<RestoreTarget | null>(null);
  const [singleRestoreTarget, setSingleRestoreTarget] = useState<RestoreTarget | null>(null);
  const [revealingDirectory, setRevealingDirectory] = useState<"session-types" | "globals" | null>(
    null,
  );

  // A parent refresh failure does not invalidate the completed backend save.
  const [parentSyncError, setParentSyncError] = useState<string | null>(null);

  const loadAll = useCallback(
    async (announce = true) => {
      setDataLoading(true);
      setDataError(null);
      try {
        const [roleList, sessionList, globalList] = await Promise.all([
          listRoles(),
          listPromptSessionTypes(),
          listPromptGlobals(),
        ]);
        // Each independently persisted catalogue can render an empty fallback.
        setRoles(Array.isArray(roleList) ? roleList : []);
        setSessionTypes(Array.isArray(sessionList) ? sessionList : []);
        setGlobalBlocks(Array.isArray(globalList) ? globalList : []);
        if (announce) {
          setStatusMessage(
            sessionList.length === 0 && globalList.length === 0
              ? t("prompts.configurationEmptyStatus")
              : t("prompts.configurationLoadedStatus"),
          );
        }
      } catch (err) {
        setDataError(actionError(err, "prompts.configurationLoadError"));
      } finally {
        setDataLoading(false);
      }
    },
    [actionError, t],
  );

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    const focusId = pendingRoleFocusIdRef.current;
    if (!focusId) return;
    pendingRoleFocusIdRef.current = null;
    document.getElementById(focusId)?.focus();
  }, [sessionForm.selectedRoleIds]);

  // Call only after the local catalogues have reloaded successfully.
  const notifyParent = useCallback(async (): Promise<void> => {
    try {
      await onConfigurationChanged();
      setParentSyncError(null);
    } catch {
      setParentSyncError(t("prompts.setupSyncNotice"));
    }
  }, [onConfigurationChanged, t]);

  const handleRevealDirectory = async (directory: "session-types" | "globals") => {
    setStatusMessage("");
    setRevealingDirectory(directory);
    setDataError(null);
    try {
      if (directory === "session-types") {
        if (hasNativeManagedPathReveal()) await revealManagedPath("session_types");
        else await revealPromptSessionTypesDirectory();
      } else {
        if (hasNativeManagedPathReveal()) await revealManagedPath("prompt_library");
        else await revealPromptGlobalsDirectory();
      }
      setStatusMessage(
        t(
          directory === "session-types"
            ? "prompts.sessionTypesFolderOpenedStatus"
            : "prompts.promptBlocksFolderOpenedStatus",
        ),
      );
    } catch (err) {
      setDataError(
        actionError(
          err,
          directory === "session-types"
            ? "prompts.revealSessionTypesFolderError"
            : "prompts.revealGlobalBlocksFolderError",
        ),
      );
    } finally {
      setRevealingDirectory(null);
    }
  };

  const openNewSession = () => {
    setSessionForm(EMPTY_SESSION_FORM);
    setEditingSessionKey(null);
    setSessionFormError(null);
    setSessionFormErrorTarget(null);
    setShowSessionModal(true);
  };

  const openEditSession = (detail: SessionTypeDetail) => {
    setSessionForm(sessionFormFromDetail(detail));
    setEditingSessionKey(detail.key);
    setSessionFormError(null);
    setSessionFormErrorTarget(null);
    setShowSessionModal(true);
  };

  const closeSessionModal = () => {
    if (sessionSaving) return;
    setShowSessionModal(false);
    setSessionFormError(null);
    setSessionFormErrorTarget(null);
    setSessionForm(EMPTY_SESSION_FORM);
    setEditingSessionKey(null);
  };

  const handleSessionField = <K extends keyof SessionTypeFormState>(
    field: K,
    value: SessionTypeFormState[K],
  ) => {
    setSessionFormError(null);
    setSessionFormErrorTarget(null);
    setSessionForm((prev) => ({ ...prev, [field]: value }));
  };

  const updateInput = (index: number, update: { prompt_heading?: string }) => {
    setSessionFormError(null);
    setSessionFormErrorTarget(null);
    setSessionForm((previous) => ({
      ...previous,
      inputs: previous.inputs.map((input, inputIndex) =>
        inputIndex === index ? { ...input, ...update } : input,
      ),
    }));
  };

  const setInputField = (
    index: number,
    field: "label" | "hint" | "default_text",
    value: string,
  ) => {
    setSessionFormError(null);
    setSessionFormErrorTarget(null);
    setSessionForm((previous) => ({
      ...previous,
      inputs: previous.inputs.map((input, inputIndex) => {
        if (inputIndex !== index) return input;
        return { ...input, [field]: value };
      }),
    }));
  };

  const toggleSessionRole = (roleId: string) => {
    setSessionForm((prev) => {
      const has = prev.selectedRoleIds.includes(roleId);
      pendingRoleFocusIdRef.current = has
        ? `pcm-role-available-${roleId}`
        : `pcm-role-remove-${roleId}`;
      setStatusMessage(
        t(has ? "prompts.roleRemovedFromSessionStatus" : "prompts.roleAddedToSessionStatus", {
          label: roles.find((role) => role.id === roleId)?.label ?? roleId,
        }),
      );
      const next = has
        ? prev.selectedRoleIds.filter((id) => id !== roleId)
        : [...prev.selectedRoleIds, roleId];
      return { ...prev, selectedRoleIds: uniqueOrdered(next) };
    });
  };

  const moveSessionRole = (roleId: string, direction: -1 | 1) => {
    setSessionForm((prev) => {
      const current = [...prev.selectedRoleIds];
      const idx = current.indexOf(roleId);
      if (idx < 0) return prev;
      const target = idx + direction;
      if (target < 0 || target >= current.length) return prev;
      const [moved] = current.splice(idx, 1);
      current.splice(target, 0, moved);
      setStatusMessage(
        t(direction < 0 ? "prompts.roleMovedUpStatus" : "prompts.roleMovedDownStatus", {
          label: roles.find((role) => role.id === roleId)?.label ?? roleId,
        }),
      );
      return { ...prev, selectedRoleIds: current };
    });
  };

  const handleSessionSave = async () => {
    setStatusMessage("");
    setSessionFormError(null);
    setSessionFormErrorTarget(null);

    const showValidationError = (message: string, targetId: string) => {
      setSessionFormError(message);
      setSessionFormErrorTarget(targetId);
      document.getElementById(targetId)?.focus();
    };

    const key = sessionForm.key.trim();
    const label = sessionForm.label.trim();
    const description = sessionForm.description.trim();
    const body = sessionForm.body.trim();
    const inputs = sessionForm.inputs.map((input) => ({
      ...input,
      prompt_heading: input.prompt_heading.trim(),
    }));

    if (editingSessionKey === null) {
      if (!key) {
        showValidationError(t("errors.keyRequired"), "pcm-session-key");
        return;
      }
      if (!/^[a-z][a-z0-9_]*$/.test(key)) {
        showValidationError(t("prompts.sessionKeyHint"), "pcm-session-key");
        return;
      }
    }
    if (!label) {
      showValidationError(t("errors.displayNameRequired"), "pcm-session-label");
      return;
    }
    if (!description) {
      showValidationError(t("errors.descriptionRequired"), "pcm-session-description");
      return;
    }
    if (!body) {
      showValidationError(t("errors.bodyRequired"), "pcm-session-body");
      return;
    }
    if (
      inputs.length !== 3 ||
      inputs.some((input) => !input.prompt_heading || !sessionInputText(input.label).trim())
    ) {
      const invalidIndex = inputs.findIndex(
        (input) => !input.prompt_heading || !sessionInputText(input.label).trim(),
      );
      const invalidInput = inputs[invalidIndex];
      const targetId = !invalidInput?.prompt_heading
        ? `pcm-session-input-heading-${invalidIndex}`
        : `pcm-session-input-label-${invalidIndex}`;
      showValidationError(t("prompts.invalidSessionInputs"), targetId);
      return;
    }

    // A concurrently deleted role remains visible as a warning but is never persisted.
    const knownRoleIds = new Set(roles.map((r) => r.id));
    const roleIds = uniqueOrdered(sessionForm.selectedRoleIds.filter((id) => knownRoleIds.has(id)));

    setSessionSaving(true);
    let createdKey: string | null = null;
    let persisted = false;
    try {
      if (editingSessionKey === null) {
        const payload: SessionTypeCreatePayload = {
          key,
          label,
          description,
          default_agent_prompt_ids: roleIds,
          include_unchanged_research_material_context_in_prompt:
            sessionForm.includeUnchangedResearchMaterialContextInPrompt,
          body,
          inputs,
        };
        const created = await createPromptSessionType(payload);
        createdKey = created.key;
        setShowSessionModal(false);
        setSessionForm(EMPTY_SESSION_FORM);
        setEditingSessionKey(null);
        await loadAll(false);
        persisted = true;
      } else {
        const original = sessionTypes.find((s) => s.key === editingSessionKey);
        if (!original) {
          setSessionFormError(t("errors.sessionTypeRemoved"));
          return;
        }
        const candidate: SessionTypeFormState = {
          ...sessionForm,
          key: editingSessionKey,
          label,
          description,
          body,
          selectedRoleIds: roleIds,
          includeUnchangedResearchMaterialContextInPrompt:
            sessionForm.includeUnchangedResearchMaterialContextInPrompt,
          inputs,
        };
        const diff = sessionTypePayloadDiff(original, candidate);
        if (!diff) {
          setShowSessionModal(false);
          setSessionForm(EMPTY_SESSION_FORM);
          setEditingSessionKey(null);
          return;
        }
        await updatePromptSessionType(editingSessionKey, diff);

        setShowSessionModal(false);
        setSessionForm(EMPTY_SESSION_FORM);
        setEditingSessionKey(null);
        await loadAll(false);
        persisted = true;
      }
    } catch (err) {
      setSessionFormError(actionError(err, "prompts.sessionSaveError"));
    } finally {
      setSessionSaving(false);
    }
    // Announce a new key only after the parent has refreshed its catalogue.
    if (persisted) {
      await notifyParent();
      if (createdKey) onSessionTypeCreated?.(createdKey);
      setStatusMessage(t("prompts.sessionTypeSavedStatus", { label }));
    }
  };

  const handleConfirmSessionDelete = async () => {
    if (!deleteSessionTarget) return;
    const target = deleteSessionTarget;
    setStatusMessage("");
    setDeleteSessionTarget(null);
    setSessionDeleting(true);
    setDataError(null);
    setParentSyncError(null);
    let persisted = false;
    try {
      await deletePromptSessionType(target.key);
      await loadAll(false);
      persisted = true;
    } catch (err) {
      setDataError(actionError(err, "prompts.sessionDeleteError", { label: target.label }));
    } finally {
      setSessionDeleting(false);
    }
    if (persisted) {
      await notifyParent();
      setStatusMessage(t("prompts.sessionTypeDeletedStatus", { label: target.label }));
    }
  };

  const openEditGlobal = (block: GlobalBlock) => {
    setGlobalForm(globalFormFromBlock(block));
    setEditingGlobalId(block.id);
    setGlobalFormError(null);
    setGlobalFormErrorTarget(null);
    setShowGlobalModal(true);
  };

  const closeGlobalModal = () => {
    if (globalSaving) return;
    setShowGlobalModal(false);
    setGlobalFormError(null);
    setGlobalFormErrorTarget(null);
  };

  const handleGlobalField = <K extends keyof GlobalFormState>(
    field: K,
    value: GlobalFormState[K],
  ) => {
    setGlobalFormError(null);
    setGlobalFormErrorTarget(null);
    setGlobalForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleGlobalSave = async () => {
    setStatusMessage("");
    if (editingGlobalId === null) return;
    setGlobalFormError(null);
    const label = globalForm.label.trim();
    if (!label) {
      setGlobalFormError(t("errors.displayNameRequired"));
      setGlobalFormErrorTarget("pcm-global-label");
      document.getElementById("pcm-global-label")?.focus();
      return;
    }
    const payload: GlobalUpdatePayload = {
      label,
      content: globalForm.content,
    };
    setGlobalSaving(true);
    let persisted = false;
    try {
      await updatePromptGlobal(editingGlobalId, payload);
      setShowGlobalModal(false);
      await loadAll(false);
      persisted = true;
    } catch (err) {
      setGlobalFormError(actionError(err, "prompts.globalSaveError"));
    } finally {
      setGlobalSaving(false);
    }
    if (persisted) {
      await notifyParent();
      setStatusMessage(t("prompts.globalBlockSavedStatus", { label }));
    }
  };

  const askSingleRestore = (target: RestoreTarget) => {
    setSingleRestoreTarget(target);
  };

  const handleConfirmSingleRestore = async () => {
    if (!singleRestoreTarget) return;
    const target = singleRestoreTarget;
    setStatusMessage("");
    setSingleRestoreTarget(null);
    setRestoringTarget(target);
    setDataError(null);
    let persisted = false;
    try {
      if (target.resource === "session") {
        await restoreDefaultPromptSessionType(target.id);
      } else {
        await restoreDefaultPromptGlobal(target.id);
      }
      await loadAll(false);
      persisted = true;
    } catch (err) {
      setDataError(actionError(err, "prompts.restoreResourceError", { label: target.label }));
    } finally {
      setRestoringTarget(null);
    }
    if (persisted) {
      await notifyParent();
      setStatusMessage(t("prompts.configurationRestoredStatus", { label: target.label }));
    }
  };

  const isBusy =
    dataLoading || sessionSaving || sessionDeleting || globalSaving || restoringTarget !== null;

  const availableRoles = useMemo(() => {
    const selected = new Set(sessionForm.selectedRoleIds);
    return roles.filter((r) => !selected.has(r.id));
  }, [roles, sessionForm.selectedRoleIds]);

  const selectedSessionRoles = useMemo(() => {
    const byId = new Map(roles.map((r) => [r.id, r] as const));
    return sessionForm.selectedRoleIds
      .map((id) => byId.get(id))
      .filter((r): r is Role => r !== undefined);
  }, [roles, sessionForm.selectedRoleIds]);

  // Keep missing selections visible until save filters them from the payload.
  const danglingRoleIds = useMemo(() => {
    const known = new Set(roles.map((r) => r.id));
    return uniqueOrdered(sessionForm.selectedRoleIds.filter((id) => !known.has(id)));
  }, [roles, sessionForm.selectedRoleIds]);

  return (
    <div className="pcm-manager">
      <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {statusMessage}
      </div>
      {dataError && (
        <NoticeBanner
          className="pcm-feedback"
          dismissReturnFocusRef={newSessionButtonRef}
          tone="error"
          onDismiss={() => setDataError(null)}
        >
          {dataError}
        </NoticeBanner>
      )}

      {parentSyncError && !dataError && (
        <NoticeBanner
          className="pcm-feedback pcm-feedback--sync"
          dismissReturnFocusRef={newSessionButtonRef}
          tone="warning"
          onDismiss={() => setParentSyncError(null)}
        >
          {parentSyncError}
        </NoticeBanner>
      )}

      <section className="pcm-section">
        <SectionHeader
          className="pcm-section-header"
          headingLevel={3}
          title={t("prompts.sessionTypesTitle")}
          actions={
            <>
              <Button
                onClick={() => handleRevealDirectory("session-types")}
                disabled={isBusy || revealingDirectory !== null}
                title={t("prompts.openSessionTypesFolder")}
                aria-label={
                  revealingDirectory === "session-types"
                    ? t("prompts.openingFolder")
                    : t("prompts.openSessionTypesFolder")
                }
              >
                {revealingDirectory === "session-types" ? (
                  t("prompts.openingFolder")
                ) : (
                  <>
                    <MaterialSymbol name="folder_open" decorative />{" "}
                    {t("prompts.openSessionTypesFolder")}
                  </>
                )}
              </Button>
              <Button
                ref={newSessionButtonRef}
                variant="primary"
                onClick={openNewSession}
                disabled={isBusy}
              >
                + {t("prompts.newSessionType")}
              </Button>
            </>
          }
        />

        {dataLoading ? (
          <div className="pcm-loading">{t("prompts.loadingConfiguration")}</div>
        ) : sessionTypes.length === 0 ? (
          <div className="pcm-empty">{t("prompts.noSessionTypes")}</div>
        ) : (
          // This table overflows locally at narrow widths, so its scroll owner must be keyboard reachable.
          // eslint-disable-next-line jsx-a11y-x/no-noninteractive-tabindex
          <div
            className="pcm-table-scroll"
            role="region"
            aria-label={t("prompts.sessionTypesTitle")}
            tabIndex={0}
          >
            <table className="pcm-table">
              <thead>
                <tr>
                  <th>{t("prompts.id")}</th>
                  <th>{t("prompts.displayName")}</th>
                  <th>{t("prompts.origin")}</th>
                  <th>{t("prompts.defaultRoles")}</th>
                  <th>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {sessionTypes.map((s) => {
                  const defaultAgentPromptIds = Array.isArray(s.default_agent_prompt_ids)
                    ? s.default_agent_prompt_ids
                    : [];
                  const provenanceClass = PROVENANCE_CLASS[s.origin];
                  const provenanceLabel = t(PROVENANCE_LABEL_KEYS[s.origin]);
                  const isAlreadyBaseline = s.origin === "shipped_default";
                  const isResetting =
                    restoringTarget?.resource === "session" && restoringTarget.id === s.key;
                  return (
                    <tr key={s.key}>
                      <td className="pcm-cell-key">{s.key}</td>
                      <td>{s.label}</td>
                      <td>
                        <span className={provenanceClass} title={t(provenanceTitleKey(s.origin))}>
                          {provenanceLabel}
                        </span>
                      </td>
                      <td className="pcm-cell-agents">
                        {defaultAgentPromptIds.length === 0 ? (
                          <span className="pcm-muted">—</span>
                        ) : (
                          defaultAgentPromptIds.join(", ")
                        )}
                      </td>
                      <td className="pcm-cell-actions">
                        <ActionGroup className="pcm-actions" align="start">
                          {s.is_shipped && (
                            <Button
                              variant="text"
                              onClick={() =>
                                askSingleRestore({
                                  resource: "session",
                                  id: s.key,
                                  label: s.label,
                                })
                              }
                              disabled={isBusy || isAlreadyBaseline}
                              title={
                                isAlreadyBaseline
                                  ? t("prompts.alreadyDefault")
                                  : t("prompts.resetSessionType", { label: s.label })
                              }
                              aria-label={`${t("prompts.restoreDefault")} — ${s.label}`}
                            >
                              {isResetting ? (
                                t("prompts.restoring")
                              ) : (
                                <>
                                  <MaterialSymbol name="refresh" decorative />{" "}
                                  {t("prompts.restoreDefault")}
                                </>
                              )}
                            </Button>
                          )}
                          <Button onClick={() => openEditSession(s)} disabled={isBusy}>
                            {t("common.edit")}
                          </Button>
                          {s.origin === "custom" && (
                            <IconButton
                              variant="danger"
                              label={t("prompts.deleteSessionTypeAction", { label: s.label })}
                              onClick={() => setDeleteSessionTarget(s)}
                              disabled={isBusy}
                            >
                              <MaterialSymbol name="delete" decorative />
                            </IconButton>
                          )}
                        </ActionGroup>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="pcm-section">
        <SectionHeader
          className="pcm-section-header"
          headingLevel={3}
          title={t("prompts.globalBlocksTitle")}
          actions={
            <>
              <span className="pcm-readonly-note">{t("prompts.globalsEditHint")}</span>
              <Button
                onClick={() => handleRevealDirectory("globals")}
                disabled={isBusy || revealingDirectory !== null}
                title={t("prompts.openPromptBlocksFolder")}
                aria-label={
                  revealingDirectory === "globals"
                    ? t("prompts.openingFolder")
                    : t("prompts.openPromptBlocksFolder")
                }
              >
                {revealingDirectory === "globals" ? (
                  t("prompts.openingFolder")
                ) : (
                  <>
                    <MaterialSymbol name="folder_open" decorative />{" "}
                    {t("prompts.openPromptBlocksFolder")}
                  </>
                )}
              </Button>
            </>
          }
        />

        {dataLoading ? (
          <div className="pcm-loading">{t("prompts.loadingGlobals")}</div>
        ) : globalBlocks.length === 0 ? (
          <div className="pcm-empty">{t("prompts.noGlobals")}</div>
        ) : (
          // This table overflows locally at narrow widths, so its scroll owner must be keyboard reachable.
          // eslint-disable-next-line jsx-a11y-x/no-noninteractive-tabindex
          <div
            className="pcm-table-scroll"
            role="region"
            aria-label={t("prompts.globalBlocksTitle")}
            tabIndex={0}
          >
            <table className="pcm-table">
              <thead>
                <tr>
                  <th>{t("prompts.id")}</th>
                  <th>{t("prompts.displayName")}</th>
                  <th>{t("prompts.origin")}</th>
                  <th>{t("prompts.scope")}</th>
                  <th>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {globalBlocks.map((block) => {
                  const provenanceClass = PROVENANCE_CLASS[block.origin];
                  const provenanceLabel = t(PROVENANCE_LABEL_KEYS[block.origin]);
                  const isAlreadyBaseline = block.origin === "shipped_default";
                  const isResetting =
                    restoringTarget?.resource === "global" && restoringTarget.id === block.id;
                  return (
                    <tr key={block.id}>
                      <td className="pcm-cell-key">{block.id}</td>
                      <td>{block.label}</td>
                      <td>
                        <span
                          className={provenanceClass}
                          title={t(provenanceTitleKey(block.origin))}
                        >
                          {provenanceLabel}
                        </span>
                      </td>
                      <td>
                        <span className="pcm-scope-badge">{formatPromptScope(block.scope, t)}</span>
                      </td>
                      <td className="pcm-cell-actions">
                        <ActionGroup className="pcm-actions" align="start">
                          {block.is_shipped && (
                            <Button
                              variant="text"
                              onClick={() =>
                                askSingleRestore({
                                  resource: "global",
                                  id: block.id,
                                  label: block.label,
                                })
                              }
                              disabled={isBusy || isAlreadyBaseline}
                              title={
                                isAlreadyBaseline
                                  ? t("prompts.alreadyDefault")
                                  : t("prompts.resetGlobalBlock", { label: block.label })
                              }
                              aria-label={`${t("prompts.restoreDefault")} — ${block.label}`}
                            >
                              {isResetting ? (
                                t("prompts.restoring")
                              ) : (
                                <>
                                  <MaterialSymbol name="refresh" decorative />{" "}
                                  {t("prompts.restoreDefault")}
                                </>
                              )}
                            </Button>
                          )}
                          <Button
                            id={`pcm-edit-global-${block.id}`}
                            onClick={() => openEditGlobal(block)}
                            disabled={isBusy}
                          >
                            {t("common.edit")}
                          </Button>
                        </ActionGroup>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <QuickActionsManager api={quickActionsApi} onChanged={onQuickActionsChanged} />

      {singleRestoreTarget && (
        <ConfirmDialog
          title={t("prompts.restoreDefaultTitle")}
          message={
            <>
              <p>
                {t("prompts.restoreSingleBody", {
                  resource:
                    singleRestoreTarget.resource === "session"
                      ? t("prompts.sessionTypeResource")
                      : t("prompts.globalBlockResource"),
                  label: singleRestoreTarget.label,
                  id: singleRestoreTarget.id,
                })}
              </p>
              <p>{t("prompts.otherConfigurationsUnaffected")}</p>
            </>
          }
          cancelLabel={t("common.cancel")}
          confirmLabel={t("prompts.restoreNow")}
          pendingLabel={t("prompts.restoring")}
          disabled={restoringTarget !== null}
          onCancel={() => setSingleRestoreTarget(null)}
          onConfirm={handleConfirmSingleRestore}
        />
      )}

      {deleteSessionTarget && (
        <ConfirmDialog
          title={t("prompts.deleteSessionTypeTitle")}
          message={
            <>
              <p className="rm-confirm-text">
                {t("prompts.deleteSessionBody", {
                  label: deleteSessionTarget.label,
                  key: deleteSessionTarget.key,
                })}
              </p>
              <p className="rm-confirm-text">{t("prompts.shippedSessionDeleteBlocked")}</p>
            </>
          }
          cancelLabel={t("common.cancel")}
          variant="delete"
          pendingLabel={t("common.loading")}
          disabled={sessionDeleting}
          onCancel={() => setDeleteSessionTarget(null)}
          onConfirm={handleConfirmSessionDelete}
          returnFocusRef={newSessionButtonRef}
        />
      )}

      {showSessionModal && (
        <Modal
          className="pcm-modal"
          layout="editor"
          labelledBy="pcm-session-modal-title"
          onClose={closeSessionModal}
        >
          <h2 id="pcm-session-modal-title">
            {editingSessionKey === null
              ? t("prompts.newSessionTypeTitle")
              : t("prompts.editSessionTypeTitle", { key: editingSessionKey })}
          </h2>

          {sessionFormError && (
            <EditorDialogError id="pcm-session-form-error">{sessionFormError}</EditorDialogError>
          )}

          <EditorDialogBody className="rm-form">
            {editingSessionKey === null ? (
              <Field
                className="rm-form-row"
                htmlFor="pcm-session-key"
                label={t("prompts.id")}
                description={t("prompts.sessionKeyHint")}
              >
                <Input
                  id="pcm-session-key"
                  value={sessionForm.key}
                  onChange={(e) => handleSessionField("key", e.target.value)}
                  placeholder={t("prompts.sessionKeyPlaceholder")}
                  aria-invalid={sessionFormErrorTarget === "pcm-session-key"}
                  aria-describedby={
                    sessionFormErrorTarget === "pcm-session-key"
                      ? "pcm-session-form-error"
                      : undefined
                  }
                />
              </Field>
            ) : (
              <div className="rm-form-row">
                <span className="rm-form-label">{t("prompts.id")}</span>
                <code className="pcm-immutable-id">{editingSessionKey}</code>
              </div>
            )}

            <Field
              className="rm-form-row"
              htmlFor="pcm-session-label"
              label={t("prompts.displayName")}
            >
              <Input
                id="pcm-session-label"
                value={sessionForm.label}
                onChange={(e) => handleSessionField("label", e.target.value)}
                placeholder={t("prompts.sessionLabelPlaceholder")}
                aria-invalid={sessionFormErrorTarget === "pcm-session-label"}
                aria-describedby={
                  sessionFormErrorTarget === "pcm-session-label"
                    ? "pcm-session-form-error"
                    : undefined
                }
              />
            </Field>

            <Field
              className="rm-form-row"
              htmlFor="pcm-session-description"
              label={t("prompts.description")}
            >
              <Textarea
                id="pcm-session-description"
                className="rm-textarea"
                value={sessionForm.description}
                onChange={(e) => handleSessionField("description", e.target.value)}
                rows={3}
                placeholder={t("prompts.descriptionPlaceholder")}
                aria-invalid={sessionFormErrorTarget === "pcm-session-description"}
                aria-describedby={
                  sessionFormErrorTarget === "pcm-session-description"
                    ? "pcm-session-form-error"
                    : undefined
                }
              />
            </Field>

            <section className="pcm-session-instructions" aria-labelledby="pcm-session-body-label">
              <label id="pcm-session-body-label" htmlFor="pcm-session-body">
                {t("prompts.body")}
              </label>
              <Textarea
                id="pcm-session-body"
                className="rm-textarea pcm-body-textarea"
                value={sessionForm.body}
                onChange={(e) => handleSessionField("body", e.target.value)}
                rows={10}
                placeholder={t("prompts.bodyPlaceholder")}
                aria-invalid={sessionFormErrorTarget === "pcm-session-body"}
                aria-describedby={
                  sessionFormErrorTarget === "pcm-session-body"
                    ? "pcm-session-form-error"
                    : undefined
                }
              />
            </section>

            <section className="pcm-input-section" aria-labelledby="pcm-setup-inputs-title">
              <h3 id="pcm-setup-inputs-title">{t("prompts.setupInputs")}</h3>
              <p className="rm-hint">{t("prompts.setupInputsHelp")}</p>
              <div className="pcm-input-list">
                {sessionForm.inputs.map((input, index) => (
                  <section className="pcm-input-item" key={`${input.key}-${index}`}>
                    <div className="pcm-input-item-header">
                      <strong>{sessionInputText(input.label)}</strong>
                      <code className="pcm-input-key">{input.key}</code>
                    </div>
                    <div className="pcm-input-grid">
                      <label>
                        {t("prompts.inputPromptHeading")}
                        <Input
                          id={`pcm-session-input-heading-${index}`}
                          value={input.prompt_heading}
                          onChange={(event) =>
                            updateInput(index, { prompt_heading: event.target.value })
                          }
                          aria-invalid={
                            sessionFormErrorTarget === `pcm-session-input-heading-${index}`
                          }
                          aria-describedby={
                            sessionFormErrorTarget === `pcm-session-input-heading-${index}`
                              ? "pcm-session-form-error"
                              : undefined
                          }
                        />
                      </label>
                      <label>
                        {t("prompts.inputDisplayName")}
                        <Input
                          id={`pcm-session-input-label-${index}`}
                          value={sessionInputText(input.label)}
                          onChange={(event) => setInputField(index, "label", event.target.value)}
                          aria-invalid={
                            sessionFormErrorTarget === `pcm-session-input-label-${index}`
                          }
                          aria-describedby={
                            sessionFormErrorTarget === `pcm-session-input-label-${index}`
                              ? "pcm-session-form-error"
                              : undefined
                          }
                        />
                      </label>
                      <label className="pcm-input-full">
                        {t("prompts.inputHint")}
                        <Input
                          value={sessionInputText(input.hint)}
                          onChange={(event) => setInputField(index, "hint", event.target.value)}
                        />
                      </label>
                      <label className="pcm-input-full">
                        {t("prompts.inputDefaultText")}
                        <Textarea
                          className="rm-textarea"
                          rows={3}
                          value={sessionInputText(input.default_text)}
                          onChange={(event) =>
                            setInputField(index, "default_text", event.target.value)
                          }
                        />
                      </label>
                      {input.key === "research_material_context" &&
                        sessionInputText(input.default_text).trim().length > 0 && (
                          <label className="pcm-input-full pcm-material-context-toggle">
                            <input
                              type="checkbox"
                              checked={sessionForm.includeUnchangedResearchMaterialContextInPrompt}
                              onChange={(event) =>
                                handleSessionField(
                                  "includeUnchangedResearchMaterialContextInPrompt",
                                  event.target.checked,
                                )
                              }
                            />
                            <span>{t("prompts.includeUnchangedTemplate")}</span>
                          </label>
                        )}
                    </div>
                  </section>
                ))}
              </div>
            </section>

            <section className="pcm-role-section" aria-labelledby="pcm-role-order-title">
              <h3 id="pcm-role-order-title">{t("prompts.roleOrder")}</h3>
              <p className="rm-hint">{t("prompts.roleOrderHint")}</p>
              {danglingRoleIds.length > 0 && (
                <div className="pcm-form-warning" role="status">
                  {t("prompts.danglingRoles", {
                    count: danglingRoleIds.length,
                    id: danglingRoleIds[0],
                  })}
                </div>
              )}
              <div className="pcm-role-columns">
                <div className="pcm-role-col">
                  <h4>{t("prompts.available")}</h4>
                  {availableRoles.length === 0 ? (
                    <div className="pcm-role-empty">{t("prompts.noMoreRoles")}</div>
                  ) : (
                    <ul className="pcm-role-list">
                      {availableRoles.map((r) => (
                        <li key={r.id}>
                          <label className="pcm-role-checkbox">
                            <input
                              id={`pcm-role-available-${r.id}`}
                              type="checkbox"
                              checked={false}
                              disabled={isBusy}
                              onChange={() => toggleSessionRole(r.id)}
                            />
                            <span>{r.label}</span>
                            <code className="pcm-role-code">{r.id}</code>
                          </label>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="pcm-role-col">
                  <h4>{t("prompts.selected")}</h4>
                  {selectedSessionRoles.length === 0 ? (
                    <div className="pcm-role-empty">{t("prompts.noSelectedRoles")}</div>
                  ) : (
                    <ul className="pcm-role-list">
                      {selectedSessionRoles.map((r, idx) => (
                        <li key={r.id}>
                          <div className="pcm-role-selected">
                            <span className="pcm-role-pos">{idx + 1}.</span>
                            <span className="pcm-role-label">{r.label}</span>
                            <code className="pcm-role-code">{r.id}</code>
                          </div>
                          <ActionGroup className="pcm-role-buttons" align="start">
                            <IconButton
                              size="small"
                              onClick={() => moveSessionRole(r.id, -1)}
                              disabled={isBusy || idx === 0}
                              label={t("prompts.moveRoleUp", { label: r.label })}
                              title={t("prompts.moveRoleUp", { label: r.label })}
                            >
                              <MaterialSymbol name="arrow_upward" decorative />
                            </IconButton>
                            <IconButton
                              size="small"
                              onClick={() => moveSessionRole(r.id, 1)}
                              disabled={isBusy || idx === selectedSessionRoles.length - 1}
                              label={t("prompts.moveRoleDown", { label: r.label })}
                              title={t("prompts.moveRoleDown", { label: r.label })}
                            >
                              <MaterialSymbol name="arrow_downward" decorative />
                            </IconButton>
                            <IconButton
                              id={`pcm-role-remove-${r.id}`}
                              size="small"
                              onClick={() => toggleSessionRole(r.id)}
                              disabled={isBusy}
                              label={t("prompts.removeRole", { label: r.label })}
                              title={t("prompts.removeRole", { label: r.label })}
                            >
                              <MaterialSymbol name="close" decorative />
                            </IconButton>
                          </ActionGroup>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </section>
          </EditorDialogBody>

          <DialogFooter>
            <Button onClick={closeSessionModal} disabled={isBusy}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="primary"
              onClick={handleSessionSave}
              disabled={isBusy}
              loading={sessionSaving}
              loadingLabel={t("common.saving")}
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </Modal>
      )}

      {showGlobalModal && editingGlobalId !== null && (
        <Modal
          className="pcm-modal"
          layout="editor"
          labelledBy="pcm-global-modal-title"
          onClose={closeGlobalModal}
        >
          <h2 id="pcm-global-modal-title">
            {t("prompts.editGlobalTitle", { id: editingGlobalId })}
          </h2>

          {globalFormError && (
            <EditorDialogError id="pcm-global-form-error">{globalFormError}</EditorDialogError>
          )}

          <EditorDialogBody className="rm-form">
            <div className="rm-form-row">
              <span className="rm-form-label">{t("prompts.id")}</span>
              <code className="pcm-immutable-id">{editingGlobalId}</code>
            </div>

            <Field
              className="rm-form-row"
              htmlFor="pcm-global-label"
              label={t("prompts.displayName")}
            >
              <Input
                id="pcm-global-label"
                value={globalForm.label}
                onChange={(e) => handleGlobalField("label", e.target.value)}
                aria-invalid={globalFormErrorTarget === "pcm-global-label"}
                aria-describedby={
                  globalFormErrorTarget === "pcm-global-label" ? "pcm-global-form-error" : undefined
                }
              />
            </Field>

            <Field
              className="rm-form-row"
              htmlFor="pcm-global-content"
              label={t("prompts.content")}
            >
              <Textarea
                id="pcm-global-content"
                className="rm-textarea pcm-body-textarea"
                value={globalForm.content}
                onChange={(e) => handleGlobalField("content", e.target.value)}
                rows={12}
              />
            </Field>
          </EditorDialogBody>

          <DialogFooter>
            <Button onClick={closeGlobalModal} disabled={isBusy}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="primary"
              onClick={handleGlobalSave}
              disabled={isBusy}
              loading={globalSaving}
              loadingLabel={t("common.saving")}
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </Modal>
      )}
    </div>
  );
};

export default PromptConfigurationManager;
export { type PromptConfigurationManagerProps, type SessionTypeFormState };
