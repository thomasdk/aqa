/* eslint-disable jsx-a11y-x/no-noninteractive-tabindex -- Named overflow regions need keyboard scrolling. */
import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import MaterialSymbol from "./MaterialSymbol";
import { IconButton } from "./IconButton";
import { ConfirmDialog, Modal } from "./Modal";
import NoticeBanner from "./NoticeBanner";
import {
  ActionGroup,
  Button,
  DialogFooter,
  EditorDialogBody,
  EditorDialogError,
  Field,
  Input,
  PageHeader,
  Textarea,
} from "./design-system";
import {
  listRoles,
  createRole,
  updateRole,
  deleteRole,
  restoreDefaultRole,
  revealRolesDirectory,
  ApiError,
  type RoleCreatePayload,
  type RoleUpdatePayload,
} from "../api";
import type { Role, RoleOrigin } from "./types";
import { hasNativeManagedPathReveal, revealManagedPath } from "../desktopBridge";

type RoleFormData = {
  id: string;
  label: string;
  role: string;
  task: string;
  output_format: string;
  description: string;
};

const EMPTY_FORM: RoleFormData = {
  id: "",
  label: "",
  role: "",
  task: "",
  output_format: "",
  description: "",
};

const PROVENANCE_CLASS: Record<RoleOrigin, string> = {
  shipped_default: "rm-badge rm-badge--shipped-default",
  shipped_modified: "rm-badge rm-badge--shipped-modified",
  custom: "rm-badge rm-badge--custom",
};

const SESSION_TYPE_KEY_RE = /^[a-z][a-z0-9_]*$/;

function safeSessionTypeDependencyLabels(err: ApiError): string[] {
  const dependencies = err.params.session_types;
  if (!Array.isArray(dependencies)) return [];

  const labels = new Map<string, string>();
  for (const dependency of dependencies) {
    if (typeof dependency !== "object" || dependency === null) continue;
    const item = dependency as { key?: unknown; label?: unknown };
    if (typeof item.key !== "string") continue;
    const key = item.key.trim();
    if (!SESSION_TYPE_KEY_RE.test(key)) continue;
    const label = typeof item.label === "string" ? item.label.trim() : "";
    // Labels are user-authored, so reject control characters rather than
    // rendering backend-provided text that could hide or distort the list.
    const hasUnsafeLabelCharacters = [...label].some((character) => {
      const code = character.charCodeAt(0);
      return code < 32 || code === 127;
    });
    const safeLabel =
      label && !/[\\/]/.test(label) && !hasUnsafeLabelCharacters && label.length <= 160
        ? label
        : key;
    labels.set(key, `${safeLabel} (${key})`);
  }
  return [...labels.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([, label]) => label);
}

type RoleManagerProps = {
  /** Refresh the parent after persistence; rejection does not roll back saved data. */
  onRolesChanged: () => void | Promise<void>;
};

