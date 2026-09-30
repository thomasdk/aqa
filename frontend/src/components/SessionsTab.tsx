import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import { useTranslation } from "react-i18next";
import { ApiError } from "../api";
import { translateClientError, translateErrorCode } from "../i18n";
import {
  buildSessionMetaLine,
  filterFavoriteSessions,
  groupSessionsByUpdatedDate,
  normalizeSessionTitleInput,
  shouldPersistTitleEdit,
  type FavoriteFilterMode,
} from "./sessionTab";
import { formatLocalSessionDateTime } from "./sessionPresentation";
import {
  bulkDeleteSessions,
  deleteSession,
  listSessions,
  renameSession,
  revealSession,
  setSessionFavorite,
} from "../api";
import { MaterialSymbol } from "./MaterialSymbol";
import { IconButton } from "./IconButton";
import { ConfirmDialog } from "./Modal";
import NoticeBanner from "./NoticeBanner";
import { Button, FavoriteToggle, Input, PageHeader } from "./design-system";
import type { SessionSummary } from "./types";
import { hasNativeManagedPathReveal, revealManagedPath } from "../desktopBridge";

type Status =
  | { kind: "loading" }
  | { kind: "loaded"; sessions: SessionSummary[] }
  | { kind: "error"; message: string };

type BulkDeleteMode = "all" | "except_favorites";
type BulkDeleteConfirmation = { mode: BulkDeleteMode; expectedFileIds: string[] };

type Props = {
  /**
   * Set to the file_id of the session that is currently open in the
   * Discussion view. The tab highlights that row and shows a small
   * active-session badge next to it.
   */
  activeFileId?: string | null;
  /**
   * Called when the user confirms opening a session row. The parent
   * (Layout) is responsible for the atomic hydration sequence:
   *   (a) cancel any in-flight SSE generation,
   *   (b) POST /api/sessions/{id}/open,
   *   (c) hydrate messages, material, agents, sequential mode, and
   *       material_context, and
   *   (d) navigate to the discussion view.
   */
  onOpen: (fileId: string) => void | Promise<void>;
  /**
   * Notify the parent about whether the open-session badge should
   * change, along with the successfully deleted IDs so it can clear
   * any matching last-active pointer.
   */
  onActiveSessionDeleted?: (
    wasOpen: boolean,
    deletedFileIds?: readonly string[],
  ) => void | Promise<void>;
  onMutationStart?: () => void;
  /**
   * Optional success/info message coming from the parent (for example
   * a successful open). Displayed briefly.
   */
  externalNotice?: string | null;
  onNoticeDismiss?: () => void;
};

