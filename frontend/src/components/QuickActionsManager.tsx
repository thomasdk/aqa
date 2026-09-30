/* eslint-disable jsx-a11y-x/no-noninteractive-tabindex -- Named overflow regions need keyboard scrolling. */
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { QuickAction, QuickActionCreatePayload, QuickActionUpdatePayload } from "../api";
import type {
  QuickActionDeleteContract,
  QuickActionListContract,
  QuickActionRestoreContract,
  RevealGlobalsDirectoryContract,
} from "../api/contracts";
import { IconButton } from "./IconButton";
import { MaterialSymbol } from "./MaterialSymbol";
import { ConfirmDialog, Modal } from "./Modal";
import NoticeBanner from "./NoticeBanner";
import {
  ActionGroup,
  Button,
  DialogFooter,
  EditorDialogError,
  EditorDialogForm,
  Field,
  Input,
  SectionHeader,
  Textarea,
} from "./design-system";

export type QuickActionInfo = QuickAction;

/** The thin API surface makes this manager independently testable. */
export type QuickActionsApi = {
  list: () => Promise<QuickActionListContract>;
  reveal: () => Promise<RevealGlobalsDirectoryContract>;
  create: (payload: QuickActionCreatePayload) => Promise<QuickActionInfo>;
  update: (id: string, payload: QuickActionUpdatePayload) => Promise<QuickActionInfo>;
  remove: (id: string) => Promise<void | QuickActionDeleteContract>;
  restore: (id: string) => Promise<QuickActionRestoreContract>;
  restoreAll: () => Promise<QuickActionRestoreContract>;
};

type QuickActionsManagerProps = {
  api: QuickActionsApi;
  /** Lets the discussion view refresh its button row after a persisted edit. */
  onChanged?: () => void | Promise<void>;
};

type FormState = {
  id: string;
  label: string;
  prompt: string;
};

const EMPTY_FORM: FormState = { id: "", label: "", prompt: "" };

function formFromAction(action: QuickActionInfo): FormState {
  return { id: action.id, label: action.label, prompt: action.prompt };
}

function originLabel(origin: QuickActionInfo["origin"], t: (key: string) => string): string {
  switch (origin) {
    case "shipped_default":
      return t("prompts.quickActionDefault");
    case "shipped_modified":
      return t("prompts.quickActionModifiedDefault");
    case "custom":
      return t("prompts.quickActionCustom");
    default:
      return origin;
  }
}

/**
 * Installation-wide configuration for the generic text-only controls shown
 * below the discussion.  It deliberately has no connection to saved-session
 * state: only the prompt inserted when a button is clicked belongs to a
 * discussion's history.
 */