const RoleManager = ({ onRolesChanged }: RoleManagerProps) => {
  const { t, i18n } = useTranslation();
  const perspectivesFolderLabel = t("prompts.openPerspectivesFolder");
  const actionError = useCallback(
    (err: unknown, fallbackKey: string, params: Record<string, unknown> = {}): string => {
      if (err instanceof ApiError && err.code) {
        if (err.code === "role_referenced_by_session_types") {
          const dependencies = safeSessionTypeDependencyLabels(err);
          return dependencies.length > 0
            ? t("prompts.deleteRoleDependencyError", { sessionTypes: dependencies.join(", ") })
            : t("prompts.deleteRoleDependencyGeneric");
        }
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // A parent refresh failure does not invalidate the completed backend save.
  const [parentSyncError, setParentSyncError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<RoleFormData>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [idError, setIdError] = useState<string | null>(null);
  const [labelError, setLabelError] = useState<string | null>(null);
  const [roleError, setRoleError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState("");
  const labelInputRef = useRef<HTMLInputElement>(null);
  const roleInputRef = useRef<HTMLTextAreaElement>(null);
  const newButtonRef = useRef<HTMLButtonElement>(null);

  // Serialize role restoration with other form mutations.
  const [resettingId, setResettingId] = useState<string | null>(null);
  const [showSingleResetConfirm, setShowSingleResetConfirm] = useState(false);
  const [singleResetTarget, setSingleResetTarget] = useState<Role | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null);
  const [deleting, setDeleting] = useState(false);
  const actionErrorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (error) actionErrorRef.current?.focus();
  }, [error]);

  const [revealingRolesDirectory, setRevealingRolesDirectory] = useState(false);

  const handleRevealRolesDirectory = async () => {
    setStatusMessage("");
    setRevealingRolesDirectory(true);
    setError(null);
    try {
      if (hasNativeManagedPathReveal()) {
        await revealManagedPath("perspectives");
      } else {
        await revealRolesDirectory();
      }
      setStatusMessage(t("prompts.rolesFolderOpenedStatus"));
    } catch (err) {
      setError(actionError(err, "prompts.revealRolesFolderError"));
    } finally {
      setRevealingRolesDirectory(false);
    }
  };

  const loadRoles = useCallback(
    async (announce = true) => {
      setLoading(true);
      setError(null);
      try {
        const data = await listRoles();
        setRoles(data);
        if (announce) {
          setStatusMessage(
            data.length === 0
              ? t("prompts.rolesEmptyStatus")
              : t("prompts.rolesLoaded", { count: data.length }),
          );
        }
      } catch (err) {
        setError(actionError(err, "errors.rolesLoad"));
      } finally {
        setLoading(false);
      }
    },
    [actionError, t],
  );

  useEffect(() => {
    loadRoles();
  }, [loadRoles]);

  const openNew = () => {
    setForm(EMPTY_FORM);
    setIdError(null);
    setLabelError(null);
    setRoleError(null);
    setFormError(null);
    setEditingId(null);
    setShowModal(true);
  };

  const openEdit = (role: Role) => {
    setForm({
      id: role.id,
      label: role.label,
      role: role.role ?? "",
      task: role.task ?? "",
      output_format: role.output_format ?? "",
      description: role.description ?? "",
    });
    setEditingId(role.id);
    setIdError(null);
    setLabelError(null);
    setRoleError(null);
    setFormError(null);
    setShowModal(true);
  };

  const handleField = (field: keyof RoleFormData, value: string) => {
    if (field === "id") {
      setIdError(
        value.trim() && !/^[a-z][a-z0-9_]*$/.test(value.trim()) ? t("prompts.invalidInput") : null,
      );
    }
    if (field === "label") setLabelError(null);
    if (field === "role") setRoleError(null);
    setFormError(null);
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  // Call only after the local role catalogue has reloaded successfully.
  const notifyParent = useCallback(async (): Promise<void> => {
    try {
      await onRolesChanged();
      setParentSyncError(null);
    } catch {
      setParentSyncError(t("prompts.setupSyncNotice"));
    }
  }, [onRolesChanged, t]);

  const handleSave = async () => {
    setStatusMessage("");
    const normalizedId = form.id.trim();
    if (editingId === null && !/^[a-z][a-z0-9_]*$/.test(normalizedId)) {
      setIdError(t("prompts.invalidInput"));
      document.getElementById("perspective-id")?.focus();
      return;
    }
    if (!form.label.trim()) {
      setLabelError(t("errors.displayNameRequired"));
      labelInputRef.current?.focus();
      return;
    }
    if (!form.role.trim()) {
      setRoleError(t("errors.roleInstructionRequired"));
      roleInputRef.current?.focus();
      return;
    }
    setSaving(true);
    setError(null);
    setParentSyncError(null);
    try {
      if (editingId === null) {
        const payload: RoleCreatePayload = {
          id: form.id.trim(),
          label: form.label.trim(),
          role: form.role,
          task: form.task || null,
          output_format: form.output_format || null,
          description: form.description.trim() || null,
        };
        await createRole(payload);
      } else {
        const payload: RoleUpdatePayload = {};
        if (form.label !== roles.find((r) => r.id === editingId)?.label)
          payload.label = form.label.trim();
        if (form.role !== roles.find((r) => r.id === editingId)?.role) payload.role = form.role;
        if (form.task !== (roles.find((r) => r.id === editingId)?.task ?? ""))
          payload.task = form.task || null;
        if (form.output_format !== (roles.find((r) => r.id === editingId)?.output_format ?? ""))
          payload.output_format = form.output_format || null;
        if (form.description !== (roles.find((r) => r.id === editingId)?.description ?? ""))
          payload.description = form.description.trim() || null;
        await updateRole(editingId, payload);
      }
      const savedLabel = form.label.trim();
      setShowModal(false);
      await loadRoles(false);
      await notifyParent();
      setStatusMessage(t("prompts.roleSavedStatus", { label: savedLabel }));
    } catch (err) {
      setFormError(actionError(err, "errors.save"));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (role: Role) => {
    setDeleteTarget(role);
  };

  const confirmDelete = async () => {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    setError(null);
    setStatusMessage("");
    setParentSyncError(null);
    try {
      await deleteRole(deleteTarget.id);
      await loadRoles(false);
      await notifyParent();
      setDeleteTarget(null);
      setStatusMessage(t("prompts.roleDeletedStatus", { label: deleteTarget.label }));
    } catch (err) {
      // Close the confirmation first so a dependency conflict is visible and
      // focusable in the page-level banner rather than hidden behind the modal.
      setDeleteTarget(null);
      setError(actionError(err, "errors.delete"));
    } finally {
      setDeleting(false);
    }
  };

  const askSingleReset = (role: Role) => {
    setSingleResetTarget(role);
    setShowSingleResetConfirm(true);
  };

  const handleConfirmSingleReset = async () => {
    if (!singleResetTarget) return;
    const target = singleResetTarget;
    setShowSingleResetConfirm(false);
    setSingleResetTarget(null);
    setResettingId(target.id);
    setStatusMessage("");
    setError(null);
    setParentSyncError(null);
    try {
      await restoreDefaultRole(target.id);
      await loadRoles(false);
      await notifyParent();
      setStatusMessage(t("prompts.roleRestoredStatus", { label: target.label }));
    } catch (err) {
      setError(actionError(err, "prompts.restoreRoleError", { label: target.label }));
    } finally {
      setResettingId(null);
    }
  };

  const isBusy = saving || resettingId !== null;
  return (
    <div className="role-manager">
      <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {statusMessage}
      </div>
      <PageHeader
        className="rm-header"
        title={t("nav.roles")}
        actions={
          <>
            <Button
              onClick={handleRevealRolesDirectory}
              disabled={isBusy || revealingRolesDirectory}
              title={perspectivesFolderLabel}
              aria-label={
                revealingRolesDirectory ? t("prompts.openingRolesFolder") : perspectivesFolderLabel
              }
            >
              {revealingRolesDirectory ? (
                t("prompts.openingRolesFolder")
              ) : (
                <>
                  <MaterialSymbol name="folder_open" decorative /> {perspectivesFolderLabel}
                </>
              )}
            </Button>
            <Button ref={newButtonRef} variant="primary" onClick={openNew} disabled={isBusy}>
              + {t("prompts.newRole")}
            </Button>
          </>
        }
      />

      {error && (
        <NoticeBanner
          ref={actionErrorRef}
          className="error-banner"
          dismissReturnFocusRef={newButtonRef}
          tone="error"
          tabIndex={-1}
          onDismiss={() => setError(null)}
        >
          {error}
        </NoticeBanner>
      )}

      {parentSyncError && !error && (
        <NoticeBanner
          className="error-banner rm-parent-sync-error"
          dismissReturnFocusRef={newButtonRef}
          tone="warning"
          aria-label={t("prompts.setupSyncNoticeLabel")}
          onDismiss={() => setParentSyncError(null)}
        >
          {parentSyncError}
        </NoticeBanner>
      )}

      {loading ? (
        <div className="rm-loading">{t("prompts.loadingRoles")}</div>
      ) : roles.length === 0 ? (
        <div className="rm-empty">{t("prompts.noRoles")}</div>
      ) : (
        // This table overflows locally at narrow widths, so its scroll owner must be keyboard reachable.
        // eslint-disable-next-line jsx-a11y-x/no-noninteractive-tabindex
        <div
          className="rm-table-scroll"
          role="region"
          aria-label={t("prompts.rolesTitle")}
          tabIndex={0}
        >
          <table className="rm-table">
            <thead>
              <tr>
                <th>{t("prompts.id")}</th>
                <th>{t("prompts.displayName")}</th>
                <th>{t("prompts.origin")}</th>
                <th>{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {roles.map((r) => {
                const origin: RoleOrigin =
                  r.origin ?? (r.is_shipped ? "shipped_modified" : "custom");
                const provenanceClass = PROVENANCE_CLASS[origin];
                const provenanceLabel =
                  origin === "shipped_default"
                    ? t("common.default")
                    : origin === "shipped_modified"
                      ? t("prompts.changed")
                      : t("prompts.customRole");
                const isResetting = resettingId === r.id;
                const showReset = r.is_shipped === true;
                const isAlreadyBaseline = origin === "shipped_default";
                const resetDisabled = isBusy || isAlreadyBaseline;
                const resetTitle = isAlreadyBaseline
                  ? t("prompts.alreadyDefault")
                  : t("prompts.resetRole", { label: r.label });
                return (
                  <tr key={r.id}>
                    <td className="rm-cell-id">{r.id}</td>
                    <td>{r.label}</td>
                    <td>
                      <span
                        className={provenanceClass}
                        title={
                          origin === "shipped_default"
                            ? t("prompts.shippedRoleDefault")
                            : origin === "shipped_modified"
                              ? t("prompts.shippedRoleModified")
                              : t("prompts.customRoleOrigin")
                        }
                      >
                        {provenanceLabel}
                      </span>
                    </td>
                    <td className="rm-cell-actions">
                      <ActionGroup className="rm-actions" align="start">
                        {showReset && (
                          <Button
                            variant="text"
                            onClick={() => askSingleReset(r)}
                            disabled={resetDisabled}
                            title={resetTitle}
                            aria-label={`${t("prompts.restoreDefault")} — ${r.label}`}
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
                        {r.editable ? (
                          <>
                            <Button onClick={() => openEdit(r)} disabled={isBusy}>
                              {t("common.edit")}
                            </Button>
                            <IconButton
                              variant="danger"
                              label={t("prompts.deleteRoleAction", { label: r.label })}
                              onClick={() => handleDelete(r)}
                              disabled={isBusy}
                            >
                              <MaterialSymbol name="delete" decorative />
                            </IconButton>
                          </>
                        ) : (
                          !showReset && (
                            <span className="rm-readonly-label">{t("prompts.readonly")}</span>
                          )
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

      {showModal && (
        <Modal
          className="rm-modal"
          layout="editor"
          labelledBy="role-modal-title"
          onClose={() => !saving && setShowModal(false)}
        >
          <h2 id="role-modal-title">
            {editingId === null ? t("prompts.newRoleTitle") : t("prompts.editRoleTitle")}
          </h2>
          {formError && <EditorDialogError>{formError}</EditorDialogError>}
          <EditorDialogBody className="rm-form">
            {editingId === null ? (
              <Field
                className="rm-form-row"
                htmlFor="perspective-id"
                label={t("prompts.id")}
                description={t("prompts.idHint")}
                descriptionId="perspective-id-hint"
                error={idError}
                errorId="perspective-id-error"
              >
                <Input
                  id="perspective-id"
                  value={form.id}
                  onChange={(e) => handleField("id", e.target.value)}
                  placeholder={t("prompts.roleIdPlaceholder")}
                  disabled={saving}
                />
              </Field>
            ) : (
              <div className="rm-form-row">
                <span className="rm-form-label">{t("prompts.id")}</span>
                <code className="pcm-immutable-id">{editingId}</code>
              </div>
            )}
            <Field
              className="rm-form-row"
              htmlFor="perspective-label"
              label={t("prompts.displayName")}
              error={labelError}
              errorId="perspective-label-error"
            >
              <Input
                id="perspective-label"
                ref={labelInputRef}
                value={form.label}
                onChange={(e) => handleField("label", e.target.value)}
                placeholder={t("prompts.roleLabelPlaceholder")}
                disabled={saving}
              />
            </Field>
            <Field
              className="rm-form-row"
              htmlFor="perspective-description"
              label={t("prompts.perspectiveDescription")}
              description={t("prompts.perspectiveDescriptionHint")}
            >
              <Textarea
                id="perspective-description"
                className="rm-textarea"
                value={form.description}
                onChange={(e) => handleField("description", e.target.value)}
                rows={2}
                placeholder={t("prompts.perspectiveDescriptionPlaceholder")}
                disabled={saving}
              />
            </Field>
            <Field
              className="rm-form-row"
              htmlFor="perspective-role"
              label={t("prompts.role")}
              error={roleError}
              errorId="perspective-role-error"
            >
              <Textarea
                id="perspective-role"
                ref={roleInputRef}
                className="rm-textarea"
                value={form.role}
                onChange={(e) => handleField("role", e.target.value)}
                rows={4}
                placeholder={t("prompts.rolePlaceholder")}
                disabled={saving}
              />
            </Field>
            <Field className="rm-form-row" htmlFor="perspective-task" label={t("prompts.task")}>
              <Textarea
                id="perspective-task"
                className="rm-textarea"
                value={form.task}
                onChange={(e) => handleField("task", e.target.value)}
                rows={4}
                placeholder={t("prompts.taskPlaceholder")}
                disabled={saving}
              />
            </Field>
            <Field
              className="rm-form-row"
              htmlFor="perspective-output-format"
              label={t("prompts.outputFormat")}
            >
              <Textarea
                id="perspective-output-format"
                className="rm-textarea"
                value={form.output_format}
                onChange={(e) => handleField("output_format", e.target.value)}
                rows={3}
                placeholder={t("prompts.outputPlaceholder")}
                disabled={saving}
              />
            </Field>
          </EditorDialogBody>
          <DialogFooter>
            <Button onClick={() => setShowModal(false)} disabled={saving}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="primary"
              disabled={
                saving ||
                (editingId === null &&
                  (!form.id.trim() || !/^[a-z][a-z0-9_]*$/.test(form.id.trim())))
              }
              loading={saving}
              loadingLabel={t("common.saving")}
              onClick={handleSave}
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </Modal>
      )}

      {showSingleResetConfirm && singleResetTarget && (
        <ConfirmDialog
          title={t("prompts.restoreDefaultTitle")}
          message={
            <>
              <p>{t("prompts.restoreRoleBody", { label: singleResetTarget.label })}</p>
              <p>{t("prompts.otherRolesUnaffected")}</p>
            </>
          }
          cancelLabel={t("common.cancel")}
          confirmLabel={t("prompts.restoreNow")}
          pendingLabel={t("prompts.restoring")}
          disabled={resettingId === singleResetTarget.id}
          onCancel={() => setShowSingleResetConfirm(false)}
          onConfirm={handleConfirmSingleReset}
        />
      )}

      {deleteTarget && (
        <ConfirmDialog
          title={t("prompts.deleteRoleTitle")}
          message={t("prompts.deleteRoleConfirm", { label: deleteTarget.label })}
          cancelLabel={t("common.cancel")}
          variant="delete"
          onCancel={() => setDeleteTarget(null)}
          onConfirm={() => void confirmDelete()}
          disabled={deleting}
          pendingLabel={t("common.deleting")}
          returnFocusRef={newButtonRef}
        />
      )}
    </div>
  );
};

export default RoleManager;
export type { RoleManagerProps };
