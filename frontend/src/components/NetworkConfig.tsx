/* eslint-disable jsx-a11y-x/no-noninteractive-tabindex -- Named overflow regions need keyboard scrolling. */
import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import MaterialSymbol from "./MaterialSymbol";
import { FavoriteStar } from "./FavoriteStar";
import { IconButton } from "./IconButton";
import { ConfirmDialog, Modal } from "./Modal";
import NoticeBanner from "./NoticeBanner";
import {
  ActionGroup,
  Button,
  Card,
  DialogFooter,
  EditorDialogBody,
  EditorDialogError,
  FavoriteToggle,
  Field,
  Input,
  IntegerInput,
  PageHeader,
} from "./design-system";
import {
  listHosts,
  createHost,
  updateHost,
  deleteHost,
  previewHostDeletion,
  testHost,
  testDraftHost,
} from "../api";
import type { HostDeletePreview, HostInfo, HostUpdatePayload, TestHostResponse } from "../api";
import { normalizeModelNames } from "./hostModelSelection";
import { displayModelName } from "./displayNames";
import { formatNumber, parseLocalizedInteger, translateClientError } from "../i18n";
import {
  setPreferredModel,
  reconcileEditModelRow,
  reconcileRemoveModelRow,
} from "./networkModelPreference";

type ModalMode = "create" | "edit" | null;

type FormState = {
  label: string;
  url: string;
  model: string;
  models: string[];
  api_key: string;
  is_favorite: boolean;
  model_context_tokens: Record<string, number>;
};

const EMPTY_FORM: FormState = {
  label: "",
  url: "",
  model: "",
  // A new host always starts with its first model row. The first valid row
  // becomes preferred, so there is no separate orphan "preferred model"
  // control to keep in sync.
  models: [""],
  api_key: "",
  is_favorite: false,
  model_context_tokens: {},
};

const normalizedContextTokenLimits = (
  models: readonly string[],
  limits: Record<string, number>,
): Record<string, number> =>
  Object.fromEntries(
    models
      .map((model) => model.trim())
      .filter((model) => model.length > 0)
      .flatMap((model) => {
        const value = limits[model];
        return Number.isInteger(value) && value > 0 ? [[model, value]] : [];
      }),
  );

const validExternalContext = (value: string, language?: string): number | null => {
  const parsed = parseLocalizedInteger(value, language);
  return parsed !== null && parsed > 0 ? parsed : null;
};

type NetworkConfigProps = {
  onHostsChanged?: () => void | Promise<void>;
  getDraftDependencies?: (host: HostInfo) => HostDraftDependencies;
};

export type HostDraftDependencies = {
  defaultAssignments: string[];
  explicitAssignments: string[];
  defaultSynthesis: boolean;
  explicitSynthesis: boolean;
};

const EMPTY_DRAFT_DEPENDENCIES: HostDraftDependencies = {
  defaultAssignments: [],
  explicitAssignments: [],
  defaultSynthesis: false,
  explicitSynthesis: false,
};

type DeleteTarget = {
  preview: HostDeletePreview;
  draft: HostDraftDependencies;
};

const hasValidHostUrl = (value: string): boolean => {
  try {
    const parsed = new URL(value.trim());
    return (
      (parsed.protocol === "http:" || parsed.protocol === "https:") && Boolean(parsed.hostname)
    );
  } catch {
    return false;
  }
};