export default function QuickActionsManager({ api, onChanged }: QuickActionsManagerProps) {
  const { t } = useTranslation();
  const [actions, setActions] = useState<QuickActionInfo[]>([]);
  const [canRestoreDefaults, setCanRestoreDefaults] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState("");
  const newButtonRef = useRef<HTMLButtonElement>(null);
  const pendingDeleteFocusRef = useRef(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<QuickActionInfo | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [restoringAll, setRestoringAll] = useState(false);
  const [revealingDirectory, setRevealingDirectory] = useState(false);
  const [confirmation, setConfirmation] = useState<
    { kind: "delete"; action: QuickActionInfo } | { kind: "restore-all" } | null
  >(null);

  const reload = useCallback(
    async (announce = true) => {
      setLoading(true);
      setError(null);
      try {
        const loaded = await api.list();
        setActions(loaded.actions);
        setCanRestoreDefaults(loaded.can_restore_defaults);
        if (announce) {
          setStatusMessage(
            loaded.actions.length === 0
              ? t("prompts.quickActionsEmptyStatus")
              : t("prompts.quickActionsLoaded", { count: loaded.actions.length }),
          );
        }
      } catch {
        setCanRestoreDefaults(false);
        setError(t("prompts.quickActionsLoadError"));
      } finally {
        setLoading(false);
      }
    },
    [api, t],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    if (confirmation || busyId !== null || !pendingDeleteFocusRef.current) return;
    pendingDeleteFocusRef.current = false;
    newButtonRef.current?.focus();
  }, [busyId, confirmation]);

  const notifyChanged = async () => {
    try {
      await onChanged?.();
    } catch {
      // The manager has already reloaded its own persisted state. A failed
      // optional discussion-panel refresh must not make a successful edit
      // appear to have failed.
    }
  };

  const closeModal = () => {
    if (saving) return;
    setModalOpen(false);
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
  };

  const openNew = () => {
    setError(null);
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setModalOpen(true);
  };

  const openEdit = (action: QuickActionInfo) => {
    setError(null);
    setEditing(action);
    setForm(formFromAction(action));
    setFormError(null);
    setModalOpen(true);
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setFormError(null);
    setStatusMessage("");
    const savedLabel = form.label.trim();
    try {
      if (editing) {
        await api.update(editing.id, { label: form.label, prompt: form.prompt });
      } else {
        await api.create(form);
      }
      setModalOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      await reload(false);
      await notifyChanged();
      setStatusMessage(t("prompts.quickActionSavedStatus", { label: savedLabel }));
    } catch {
      setFormError(t("prompts.quickActionSaveError"));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (action: QuickActionInfo) => {
    setConfirmation({ kind: "delete", action });
  };

  const confirmRemove = async (action: QuickActionInfo) => {
    setStatusMessage("");
    setBusyId(action.id);
    setError(null);
    try {
      await api.remove(action.id);
      await reload(false);
      await notifyChanged();
      setBusyId(null);
      pendingDeleteFocusRef.current = true;
      setConfirmation(null);
      setStatusMessage(t("prompts.quickActionDeletedStatus", { label: action.label }));
    } catch {
      setBusyId(null);
      setConfirmation(null);
      setError(t("prompts.quickActionDeleteError"));
    } finally {
      setBusyId(null);
    }
  };

  const restore = async (action: QuickActionInfo) => {
    setStatusMessage("");
    setBusyId(action.id);
    setError(null);
    try {
      await api.restore(action.id);
      await reload(false);
      await notifyChanged();
      setStatusMessage(t("prompts.quickActionRestoredStatus", { label: action.label }));
      document.getElementById(`qam-edit-${action.id}`)?.focus();
    } catch {
      setError(t("prompts.quickActionRestoreError"));
    } finally {
      setBusyId(null);
    }
  };

  const restoreAll = async () => {
    setConfirmation({ kind: "restore-all" });
  };

  const confirmRestoreAll = async () => {
    setStatusMessage("");
    setRestoringAll(true);
    setError(null);
    try {
      await api.restoreAll();
      await reload(false);
      await notifyChanged();
      setConfirmation(null);
      setStatusMessage(t("prompts.quickActionsRestoredStatus"));
    } catch {
      setConfirmation(null);
      setError(t("prompts.quickActionsRestoreError"));
    } finally {
      setRestoringAll(false);
    }
  };

  const revealDirectory = async () => {
    setStatusMessage("");
    setRevealingDirectory(true);
    setError(null);
    try {
      await api.reveal();
      setStatusMessage(t("prompts.quickActionsFolderOpenedStatus"));
    } catch {
      setError(t("prompts.revealQuickActionsFolderError"));
    } finally {
      setRevealingDirectory(false);
    }
  };

  const isBusy = loading || saving || busyId !== null || restoringAll || revealingDirectory;

  return (
    <section className="pcm-section qam-section" aria-labelledby="quick-actions-heading">
      <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {statusMessage}
      </div>
      <SectionHeader
        className="pcm-section-header"
        headingLevel={3}
        titleId="quick-actions-heading"
        title={t("prompts.quickActionsTitle")}
        subtitle={t("prompts.quickActionsDescription")}
        actions={
          <>
            <Button
              onClick={() => void revealDirectory()}
              disabled={isBusy}
              title={
                revealingDirectory
                  ? t("prompts.openingFolder")
                  : t("prompts.openQuickActionsFolder")
              }
              aria-label={
                revealingDirectory
                  ? t("prompts.openingFolder")
                  : t("prompts.openQuickActionsFolder")
              }
            >
              {revealingDirectory ? (
                t("prompts.openingFolder")
              ) : (
                <>
                  <MaterialSymbol name="folder_open" decorative />{" "}
                  {t("prompts.openQuickActionsFolder")}
                </>
              )}
            </Button>
            <Button
              variant="text"
              onClick={restoreAll}
              disabled={isBusy || !canRestoreDefaults}
              title={
                !loading && !error && !canRestoreDefaults
                  ? t("prompts.quickActionsAlreadyDefault")
                  : undefined
              }
            >
              {restoringAll ? (
                t("prompts.restoring")
              ) : (
                <>
                  <MaterialSymbol name="refresh" decorative /> {t("prompts.restoreQuickActions")}
                </>
              )}
            </Button>
            <Button
              id="qam-new-action"
              ref={newButtonRef}
              variant="primary"
              onClick={openNew}
              disabled={isBusy}
            >
              + {t("prompts.newQuickAction")}
            </Button>
          </>
        }
      />

      {error && (
        <NoticeBanner
          className="qam-feedback"
          dismissReturnFocusRef={newButtonRef}
          tone="error"
          onDismiss={() => setError(null)}
        >
          {error}
        </NoticeBanner>
      )}
      {loading ? (
        <div className="pcm-loading">{t("common.loading")}</div>
      ) : actions.length === 0 ? (
        <div className="pcm-empty">{t("prompts.noQuickActions")}</div>
      ) : (
        // This table overflows locally at narrow widths, so its scroll owner must be keyboard reachable.
        // eslint-disable-next-line jsx-a11y-x/no-noninteractive-tabindex
        <div
          className="pcm-table-scroll"
          role="region"
          aria-label={t("prompts.quickActionsTitle")}
          tabIndex={0}
        >
          <table className="pcm-table qam-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>{t("prompts.displayName")}</th>
                <th>{t("prompts.quickActionPrompt")}</th>
                <th>{t("prompts.origin")}</th>
                <th>{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {actions.map((action) => {
                const resetting = busyId === action.id;
                const isDefault = action.origin === "shipped_default";
                return (
                  <tr key={action.id}>
                    <td className="pcm-cell-key">{action.id}</td>
                    <td>{action.label}</td>
                    <td className="qam-prompt">{action.prompt}</td>
                    <td>
                      <span className={`pcm-badge pcm-badge--${action.origin.replace("_", "-")}`}>
                        {originLabel(action.origin, t)}
                      </span>
                    </td>
                    <td className="pcm-cell-actions">
                      <ActionGroup className="pcm-actions" align="start">
                        {action.is_shipped && (
                          <Button
                            variant="text"
                            onClick={() => void restore(action)}
                            disabled={isBusy || isDefault}
                            aria-label={`${t("prompts.restoreDefault")} — ${action.label}`}
                            title={`${t("prompts.restoreDefault")} — ${action.label}`}
                          >
                            {resetting ? (
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
                          id={`qam-edit-${action.id}`}
                          onClick={() => openEdit(action)}
                          disabled={isBusy}
                        >
                          {t("common.edit")}
                        </Button>
                        <IconButton
                          variant="danger"
                          label={t("prompts.deleteQuickActionAction", { label: action.label })}
                          onClick={() => void remove(action)}
                          disabled={isBusy}
                        >
                          <MaterialSymbol name="delete" decorative />
                        </IconButton>
                      </ActionGroup>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {modalOpen && (
        <Modal
          className="pcm-modal qam-modal"
          layout="editor"
          labelledBy="qam-modal-title"
          onClose={closeModal}
        >
          <h2 id="qam-modal-title">
            {editing ? t("prompts.editQuickActionTitle") : t("prompts.newQuickActionTitle")}
          </h2>
          {formError && <EditorDialogError>{formError}</EditorDialogError>}
          <EditorDialogForm
            id="qam-editor-form"
            className="rm-form"
            onSubmit={(event) => void save(event)}
            aria-labelledby="qam-modal-title"
          >
            {editing && (
              <div className="rm-form-row">
                <span className="rm-form-label">{t("prompts.id")}</span>
                <code className="pcm-immutable-id">{editing.id}</code>
              </div>
            )}
            {!editing && (
              <Field
                className="rm-form-row"
                htmlFor="qam-id"
                label="ID"
                description={t("prompts.quickActionIdHint")}
              >
                <Input
                  id="qam-id"
                  value={form.id}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, id: event.target.value }))
                  }
                  placeholder={t("prompts.quickActionIdPlaceholder")}
                  pattern="[a-z][a-z0-9_]*"
                  required
                />
              </Field>
            )}
            <Field className="rm-form-row" htmlFor="qam-label" label={t("prompts.displayName")}>
              <Input
                id="qam-label"
                value={form.label}
                onChange={(event) =>
                  setForm((current) => ({ ...current, label: event.target.value }))
                }
                required
              />
            </Field>
            <Field
              className="rm-form-row"
              htmlFor="qam-prompt"
              label={t("prompts.quickActionPrompt")}
            >
              <Textarea
                id="qam-prompt"
                className="rm-textarea qam-textarea"
                value={form.prompt}
                onChange={(event) =>
                  setForm((current) => ({ ...current, prompt: event.target.value }))
                }
                required
              />
            </Field>
          </EditorDialogForm>
          <DialogFooter>
            <Button onClick={closeModal} disabled={saving}>
              {t("common.cancel")}
            </Button>
            <Button
              type="submit"
              form="qam-editor-form"
              variant="primary"
              disabled={saving}
              loading={saving}
              loadingLabel={t("common.saving")}
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </Modal>
      )}

      {confirmation?.kind === "delete" && (
        <ConfirmDialog
          title={t("prompts.deleteQuickActionTitle")}
          message={t("prompts.deleteQuickActionConfirm", { label: confirmation.action.label })}
          cancelLabel={t("common.cancel")}
          variant="delete"
          onCancel={() => setConfirmation(null)}
          onConfirm={() => void confirmRemove(confirmation.action)}
          disabled={busyId === confirmation.action.id}
          returnFocusRef={newButtonRef}
        />
      )}
      {confirmation?.kind === "restore-all" && (
        <ConfirmDialog
          title={t("prompts.restoreDefaultTitle")}
          message={t("prompts.restoreQuickActionsConfirm")}
          cancelLabel={t("common.cancel")}
          confirmLabel={t("prompts.restoreNow")}
          onCancel={() => setConfirmation(null)}
          onConfirm={() => void confirmRestoreAll()}
          disabled={restoringAll}
        />
      )}
    </section>
  );
}
