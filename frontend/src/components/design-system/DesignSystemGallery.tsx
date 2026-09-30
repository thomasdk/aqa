import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { selectPersistedLocale } from "../../uiPreferences";
import { AppearanceSelect } from "../AppearanceSelect";
import { BlockedActionHint } from "../BlockedActionHint";
import { FavoriteStar } from "../FavoriteStar";
import { IconButton } from "../IconButton";
import { MaterialSymbol } from "../MaterialSymbol";
import { Modal } from "../Modal";
import { NoticeBanner, type NoticeTone } from "../NoticeBanner";
import { PROVENANCE_CLASS, PROVENANCE_LABEL_KEYS } from "../promptConfigurationModel";
import {
  ActionGroup,
  Button,
  Card,
  ChoiceIndicator,
  DialogFooter,
  FavoriteToggle,
  Field,
  Input,
  IntegerInput,
  PageHeader,
  SectionHeader,
  Select,
  StatusBadge,
  StepMarker,
  Textarea,
} from ".";

/** Rendered reference for supported primitives, variants, and meaningful states. */
export function DesignSystemGallery() {
  const { i18n, t } = useTranslation();
  const [dismissed, setDismissed] = useState<NoticeTone[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [example, setExample] = useState("");
  const [integerExample, setIntegerExample] = useState("32768");
  const [favorite, setFavorite] = useState(false);
  const [selectedChoice, setSelectedChoice] = useState("selected");
  const dialogTriggerRef = useRef<HTMLButtonElement>(null);
  const restoreNoticesRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    document.documentElement.lang = i18n.resolvedLanguage?.startsWith("en") ? "en" : "de";
  }, [i18n.resolvedLanguage]);

  return (
    <main className="ds-gallery">
      <PageHeader
        title={t("designSystem.title")}
        subtitle={t("designSystem.subtitle")}
        actions={
          <ActionGroup align="start">
            <AppearanceSelect />
            <label className="ds-gallery__locale">
              <span>{t("designSystem.locale")}</span>
              <Select
                size="small"
                value={i18n.resolvedLanguage?.startsWith("en") ? "en" : "de"}
                onChange={(event) => void selectPersistedLocale(event.target.value as "de" | "en")}
              >
                <option value="de">{t("app.german")}</option>
                <option value="en">{t("app.english")}</option>
              </Select>
            </label>
          </ActionGroup>
        }
      />

      <nav className="ds-gallery__index" aria-label={t("designSystem.catalogNavigation")}>
        <a href="#gallery-controls-group">{t("designSystem.controlsGroup")}</a>
        <a href="#gallery-patterns-group">{t("designSystem.patternsGroup")}</a>
        <a href="#gallery-feedback-group">{t("designSystem.feedbackGroup")}</a>
        <a href="#gallery-composition-group">{t("designSystem.compositionGroup")}</a>
      </nav>

      <section className="ds-gallery__group" aria-labelledby="gallery-controls-group">
        <header className="ds-gallery__group-header">
          <h2 id="gallery-controls-group">{t("designSystem.controlsGroup")}</h2>
          <p>{t("designSystem.controlsGroupHelp")}</p>
        </header>
        <div className="ds-gallery__grid">
          <Card role="region" aria-labelledby="gallery-buttons">
            <SectionHeader
              headingLevel={3}
              titleId="gallery-buttons"
              title={t("designSystem.buttons")}
              subtitle={t("designSystem.buttonsHelp")}
            />
            <div className="ds-gallery__specimen">
              <h4>{t("designSystem.primaryActions")}</h4>
              <ActionGroup align="start">
                <Button variant="primary">{t("common.save")}</Button>
                <Button variant="secondary">{t("common.cancel")}</Button>
                <Button variant="toolbar">
                  <MaterialSymbol name="file_download" decorative /> {t("toolbar.export")}
                </Button>
                <Button variant="toolbar" className="is-active" aria-pressed="true">
                  <MaterialSymbol name="tune" decorative /> {t("setup.options")}
                </Button>
                <Button variant="text">{t("common.edit")}</Button>
              </ActionGroup>
            </div>
            <div className="ds-gallery__specimen">
              <h4>{t("designSystem.destructiveAndUnavailable")}</h4>
              <ActionGroup align="start">
                <Button variant="danger">{t("common.delete")}</Button>
                <Button variant="dangerPrimary">{t("common.delete")}</Button>
                <Button variant="secondary" size="small">
                  {t("designSystem.small")}
                </Button>
                <Button variant="secondary" disabled>
                  {t("designSystem.disabled")}
                </Button>
                <Button variant="primary" loading loadingLabel={t("common.saving")}>
                  {t("common.save")}
                </Button>
              </ActionGroup>
            </div>
            <div className="ds-gallery__specimen">
              <h4>{t("designSystem.iconActions")}</h4>
              <ActionGroup align="start">
                <IconButton label={t("common.closeNotice")}>
                  <MaterialSymbol name="close" decorative />
                </IconButton>
                <IconButton variant="danger" label={t("common.delete")}>
                  <MaterialSymbol name="delete" decorative />
                </IconButton>
                <IconButton variant="ghost" label={t("common.refresh")}>
                  <MaterialSymbol name="refresh" decorative />
                </IconButton>
                <IconButton label={t("designSystem.disabledIconAction")} disabled>
                  <MaterialSymbol name="tune" decorative />
                </IconButton>
              </ActionGroup>
            </div>
          </Card>

          <Card role="region" aria-labelledby="gallery-fields">
            <SectionHeader
              headingLevel={3}
              titleId="gallery-fields"
              title={t("designSystem.fields")}
              subtitle={t("designSystem.fieldsHelp")}
            />
            <div className="ds-gallery__fields">
              <Field
                htmlFor="gallery-input"
                label={t("sessions.editTitle")}
                description={t("designSystem.supportingText")}
              >
                <Input
                  id="gallery-input"
                  value={example}
                  onChange={(event) => setExample(event.target.value)}
                  placeholder={t("designSystem.inputPlaceholder")}
                />
              </Field>
              <Field
                htmlFor="gallery-invalid"
                label={t("setup.targetLanguage")}
                error={t("designSystem.validationMessage")}
                required
              >
                <Input id="gallery-invalid" value="" readOnly />
              </Field>
              <Field htmlFor="gallery-integer" label={t("localAi.maximumContext")}>
                <IntegerInput
                  id="gallery-integer"
                  value={integerExample}
                  onValueChange={setIntegerExample}
                  min={8192}
                  max={131072}
                />
              </Field>
              <Field htmlFor="gallery-select" label={t("setup.materialType")}>
                <Select id="gallery-select" defaultValue="text">
                  <option value="text">{t("designSystem.text")}</option>
                  <option value="markdown">{t("designSystem.markdown")}</option>
                </Select>
              </Field>
              <Field htmlFor="gallery-textarea" label={t("setup.material")}>
                <Textarea
                  id="gallery-textarea"
                  value={t("designSystem.multilineExample")}
                  readOnly
                  rows={3}
                />
              </Field>
              <Field htmlFor="gallery-disabled" label={t("designSystem.disabledField")}>
                <Input
                  id="gallery-disabled"
                  value={t("designSystem.unavailable")}
                  disabled
                  readOnly
                />
              </Field>
              <Field htmlFor="gallery-disabled-select" label={t("designSystem.disabledSelect")}>
                <Select id="gallery-disabled-select" disabled defaultValue="unavailable">
                  <option value="unavailable">{t("designSystem.unavailable")}</option>
                </Select>
              </Field>
            </div>
          </Card>
        </div>
      </section>

      <section className="ds-gallery__group" aria-labelledby="gallery-patterns-group">
        <header className="ds-gallery__group-header">
          <h2 id="gallery-patterns-group">{t("designSystem.patternsGroup")}</h2>
          <p>{t("designSystem.patternsGroupHelp")}</p>
        </header>
        <div className="ds-gallery__grid">
          <Card role="region" aria-labelledby="gallery-selection">
            <SectionHeader
              headingLevel={3}
              titleId="gallery-selection"
              title={t("designSystem.selection")}
              subtitle={t("designSystem.selectionHelp")}
            />
            <fieldset className="ds-gallery__choices">
              <legend className="visually-hidden">{t("designSystem.selection")}</legend>
              {(["selected", "available"] as const).map((choice) => (
                <label
                  key={choice}
                  className={`ds-gallery__choice${selectedChoice === choice ? " is-selected" : ""}`}
                >
                  <input
                    className="choice-radio-input"
                    type="radio"
                    name="gallery-choice"
                    value={choice}
                    checked={selectedChoice === choice}
                    onChange={() => setSelectedChoice(choice)}
                  />
                  <ChoiceIndicator selected={selectedChoice === choice} />
                  <span>
                    {t(`designSystem.choice${choice === "selected" ? "Selected" : "Available"}`)}
                  </span>
                </label>
              ))}
              <label className="ds-gallery__choice is-disabled">
                <input className="choice-radio-input" type="radio" name="gallery-choice" disabled />
                <ChoiceIndicator selected={false} />
                <span>{t("designSystem.choiceDisabled")}</span>
              </label>
            </fieldset>
            <div className="ds-gallery__favorite-row">
              <ActionGroup align="start">
                <FavoriteToggle
                  pressed={favorite}
                  activeLabel={t("designSystem.removeFavorite")}
                  inactiveLabel={t("designSystem.addFavorite")}
                  onClick={() => setFavorite((current) => !current)}
                />
                <FavoriteToggle
                  pressed={false}
                  activeLabel={t("designSystem.removeFavorite")}
                  inactiveLabel={t("designSystem.addFavorite")}
                  disabled
                />
              </ActionGroup>
              <span className="ds-gallery__favorite-status">
                <FavoriteStar isFavorite /> {t("designSystem.favoriteStatus")}
              </span>
            </div>
          </Card>

          <Card role="region" aria-labelledby="gallery-workflow">
            <SectionHeader
              headingLevel={3}
              titleId="gallery-workflow"
              title={t("designSystem.workflow")}
              subtitle={t("designSystem.workflowHelp")}
            />
            <div className="ds-gallery__native-controls">
              <ActionGroup align="start">
                <StepMarker>1</StepMarker>
                <StepMarker>
                  <MaterialSymbol name="check" decorative />
                </StepMarker>
              </ActionGroup>
              <label>
                <span>{t("designSystem.checkboxLabel")}</span>
                <input type="checkbox" defaultChecked />
              </label>
              <label>
                <span>{t("designSystem.rangeLabel")}</span>
                <input type="range" min="0" max="100" defaultValue="62" />
              </label>
              <label>
                <span>{t("designSystem.progressLabel")}</span>
                <progress value="62" max="100" />
              </label>
            </div>
          </Card>
        </div>
      </section>

      <section className="ds-gallery__group" aria-labelledby="gallery-feedback-group">
        <header className="ds-gallery__group-header">
          <h2 id="gallery-feedback-group">{t("designSystem.feedbackGroup")}</h2>
          <p>{t("designSystem.feedbackGroupHelp")}</p>
        </header>
        <Card role="region" aria-labelledby="gallery-feedback">
          <SectionHeader
            headingLevel={3}
            titleId="gallery-feedback"
            title={t("designSystem.feedback")}
          />
          <div className="ds-gallery__feedback-grid">
            <section className="ds-gallery__specimen" aria-labelledby="gallery-provenance">
              <h4 id="gallery-provenance">{t("designSystem.provenance")}</h4>
              <ActionGroup align="start">
                {(["shipped_default", "shipped_modified", "custom"] as const).map((origin) => (
                  <span key={origin} className={PROVENANCE_CLASS[origin]}>
                    {t(PROVENANCE_LABEL_KEYS[origin])}
                  </span>
                ))}
                <StatusBadge tone="info">{t("localAi.downloaded")}</StatusBadge>
                <StatusBadge tone="success">{t("localAi.running")}</StatusBadge>
              </ActionGroup>
            </section>
            <section className="ds-gallery__specimen" aria-labelledby="gallery-dismissible">
              <div className="ds-gallery__specimen-header">
                <h4 id="gallery-dismissible">{t("designSystem.dismissibleNotices")}</h4>
                <Button
                  ref={restoreNoticesRef}
                  variant="text"
                  size="small"
                  disabled={dismissed.length === 0}
                  onClick={() => setDismissed([])}
                >
                  {t("designSystem.restoreNotices")}
                </Button>
              </div>
              <div className="ds-gallery__notice-stack">
                {(["info", "success", "warning", "error"] as const)
                  .filter((tone) => !dismissed.includes(tone))
                  .map((tone) => (
                    <NoticeBanner
                      key={tone}
                      dismissReturnFocusRef={restoreNoticesRef}
                      tone={tone}
                      onDismiss={() => setDismissed((current) => [...current, tone])}
                    >
                      {t(
                        {
                          info: "designSystem.feedbackInfo",
                          success: "designSystem.feedbackSuccess",
                          warning: "designSystem.feedbackWarning",
                          error: "designSystem.feedbackError",
                        }[tone],
                      )}
                    </NoticeBanner>
                  ))}
              </div>
            </section>
            <section className="ds-gallery__specimen" aria-labelledby="gallery-persistent">
              <h4 id="gallery-persistent">{t("designSystem.persistentNotices")}</h4>
              <div className="ds-gallery__notice-stack">
                <NoticeBanner tone="warning">
                  {t("setup.aiAccess.sourceNotConfigured", { source: t("nav.network") })}
                </NoticeBanner>
                <NoticeBanner tone="warning">
                  {t("setup.aiAccess.external.disclosure")}
                </NoticeBanner>
              </div>
            </section>
            <section className="ds-gallery__specimen" aria-labelledby="gallery-blocked">
              <h4 id="gallery-blocked">{t("designSystem.blockedActionTitle")}</h4>
              <ActionGroup align="start">
                <Button variant="primary" disabled aria-describedby="gallery-blocked-hint">
                  {t("discussion.start")}
                </Button>
                <BlockedActionHint id="gallery-blocked-hint">
                  {t("designSystem.blockedAction")}
                </BlockedActionHint>
              </ActionGroup>
            </section>
          </div>
        </Card>
      </section>

      <section className="ds-gallery__group" aria-labelledby="gallery-composition-group">
        <header className="ds-gallery__group-header">
          <h2 id="gallery-composition-group">{t("designSystem.compositionGroup")}</h2>
          <p>{t("designSystem.compositionGroupHelp")}</p>
        </header>
        <div className="ds-gallery__grid">
          <Card surface="recessed" role="region" aria-labelledby="gallery-layout">
            <SectionHeader
              headingLevel={3}
              titleId="gallery-layout"
              title={t("designSystem.layoutPatterns")}
              subtitle={t("designSystem.layoutHelp")}
              actions={<Button variant="secondary">{t("common.edit")}</Button>}
            />
            <ActionGroup align="spread">
              <span>{t("designSystem.leadingContent")}</span>
              <Button variant="primary">{t("common.save")}</Button>
            </ActionGroup>
            <ActionGroup align="end">
              <Button variant="secondary">{t("common.cancel")}</Button>
              <Button variant="primary">{t("common.save")}</Button>
            </ActionGroup>
          </Card>

          <Card role="region" aria-labelledby="gallery-dialogs">
            <SectionHeader
              headingLevel={3}
              titleId="gallery-dialogs"
              title={t("designSystem.dialogs")}
              subtitle={t("designSystem.dialogsHelp")}
            />
            <Button ref={dialogTriggerRef} variant="secondary" onClick={() => setDialogOpen(true)}>
              {t("designSystem.openDialog")}
            </Button>
          </Card>
        </div>
      </section>

      {dialogOpen && (
        <Modal
          labelledBy="gallery-dialog-title"
          onClose={() => setDialogOpen(false)}
          returnFocusRef={dialogTriggerRef}
        >
          <h2 id="gallery-dialog-title">{t("designSystem.dialogTitle")}</h2>
          <p className="modal-message">{t("designSystem.dialogMessage")}</p>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setDialogOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button variant="primary" onClick={() => setDialogOpen(false)}>
              {t("common.save")}
            </Button>
          </DialogFooter>
        </Modal>
      )}
    </main>
  );
}

export default DesignSystemGallery;