const SessionsTab = ({
  activeFileId,
  onOpen,
  onActiveSessionDeleted,
  onMutationStart,
  externalNotice,
  onNoticeDismiss,
}: Props) => {
  const { t } = useTranslation();
  const localizedActionError = useCallback(
    (error: unknown, fallbackKey: string): string =>
      error instanceof ApiError ? translateErrorCode(error.code, error.params) : t(fallbackKey),
    [t],
  );
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [editingFileId, setEditingFileId] = useState<string | null>(null);
  const [editingDraft, setEditingDraft] = useState("");
  const editingInputRef = useRef<HTMLInputElement | null>(null);
  const [busyFileId, setBusyFileId] = useState<string | null>(null);
  const [openingFileId, setOpeningFileId] = useState<string | null>(null);
  const openingFileIdRef = useRef<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // Mirror parent notices locally because dismissal is owned by this tab.
  const [localNotice, setLocalNotice] = useState<string | null>(null);
  const [suppressExternalNotice, setSuppressExternalNotice] = useState(false);
  const visibleNotice = localNotice ?? (suppressExternalNotice ? null : externalNotice) ?? null;
  const dismissNotice = useCallback(() => {
    setLocalNotice(null);
    setSuppressExternalNotice(true);
    onNoticeDismiss?.();
  }, [onNoticeDismiss]);
  const [confirmDelete, setConfirmDelete] = useState<SessionSummary | null>(null);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState<BulkDeleteConfirmation | null>(null);
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [favoriteFilter, setFavoriteFilter] = useState<FavoriteFilterMode>("all");
  // Prevent concurrent writes for the same favorite toggle.
  const [favoriteBusyFileId, setFavoriteBusyFileId] = useState<string | null>(null);

  useEffect(() => {
    if (editingFileId) editingInputRef.current?.focus();
  }, [editingFileId]);

  const refresh = useCallback(async () => {
    setStatus({ kind: "loading" });
    try {
      const sessions = await listSessions();
      setStatus({ kind: "loaded", sessions });
    } catch (err) {
      setStatus({
        kind: "error",
        message: translateClientError(err, "sessions.loadError"),
      });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!externalNotice) return;
    setSuppressExternalNotice(false);
    setLocalNotice(externalNotice);
    const timer = window.setTimeout(dismissNotice, 4000);
    return () => window.clearTimeout(timer);
  }, [dismissNotice, externalNotice]);

  const handleOpen = useCallback(
    async (fileId: string) => {
      if (openingFileIdRef.current !== null) return;
      setActionError(null);
      openingFileIdRef.current = fileId;
      setOpeningFileId(fileId);
      try {
        await onOpen(fileId);
        void refresh();
      } catch (err) {
        setActionError(localizedActionError(err, "sessions.openError"));
      } finally {
        openingFileIdRef.current = null;
        setOpeningFileId(null);
      }
    },
    [localizedActionError, onOpen, refresh],
  );

  const handleReveal = useCallback(
    async (fileId: string) => {
      setActionError(null);
      setBusyFileId(fileId);
      try {
        if (hasNativeManagedPathReveal()) {
          await revealManagedPath("session", fileId);
        } else {
          await revealSession(fileId);
        }
      } catch (err) {
        setActionError(localizedActionError(err, "sessions.revealError"));
      } finally {
        setBusyFileId(null);
      }
    },
    [localizedActionError],
  );

  const handleAskDelete = useCallback(
    (session: SessionSummary) => {
      onMutationStart?.();
      setSuppressExternalNotice(true);
      setLocalNotice(null);
      setActionError(null);
      setConfirmDelete(session);
    },
    [onMutationStart],
  );

  const handleConfirmDelete = useCallback(async () => {
    const session = confirmDelete;
    if (!session) return;
    setConfirmDelete(null);
    setActionError(null);
    setBusyFileId(session.file_id);
    try {
      const result = await deleteSession(session.file_id);
      await onActiveSessionDeleted?.(result.was_open, result.deleted_ids);
      setStatus((previous) =>
        previous.kind === "loaded"
          ? {
              kind: "loaded",
              sessions: previous.sessions.filter(
                (item) => !result.deleted_ids.includes(item.file_id),
              ),
            }
          : previous,
      );
      setLocalNotice(t("sessions.deleted", { title: session.title }));
      try {
        setStatus({ kind: "loaded", sessions: await listSessions() });
      } catch {
        setLocalNotice(t("sessions.deletedRefreshWarning", { title: session.title }));
      }
    } catch (err) {
      setLocalNotice(null);
      setActionError(localizedActionError(err, "sessions.deleteError"));
    } finally {
      setBusyFileId(null);
    }
  }, [confirmDelete, localizedActionError, onActiveSessionDeleted, t]);

  const handleAskBulkDelete = useCallback(
    (mode: BulkDeleteMode) => {
      if (status.kind !== "loaded") return;
      onMutationStart?.();
      setSuppressExternalNotice(true);
      setLocalNotice(null);
      setActionError(null);
      setConfirmBulkDelete({
        mode,
        expectedFileIds: status.sessions
          .filter((session) => mode === "all" || !session.is_favorite)
          .map((session) => session.file_id),
      });
    },
    [onMutationStart, status],
  );

  const handleConfirmBulkDelete = useCallback(async () => {
    const confirmation = confirmBulkDelete;
    if (!confirmation) return;
    setConfirmBulkDelete(null);
    setActionError(null);
    setIsBulkDeleting(true);
    try {
      const result = await bulkDeleteSessions(confirmation.mode, confirmation.expectedFileIds);
      await onActiveSessionDeleted?.(result.was_open, result.deleted_ids);
      setStatus((previous) =>
        previous.kind === "loaded"
          ? {
              kind: "loaded",
              sessions: previous.sessions.filter(
                (item) => !result.deleted_ids.includes(item.file_id),
              ),
            }
          : previous,
      );
      setLocalNotice(t("sessions.bulkDeleted", { count: result.deleted_count }));
      try {
        setStatus({ kind: "loaded", sessions: await listSessions() });
      } catch {
        setLocalNotice(t("sessions.bulkDeletedRefreshWarning", { count: result.deleted_count }));
      }
    } catch (err) {
      setLocalNotice(null);
      if (err instanceof ApiError && err.code === "session_deletion_inconsistent") {
        const deletedIds = Array.isArray(err.params.deleted_ids)
          ? err.params.deleted_ids.filter((value): value is string => typeof value === "string")
          : [];
        if (deletedIds.length > 0 || err.params.was_open === true) {
          await onActiveSessionDeleted?.(err.params.was_open === true, deletedIds);
        }
        setStatus((previous) =>
          previous.kind === "loaded"
            ? {
                kind: "loaded",
                sessions: previous.sessions.filter((item) => !deletedIds.includes(item.file_id)),
              }
            : previous,
        );
      }
      setActionError(localizedActionError(err, "sessions.bulkDeleteError"));
    } finally {
      setIsBulkDeleting(false);
    }
  }, [confirmBulkDelete, localizedActionError, onActiveSessionDeleted, t]);

  const beginEdit = useCallback((session: SessionSummary) => {
    setEditingFileId(session.file_id);
    setEditingDraft(session.title);
  }, []);

  const handleToggleFavorite = useCallback(
    async (session: SessionSummary, event: MouseEvent<HTMLButtonElement>) => {
      // Prevent the containing row from opening while its favorite state changes.
      event.stopPropagation();
      event.preventDefault();
      if (favoriteBusyFileId === session.file_id) return;
      setActionError(null);
      setFavoriteBusyFileId(session.file_id);
      const current = status.kind === "loaded" ? status.sessions : null;
      try {
        const updated = await setSessionFavorite(session.file_id, !session.is_favorite);
        if (current === null) return;
        setStatus((prev) => {
          if (prev.kind !== "loaded") return prev;
          const nextSessions = prev.sessions.map((s) =>
            s.file_id === updated.file_id ? updated : s,
          );
          return { kind: "loaded", sessions: nextSessions };
        });
      } catch (err) {
        setActionError(localizedActionError(err, "sessions.favoriteError"));
      } finally {
        setFavoriteBusyFileId(null);
      }
    },
    [favoriteBusyFileId, localizedActionError, status],
  );

  const cancelEdit = useCallback(() => {
    setEditingFileId(null);
    setEditingDraft("");
  }, []);

  const commitEdit = useCallback(
    async (session: SessionSummary) => {
      if (!shouldPersistTitleEdit(editingDraft, session.title)) {
        cancelEdit();
        return;
      }
      const normalized = normalizeSessionTitleInput(editingDraft);
      if (normalized === null) {
        cancelEdit();
        return;
      }
      setBusyFileId(session.file_id);
      try {
        await renameSession(session.file_id, normalized);
        cancelEdit();
        await refresh();
      } catch (err) {
        setActionError(localizedActionError(err, "sessions.renameError"));
      } finally {
        setBusyFileId(null);
      }
    },
    [editingDraft, cancelEdit, localizedActionError, refresh],
  );

  const handleEditKeyDown = (event: KeyboardEvent<HTMLInputElement>, session: SessionSummary) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void commitEdit(session);
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancelEdit();
    }
  };

  const handleEditSubmit = (event: FormEvent<HTMLFormElement>, session: SessionSummary) => {
    event.preventDefault();
    void commitEdit(session);
  };

  const renderedGroups = useMemo(() => {
    if (status.kind !== "loaded") return [];
    const filtered = filterFavoriteSessions(status.sessions, favoriteFilter);
    return groupSessionsByUpdatedDate(filtered, new Date());
  }, [status, favoriteFilter]);
  const mutationBusy = isBulkDeleting || busyFileId !== null || openingFileId !== null;

  let body: JSX.Element;
  if (status.kind === "loading") {
    body = (
      <p className="sessions-status" role="status" aria-live="polite">
        {t("sessions.loading")}
      </p>
    );
  } else if (status.kind === "error") {
    body = (
      <div className="sessions-status is-error" role="alert">
        <p>{t("sessions.loadError")}</p>
        {status.message !== t("sessions.loadError") && (
          <p className="sessions-status-detail">{status.message}</p>
        )}
        <Button variant="secondary" onClick={() => void refresh()}>
          {t("sessions.retry")}
        </Button>
      </div>
    );
  } else if (status.sessions.length === 0) {
    body = <p className="sessions-status">{t("sessions.empty")}</p>;
  } else if (renderedGroups.length === 0 && favoriteFilter === "favorites") {
    body = (
      <p className="sessions-status sessions-status-empty-favorites">{t("sessions.noFavorites")}</p>
    );
  } else {
    body = (
      <div className="sessions-groups" role="region" aria-label={t("sessions.grouped")}>
        {renderedGroups.map((group) => (
          <section
            key={group.key}
            className={`sessions-group sessions-group-${group.key}`}
            aria-labelledby={`sessions-group-${group.key}`}
          >
            <h3 id={`sessions-group-${group.key}`} className="sessions-group-heading">
              {t(
                `sessions.${group.key === "last_7_days" ? "last7" : group.key === "last_30_days" ? "last30" : group.key === "older_than_30_days" ? "older" : group.key}`,
              )}
            </h3>
            <ul
              className="sessions-list"
              aria-label={t(
                `sessions.${group.key === "last_7_days" ? "last7" : group.key === "last_30_days" ? "last30" : group.key === "older_than_30_days" ? "older" : group.key}`,
              )}
            >
              {group.sessions.map((session) => {
                const isCurrentOpen =
                  Boolean(activeFileId && session.file_id === activeFileId) || session.is_open;
                const isEditing = editingFileId === session.file_id;
                const isBusy = mutationBusy;
                const isFavoriteBusy = favoriteBusyFileId === session.file_id;
                return (
                  <li
                    key={session.file_id}
                    className={`sessions-row${isCurrentOpen ? " is-current" : ""}${
                      session.is_favorite ? " is-favorite" : ""
                    }${isEditing ? " is-editing" : ""}`}
                    data-file-id={session.file_id}
                  >
                    <div className="sessions-row-main">
                      {isEditing ? (
                        <form
                          className="sessions-title-form"
                          onSubmit={(event) => handleEditSubmit(event, session)}
                        >
                          <Input
                            ref={editingInputRef}
                            className="sessions-title-input"
                            value={editingDraft}
                            onChange={(e) => setEditingDraft(e.target.value)}
                            onKeyDown={(event) => handleEditKeyDown(event, session)}
                            aria-label={t("sessions.editTitle")}
                            maxLength={200}
                          />
                        </form>
                      ) : (
                        <button
                          type="button"
                          className="sessions-title-button"
                          onClick={() => beginEdit(session)}
                          title={t("sessions.editTitle")}
                          aria-label={`${t("sessions.editTitle")}: ${session.title}`}
                        >
                          <span className="sessions-title">{session.title}</span>
                          <MaterialSymbol
                            name="edit"
                            decorative
                            className="sessions-title-edit-icon"
                          />
                        </button>
                      )}

                      {isCurrentOpen && (
                        <span className="sessions-badge" aria-label={t("sessions.current")}>
                          {t("sessions.currentBadge")}
                        </span>
                      )}

                      <p className="sessions-meta">
                        {buildSessionMetaLine(
                          session.updated,
                          session.round_count,
                          formatLocalSessionDateTime,
                        )}
                      </p>
                    </div>

                    <div
                      className="sessions-row-actions"
                      role="group"
                      aria-label={t("sessions.actions")}
                    >
                      {isEditing ? (
                        <>
                          <Button
                            variant="primary"
                            onClick={() => void commitEdit(session)}
                            disabled={isBusy}
                          >
                            {t("common.save")}
                          </Button>
                          <Button variant="secondary" onClick={cancelEdit} disabled={isBusy}>
                            {t("common.cancel")}
                          </Button>
                        </>
                      ) : (
                        <>
                          <FavoriteToggle
                            onClick={(event) => void handleToggleFavorite(session, event)}
                            disabled={isFavoriteBusy || isBusy}
                            pressed={session.is_favorite}
                            activeLabel={t("sessions.removeFavorite")}
                            inactiveLabel={t("sessions.addFavorite")}
                          />
                          <Button
                            variant="primary"
                            className="sessions-action-open"
                            onClick={() => void handleOpen(session.file_id)}
                            disabled={isBusy}
                            loading={openingFileId === session.file_id}
                            loadingLabel={t("common.opening")}
                          >
                            {t("sessions.open")}
                          </Button>
                          <Button
                            variant="secondary"
                            onClick={() => void handleReveal(session.file_id)}
                            disabled={isBusy}
                            title={t("sessions.openFolder")}
                            aria-label={t("sessions.openFolder")}
                          >
                            <MaterialSymbol name="folder_open" decorative />{" "}
                            {t("sessions.openFolder")}
                          </Button>
                          <IconButton
                            variant="danger"
                            className="sessions-action-delete"
                            label={t("common.delete")}
                            onClick={() => handleAskDelete(session)}
                            disabled={isBusy}
                          >
                            <MaterialSymbol name="delete" decorative />
                          </IconButton>
                        </>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    );
  }

  return (
    <section className="sessions-tab" aria-label={t("sessions.title")}>
      <PageHeader
        className="sessions-tab-header"
        title={t("nav.sessions")}
        subtitle={t("sessions.subtitle")}
      />

      {visibleNotice && (
        <NoticeBanner className="sessions-notice" tone="info" onDismiss={dismissNotice}>
          {visibleNotice}
        </NoticeBanner>
      )}

      {actionError && (
        <NoticeBanner
          className="sessions-error"
          tone="error"
          onDismiss={() => setActionError(null)}
        >
          {actionError}
        </NoticeBanner>
      )}

      {status.kind === "loaded" && status.sessions.length > 0 && (
        <div className="sessions-toolbar">
          <div className="sessions-filter" role="group" aria-label={t("sessions.filter")}>
            <Button
              variant="toolbar"
              className={`sessions-filter-option${favoriteFilter === "all" ? " is-active" : ""}`}
              aria-pressed={favoriteFilter === "all"}
              onClick={() => setFavoriteFilter("all")}
              disabled={mutationBusy}
            >
              {t("sessions.all")}
            </Button>
            <Button
              variant="toolbar"
              className={`sessions-filter-option${
                favoriteFilter === "favorites" ? " is-active" : ""
              }`}
              aria-pressed={favoriteFilter === "favorites"}
              onClick={() => setFavoriteFilter("favorites")}
              disabled={mutationBusy}
            >
              {t("sessions.favorites")}
            </Button>
          </div>
          <div
            className="sessions-bulk-actions"
            role="group"
            aria-label={t("sessions.bulkActions")}
          >
            <Button
              variant="danger"
              className="sessions-action-delete"
              onClick={() => handleAskBulkDelete("all")}
              disabled={mutationBusy}
              aria-label={t("sessions.deleteAll")}
            >
              <MaterialSymbol name="delete" decorative />
              {t("sessions.bulkDeleteAllLabel")}
            </Button>
            <Button
              variant="danger"
              className="sessions-action-delete"
              onClick={() => handleAskBulkDelete("except_favorites")}
              disabled={mutationBusy || status.sessions.every((session) => session.is_favorite)}
              aria-label={t("sessions.deleteAllExceptFavorites")}
            >
              <MaterialSymbol name="delete" decorative />
              {t("sessions.bulkDeleteExceptFavoritesLabel")}
            </Button>
          </div>
        </div>
      )}

      {body}

      {confirmDelete && (
        <ConfirmDialog
          title={t("sessions.deleteTitle")}
          message={t(
            confirmDelete.is_open ? "sessions.deleteOpenMessage" : "sessions.deleteMessage",
            { title: confirmDelete.title },
          )
            .split("\n")
            .map((line, index, lines) => (
              <span key={`${line}-${index}`}>
                {line}
                {index < lines.length - 1 ? <br /> : null}
              </span>
            ))}
          cancelLabel={t("common.cancel")}
          variant="delete"
          onCancel={() => setConfirmDelete(null)}
          onConfirm={() => void handleConfirmDelete()}
        />
      )}

      {confirmBulkDelete && status.kind === "loaded" && (
        <ConfirmDialog
          title={t(
            confirmBulkDelete.mode === "all"
              ? "sessions.deleteAllTitle"
              : "sessions.deleteAllExceptFavoritesTitle",
          )}
          message={
            <>
              <div>
                {t(
                  confirmBulkDelete.mode === "all"
                    ? "sessions.deleteAllMessage"
                    : "sessions.deleteAllExceptFavoritesMessage",
                  {
                    count: confirmBulkDelete.expectedFileIds.length,
                  },
                )}
              </div>
              {status.sessions.some(
                (session) =>
                  (Boolean(activeFileId && session.file_id === activeFileId) || session.is_open) &&
                  confirmBulkDelete.expectedFileIds.includes(session.file_id),
              ) && <div>{t("sessions.bulkDeleteOpenWarning")}</div>}
            </>
          }
          cancelLabel={t("common.cancel")}
          variant="delete"
          pendingLabel={t("common.loading")}
          disabled={isBulkDeleting}
          onCancel={() => !isBulkDeleting && setConfirmBulkDelete(null)}
          onConfirm={() => void handleConfirmBulkDelete()}
        />
      )}
    </section>
  );
};

export default SessionsTab;