const NetworkConfig = ({ onHostsChanged, getDraftDependencies }: NetworkConfigProps) => {
  const { t, i18n } = useTranslation();
  const [hosts, setHosts] = useState<HostInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState("");
  const hostRequestRef = useRef(0);
  const actionErrorRef = useRef<HTMLDivElement>(null);
  const addButtonRef = useRef<HTMLButtonElement>(null);

  const [modalMode, setModalMode] = useState<ModalMode>(null);
  const [editHostId, setEditHostId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [contextDrafts, setContextDrafts] = useState<Record<number, string>>({});
  const [showApiKey, setShowApiKey] = useState(false);
  const [clearStoredApiKey, setClearStoredApiKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestHostResponse | null>(null);
  const [modalError, setModalError] = useState<string | null>(null);
  const [labelError, setLabelError] = useState<string | null>(null);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [modelError, setModelError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [deletePreviewBusyId, setDeletePreviewBusyId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [preferredHostBusyId, setPreferredHostBusyId] = useState<string | null>(null);
  const testRequestRef = useRef(0);
  const deletePreviewRequestRef = useRef(0);
  const labelInputRef = useRef<HTMLInputElement>(null);
  const urlInputRef = useRef<HTMLInputElement>(null);
  const firstModelInputRef = useRef<HTMLInputElement>(null);
  const editIndex = editHostId
    ? hosts.findIndex((host) => host.configuration_id === editHostId)
    : -1;
  const editingHost = editIndex >= 0 ? hosts[editIndex] : undefined;

  const fetchHosts = useCallback(
    async (announce = true) => {
      const requestId = ++hostRequestRef.current;
      setLoading(true);
      setError(null);
      try {
        const data = await listHosts();
        if (hostRequestRef.current !== requestId) return;
        setHosts(data);
        if (announce) {
          const externalCount = data.filter((host) => host.kind !== "local_ai").length;
          setStatusMessage(
            externalCount === 0
              ? t("network.hostsEmptyStatus")
              : t("network.hostsLoaded", { count: externalCount }),
          );
        }
      } catch (err) {
        if (hostRequestRef.current !== requestId) return;
        setError(translateClientError(err, "errors.hostsLoad"));
      } finally {
        if (hostRequestRef.current === requestId) setLoading(false);
      }
    },
    [t],
  );

  useEffect(() => {
    fetchHosts();
  }, [fetchHosts]);

  useEffect(() => {
    if (error) actionErrorRef.current?.focus();
  }, [error]);

  const openCreate = () => {
    testRequestRef.current += 1;
    setModalMode("create");
    setEditHostId(null);
    setForm(EMPTY_FORM);
    setContextDrafts({});
    setClearStoredApiKey(false);
    setShowApiKey(false);
    setTestResult(null);
    setModalError(null);
    setLabelError(null);
    setUrlError(null);
    setModelError(null);
  };

  const openEdit = (index: number) => {
    const host = hosts[index];
    if (!host) return;
    testRequestRef.current += 1;
    // Stored credentials are deliberately never fetched into the browser.
    // A non-empty entry replaces the key; clearing is an explicit action.
    setModalMode("edit");
    setEditHostId(host.configuration_id);
    setForm({
      label: host.label,
      url: host.url,
      model: host.model,
      models: [...host.models],
      api_key: "",
      is_favorite: Boolean(host.is_favorite),
      model_context_tokens: host.model_context_tokens ?? {},
    });
    setContextDrafts({});
    setShowApiKey(false);
    setTestResult(null);
    setClearStoredApiKey(false);
    setModalError(null);
    setLabelError(null);
    setUrlError(null);
    setModelError(null);
  };

  const closeModal = () => {
    if (saving) return;
    testRequestRef.current += 1;
    setModalMode(null);
    setEditHostId(null);
    setForm(EMPTY_FORM);
    setClearStoredApiKey(false);
    setShowApiKey(false);
    setSaving(false);
    setTesting(false);
    setTestResult(null);
    setModalError(null);
    setLabelError(null);
    setUrlError(null);
    setModelError(null);
  };

  const invalidateConnectionTest = () => {
    testRequestRef.current += 1;
    setTesting(false);
    setTestResult(null);
  };

  const showUrlError = () => {
    setUrlError(t("network.invalidUrl"));
    setModalError(null);
    urlInputRef.current?.focus();
  };

  const isHostUrlApiError = (err: unknown): boolean =>
    typeof err === "object" && err !== null && "code" in err && err.code === "host_url_invalid";

  const handleSave = async () => {
    setStatusMessage("");
    setLabelError(null);
    setModelError(null);
    if (!hasValidHostUrl(form.url)) {
      showUrlError();
      return;
    }
    if (!form.label.trim()) {
      setLabelError(t("network.labelRequired"));
      setModalError(null);
      labelInputRef.current?.focus();
      return;
    }
    if (!form.model.trim()) {
      setModelError(t("network.modelRequired"));
      setModalError(null);
      firstModelInputRef.current?.focus();
      return;
    }
    const invalidContextRow = form.models.findIndex((model, index) => {
      const draft = contextDrafts[index];
      return Boolean(
        model.trim() && draft && validExternalContext(draft, i18n.resolvedLanguage) === null,
      );
    });
    if (invalidContextRow >= 0) {
      document.getElementById(`nc-model-context-${invalidContextRow}`)?.focus();
      return;
    }
    setSaving(true);
    setModalError(null);
    setUrlError(null);
    try {
      if (modalMode === "create") {
        await createHost({
          label: form.label.trim(),
          url: form.url.trim(),
          model: form.model.trim(),
          models: normalizeModelNames(form.model, form.models),
          api_key: form.api_key || null,
          is_favorite: form.is_favorite,
          model_context_tokens: normalizedContextTokenLimits(
            form.models,
            form.model_context_tokens,
          ),
        });
      } else if (modalMode === "edit") {
        if (editIndex < 0 || !editingHost) {
          setModalError(t("network.hostUnavailable"));
          return;
        }
        const payload: HostUpdatePayload = {
          configuration_id: editingHost.configuration_id,
        };
        if (form.label.trim() !== editingHost.label) payload.label = form.label.trim();
        if (form.url.trim() !== editingHost.url) payload.url = form.url.trim();
        if (form.model.trim() !== editingHost.model) payload.model = form.model.trim();
        const normalizedModels = normalizeModelNames(form.model, form.models);
        if (JSON.stringify(normalizedModels) !== JSON.stringify(editingHost.models))
          payload.models = normalizedModels;
        if (form.api_key) payload.api_key = form.api_key;
        if (clearStoredApiKey) payload.api_key = null;
        if (form.is_favorite !== Boolean(editingHost.is_favorite)) {
          payload.is_favorite = form.is_favorite;
        }
        const contextLimits = normalizedContextTokenLimits(form.models, form.model_context_tokens);
        const savedLimits = editingHost.model_context_tokens ?? {};
        if (JSON.stringify(contextLimits) !== JSON.stringify(savedLimits)) {
          payload.model_context_tokens = contextLimits;
        }
        await updateHost(editIndex, payload);
      }
      const savedLabel = form.label.trim();
      await fetchHosts(false);
      await onHostsChanged?.();
      closeModal();
      setStatusMessage(t("network.hostSavedStatus", { label: savedLabel }));
    } catch (err) {
      if (isHostUrlApiError(err)) {
        showUrlError();
      } else {
        setModalError(translateClientError(err, "errors.hostSave"));
      }
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (index: number) => {
    const host = hosts[index];
    if (!host) return;
    const requestId = ++deletePreviewRequestRef.current;
    setDeletePreviewBusyId(host.configuration_id);
    setError(null);
    try {
      const preview = await previewHostDeletion({ label: host.configuration_id });
      if (deletePreviewRequestRef.current !== requestId) return;
      setDeleteTarget({
        preview,
        draft: getDraftDependencies?.(host) ?? EMPTY_DRAFT_DEPENDENCIES,
      });
    } catch (err) {
      if (deletePreviewRequestRef.current !== requestId) return;
      setError(translateClientError(err, "errors.hostDelete"));
    } finally {
      if (deletePreviewRequestRef.current === requestId) setDeletePreviewBusyId(null);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setStatusMessage("");
    setError(null);
    try {
      await deleteHost({
        label: deleteTarget.preview.label,
        revision: deleteTarget.preview.revision,
      });
      setHosts((previous) =>
        previous.filter((host) => host.configuration_id !== deleteTarget.preview.label),
      );
      const deletedLabel = deleteTarget.preview.label;
      setDeleteTarget(null);
      try {
        await fetchHosts(false);
        await onHostsChanged?.();
        setStatusMessage(t("network.hostDeletedStatus", { label: deletedLabel }));
      } catch {
        setError(t("network.deleteRefreshWarning"));
      }
    } catch (err) {
      setDeleteTarget(null);
      setError(translateClientError(err, "errors.hostDelete"));
      if (
        typeof err === "object" &&
        err !== null &&
        "code" in err &&
        err.code === "host_catalog_changed"
      ) {
        try {
          const currentHosts = await listHosts();
          setHosts(currentHosts);
          await onHostsChanged?.();
        } catch {
          setError(t("network.deleteRefreshWarning"));
        } finally {
          setDeleteTarget(null);
        }
      }
    } finally {
      setDeleting(false);
    }
  };

  const handleTogglePreferredHost = async (host: HostInfo, index: number) => {
    if (preferredHostBusyId !== null) return;
    setError(null);
    setStatusMessage("");
    setPreferredHostBusyId(host.configuration_id);
    try {
      const makePreferred = !host.is_favorite;
      await updateHost(index, {
        configuration_id: host.configuration_id,
        is_favorite: makePreferred,
      });
      await fetchHosts(false);
      await onHostsChanged?.();
      setStatusMessage(
        t(makePreferred ? "network.preferredHostSet" : "network.preferredHostCleared", {
          label: host.label,
        }),
      );
    } catch (err) {
      setError(translateClientError(err, "errors.hostSave"));
    } finally {
      setPreferredHostBusyId(null);
    }
  };

  const handleTest = async () => {
    if (modalMode !== "create" && modalMode !== "edit") return;
    if (!hasValidHostUrl(form.url)) {
      showUrlError();
      return;
    }
    if (modalMode === "edit" && (editIndex < 0 || !editingHost)) {
      setModalError(t("network.hostUnavailable"));
      return;
    }
    const hostBeingTested = editingHost;
    const requestId = ++testRequestRef.current;
    setTesting(true);
    setTestResult(null);
    setModalError(null);
    setUrlError(null);
    try {
      let result: TestHostResponse;
      if (modalMode === "create") {
        result = await testDraftHost({ url: form.url.trim(), api_key: form.api_key || null });
      } else {
        if (!hostBeingTested) return;
        result = await testHost(editIndex, {
          configuration_id: hostBeingTested.configuration_id,
          url: form.url.trim(),
          api_key: form.api_key || null,
        });
      }
      if (testRequestRef.current !== requestId) return;
      setTestResult({
        ...result,
        message: t(result.ok ? "network.connectionEstablished" : "network.connectionFailed"),
      });
    } catch (err) {
      if (testRequestRef.current !== requestId) return;
      if (isHostUrlApiError(err)) {
        showUrlError();
        return;
      }
      setTestResult({
        ok: false,
        code: "connection_failed",
        message: translateClientError(err, "errors.hostTest"),
        models: [],
      });
    } finally {
      if (testRequestRef.current === requestId) setTesting(false);
    }
  };

  // The API addresses hosts by their position in the complete list. Keep the
  // original index with every external row so an integrated host never shifts
  // an edit, test, or delete request to the wrong external host.
  const externalHosts = hosts
    .map((host, index) => ({ host, index }))
    .filter(({ host }) => host.kind !== "local_ai");
  const saveDisabled = saving || testing;

  return (
    <div className="network-config">
      <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {statusMessage}
      </div>
      <PageHeader
        className="nc-header"
        title={t("network.title")}
        actions={
          <Button ref={addButtonRef} variant="primary" onClick={openCreate}>
            + {t("common.add")}
          </Button>
        }
      />

      {error && (
        <NoticeBanner
          ref={actionErrorRef}
          className="error-banner"
          dismissReturnFocusRef={addButtonRef}
          tone="error"
          tabIndex={-1}
          onDismiss={() => setError(null)}
        >
          {error}
        </NoticeBanner>
      )}

      {loading ? (
        <p className="nc-loading">{t("network.loading")}</p>
      ) : externalHosts.length === 0 ? (
        <p className="nc-empty">{t("network.empty")}</p>
      ) : (
        // The narrow-layout scroll region must accept focus for keyboard scrolling.
        // eslint-disable-next-line jsx-a11y-x/no-noninteractive-tabindex
        <div className="nc-table-scroll" role="region" aria-label={t("network.title")} tabIndex={0}>
          <table className="nc-table">
            <thead>
              <tr>
                <th>{t("network.label")}</th>
                <th>{t("network.url")}</th>
                <th>{t("network.model")}</th>
                <th>{t("network.contextWindow")}</th>
                <th>{t("network.preferred")}</th>
                <th>{t("network.apiKey")}</th>
                <th>{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {externalHosts.map(({ host, index }) => (
                <tr key={host.configuration_id}>
                  <td>{host.label}</td>
                  <td className="nc-cell-mono">{host.url}</td>
                  <td className="nc-cell-mono">{displayModelName(host.model)}</td>
                  <td>
                    {host.model_context_tokens?.[host.model]
                      ? t("network.contextWindowValue", {
                          count: formatNumber(host.model_context_tokens[host.model]),
                        })
                      : "—"}
                  </td>
                  <td className="nc-favorite-cell">
                    <FavoriteToggle
                      className={`nc-host-preference-toggle ${
                        host.is_favorite ? "nc-favorite-yes" : "nc-favorite-no"
                      }`}
                      pressed={Boolean(host.is_favorite)}
                      activeLabel={t("network.clearPreferredHost", { label: host.label })}
                      inactiveLabel={t("network.setPreferredHost", { label: host.label })}
                      disabled={preferredHostBusyId !== null}
                      onClick={(event) => {
                        event.stopPropagation();
                        void handleTogglePreferredHost(host, index);
                      }}
                    />
                  </td>
                  <td>
                    {host.has_api_key ? (
                      <span
                        className="nc-key-present"
                        aria-label={t("network.apiKeySet")}
                        title={t("network.apiKeySet")}
                      >
                        <MaterialSymbol name="check" decorative />
                      </span>
                    ) : (
                      <span className="nc-key-missing">—</span>
                    )}
                  </td>
                  <td>
                    <ActionGroup className="nc-actions" align="start">
                      <Button onClick={() => openEdit(index)}>{t("common.edit")}</Button>
                      <IconButton
                        variant="danger"
                        label={t("network.deleteHostAction", { label: host.label })}
                        disabled={deletePreviewBusyId !== null}
                        aria-busy={deletePreviewBusyId === host.configuration_id || undefined}
                        onClick={() => handleDelete(index)}
                      >
                        <MaterialSymbol name="delete" decorative />
                      </IconButton>
                    </ActionGroup>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modalMode && (
        <Modal
          className="nc-modal"
          layout="editor"
          labelledBy="nc-modal-title"
          onClose={closeModal}
          initialFocusRef={urlInputRef}
        >
          <h2 id="nc-modal-title">
            {modalMode === "create"
              ? t("network.addHost")
              : t("network.editHost", { label: editingHost?.label ?? form.label })}
          </h2>

          {modalError && (
            <EditorDialogError className="nc-form-error">{modalError}</EditorDialogError>
          )}

          <EditorDialogBody className="nc-form">
            <Field
              className="nc-form-row"
              htmlFor="nc-host-label"
              label={t("network.label")}
              error={labelError}
              errorId="nc-host-label-error"
            >
              <Input
                id="nc-host-label"
                ref={labelInputRef}
                value={form.label}
                onChange={(e) => {
                  setLabelError(null);
                  setForm((f) => ({ ...f, label: e.target.value }));
                }}
                placeholder={t("network.labelPlaceholder")}
                disabled={saving}
              />
            </Field>

            <Card
              className="nc-editor-card nc-connection-section"
              role="region"
              aria-labelledby="nc-connection-heading"
            >
              <div className="nc-section-heading">
                <h3 id="nc-connection-heading">{t("network.connection")}</h3>
                <p>{t("network.connectionHint")}</p>
                <p className="nc-connection-disclosure">{t("network.transmissionDisclosure")}</p>
              </div>

              <Field
                className="nc-form-row"
                htmlFor="nc-host-url"
                label={t("network.url")}
                error={urlError}
                errorId="nc-host-url-error"
              >
                <Input
                  id="nc-host-url"
                  ref={urlInputRef}
                  value={form.url}
                  onChange={(e) => {
                    invalidateConnectionTest();
                    setUrlError(null);
                    setForm((f) => ({ ...f, url: e.target.value }));
                  }}
                  placeholder={t("network.urlPlaceholder")}
                  disabled={saving}
                />
              </Field>

              <Field className="nc-form-row" htmlFor="nc-host-api-key" label={t("network.apiKey")}>
                <div className="nc-api-key-row">
                  <Input
                    id="nc-host-api-key"
                    className="nc-api-key-input"
                    type={showApiKey ? "text" : "password"}
                    value={form.api_key}
                    onChange={(e) => {
                      invalidateConnectionTest();
                      setClearStoredApiKey(false);
                      setForm((f) => ({ ...f, api_key: e.target.value }));
                    }}
                    placeholder={
                      modalMode === "edit" && editingHost?.has_api_key
                        ? t("network.replaceApiKey")
                        : t("common.optional")
                    }
                    disabled={saving}
                  />
                  <IconButton
                    className="nc-toggle-btn"
                    onClick={() => setShowApiKey((s) => !s)}
                    label={showApiKey ? t("network.hideApiKey") : t("network.showApiKey")}
                    disabled={saving}
                  >
                    <MaterialSymbol
                      name={showApiKey ? "visibility_off" : "visibility"}
                      decorative
                    />
                  </IconButton>
                  {modalMode === "edit" && editingHost?.has_api_key && (
                    <IconButton
                      className="nc-clear-key-control"
                      variant="danger"
                      disabled={clearStoredApiKey || saving}
                      onClick={() => {
                        invalidateConnectionTest();
                        setClearStoredApiKey(true);
                        setForm((f) => ({ ...f, api_key: "" }));
                      }}
                      label={t("network.removeStoredKey")}
                    >
                      <MaterialSymbol name="delete" decorative />
                    </IconButton>
                  )}
                </div>
              </Field>

              <Button
                className="nc-test-connection-btn"
                disabled={saving}
                loading={testing}
                loadingLabel={t("common.loading")}
                onClick={handleTest}
              >
                {t("network.testConnection")}
              </Button>
            </Card>

            {testResult && (
              <div
                className={`nc-test-result ${testResult.ok ? "nc-test-ok" : "nc-test-fail"}`}
                role="status"
                aria-live="polite"
                aria-atomic="true"
              >
                <strong>
                  {testResult.ok ? (
                    <MaterialSymbol name="check" decorative className="nc-test-result-icon" />
                  ) : (
                    <MaterialSymbol name="warning" decorative className="nc-test-result-icon" />
                  )}{" "}
                  {testResult.ok ? t("network.success") : t("common.error")}
                </strong>
                <p>{testResult.message}</p>
                {testResult.models.length > 0 && (
                  <div className="nc-test-models">
                    <strong>{t("network.testModelsHeading")}</strong>
                    <p>{t("network.testModelsHint")}</p>
                    {/* A long discovered-model list scrolls locally and must accept keyboard focus. */}
                    {/* eslint-disable-next-line jsx-a11y-x/no-noninteractive-tabindex */}
                    <ul
                      className="nc-test-model-list"
                      aria-label={t("network.liveModels")}
                      tabIndex={0}
                    >
                      {testResult.models.map((m) => (
                        <li key={m}>{m}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            <div className="nc-form-row nc-model-editor">
              <div className="nc-section-heading">
                <h3 id="nc-models-heading">{t("network.models")}</h3>
                <p>{t("network.modelsHint")}</p>
              </div>
              <div className="nc-model-rows" aria-labelledby="nc-models-heading">
                {form.models.map((model, modelIndex) => {
                  const isPreferred = Boolean(model.trim()) && model === form.model;
                  const modelInputId = `nc-model-id-${modelIndex}`;
                  const contextInputId = `nc-model-context-${modelIndex}`;
                  return (
                    <Card className="nc-editor-card nc-model-row" key={modelIndex}>
                      <Field
                        className="nc-model-field nc-model-id-field"
                        htmlFor={modelInputId}
                        label={t("network.modelId")}
                        error={modelIndex === 0 ? modelError : null}
                        errorId={modelIndex === 0 ? "nc-model-id-error" : undefined}
                      >
                        <Input
                          id={modelInputId}
                          ref={modelIndex === 0 ? firstModelInputRef : undefined}
                          value={model}
                          onChange={(e) => {
                            setModelError(null);
                            setForm((f: FormState) => {
                              const previousModel = f.models[modelIndex]?.trim();
                              const nextModel = e.target.value.trim();
                              const next = reconcileEditModelRow(f, modelIndex, e.target.value);
                              if (!previousModel || previousModel === nextModel) return next;
                              const { [previousModel]: movedLimit, ...remainingLimits } =
                                f.model_context_tokens;
                              return {
                                ...next,
                                model_context_tokens:
                                  nextModel && movedLimit
                                    ? { ...remainingLimits, [nextModel]: movedLimit }
                                    : remainingLimits,
                              };
                            });
                          }}
                          aria-label={`${t("network.modelId")} ${modelIndex + 1}`}
                          placeholder={t("network.modelIdPlaceholder")}
                          disabled={saving || testing}
                        />
                      </Field>
                      <Field
                        className="nc-model-field nc-context-window-field"
                        htmlFor={contextInputId}
                        label={t("network.contextWindowOptional")}
                        error={
                          contextDrafts[modelIndex] &&
                          validExternalContext(contextDrafts[modelIndex], i18n.resolvedLanguage) ===
                            null
                            ? t("network.contextWindowInvalid")
                            : undefined
                        }
                      >
                        <IntegerInput
                          id={contextInputId}
                          className="nc-context-window-input"
                          min={1}
                          value={
                            model.trim()
                              ? (contextDrafts[modelIndex] ??
                                String(form.model_context_tokens[model.trim()] ?? ""))
                              : ""
                          }
                          onValueChange={(value) => {
                            const key = model.trim();
                            setContextDrafts((drafts) => ({ ...drafts, [modelIndex]: value }));
                            setForm((f) => {
                              if (!key) return f;
                              const next = { ...f.model_context_tokens };
                              const parsed = validExternalContext(value, i18n.resolvedLanguage);
                              if (value === "") {
                                delete next[key];
                              } else if (parsed !== null) {
                                next[key] = parsed;
                              }
                              return { ...f, model_context_tokens: next };
                            });
                          }}
                          aria-label={t("network.contextWindowForModel", {
                            number: modelIndex + 1,
                          })}
                          placeholder={t("network.contextWindowPlaceholder")}
                          disabled={saving || testing || !model.trim()}
                        />
                      </Field>
                      <div className="nc-model-row-actions">
                        {isPreferred ? (
                          <span
                            className="nc-model-preference-status"
                            aria-label={t("network.defaultModel")}
                            title={t("network.defaultModel")}
                          >
                            <FavoriteStar isFavorite />
                          </span>
                        ) : (
                          <FavoriteToggle
                            className="nc-model-preference-toggle"
                            onClick={() => setForm((f: FormState) => setPreferredModel(f, model))}
                            pressed={false}
                            activeLabel={t("network.defaultModel")}
                            inactiveLabel={t("network.setDefaultModel")}
                            disabled={saving || testing || !model.trim()}
                          />
                        )}
                        <IconButton
                          className="nc-model-remove-btn"
                          variant="danger"
                          onClick={() => {
                            setForm((f: FormState) => reconcileRemoveModelRow(f, modelIndex));
                            setContextDrafts((drafts) =>
                              Object.fromEntries(
                                Object.entries(drafts)
                                  .filter(([index]) => Number(index) !== modelIndex)
                                  .map(([index, draft]) => [
                                    Number(index) > modelIndex ? Number(index) - 1 : Number(index),
                                    draft,
                                  ]),
                              ),
                            );
                          }}
                          label={t("network.removeModel", { number: modelIndex + 1 })}
                          disabled={saving || testing}
                        >
                          <MaterialSymbol name="delete" decorative />
                        </IconButton>
                      </div>
                    </Card>
                  );
                })}
              </div>
              <ActionGroup className="nc-model-actions" align="start">
                <Button
                  onClick={() => setForm((f) => ({ ...f, models: [...f.models, ""] }))}
                  disabled={saving || testing}
                >
                  {t("network.addModel")}
                </Button>
              </ActionGroup>
            </div>

            <label className="checkbox nc-favorite-control">
              <input
                type="checkbox"
                checked={form.is_favorite}
                onChange={(e) => setForm((f) => ({ ...f, is_favorite: e.target.checked }))}
                disabled={saving || testing}
              />
              <span>{t("network.usePreferredHost")}</span>
            </label>
          </EditorDialogBody>

          <DialogFooter className="nc-modal-actions">
            <Button onClick={closeModal} disabled={saving}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="primary"
              disabled={saveDisabled}
              loading={saving}
              loadingLabel={t("common.saving")}
              onClick={handleSave}
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </Modal>
      )}

      {deleteTarget && (
        <ConfirmDialog
          title={t("network.deleteTitle")}
          message={
            <div className="nc-delete-impact">
              <p>{t("network.deleteConfirm", { label: deleteTarget.preview.label })}</p>
              <p>{t("network.deleteWarningSummary")}</p>
            </div>
          }
          cancelLabel={t("common.cancel")}
          variant="delete"
          onCancel={() => setDeleteTarget(null)}
          onConfirm={() => void confirmDelete()}
          disabled={deleting}
          returnFocusRef={addButtonRef}
        />
      )}
    </div>
  );
};

export default NetworkConfig;
