import { useTranslation } from "react-i18next";
import type { RefObject } from "react";
import appIcon from "../assets/favicon.svg";
import { localeTag } from "../i18n";
import { formatReleaseDate, releaseInfo } from "../releaseInfo";
import { Modal } from "./Modal";
import { Button, DialogFooter, EditorDialogBody } from "./design-system";

const PROJECT_TITLE =
  "AI as critical friend: Softwaregestützte dialogische Analyse zur Augmentation qualitativer Analysen (AQA)";
const CONTRIBUTORS = ["Thomas Krause", "Sebastian Bornschlegl", "Susanne Vogl"];
const ASSISTANTS = ["Laura Niess", "Jakob Funk", "Carla Menke", "Lasse Binder"];
const AFFILIATIONS = {
  de: [
    "Institut für Sozialwissenschaften",
    "Abteilung für Soziologie mit Schwerpunkt sozialwissenschaftliche Forschungsmethoden",
    "Universität Stuttgart",
  ],
  en: [
    "Institute for Social Sciences",
    "Sociology and Empirical Social Research",
    "University of Stuttgart",
  ],
} as const;

type AboutDialogProps = {
  onClose: () => void;
  returnFocusRef?: RefObject<HTMLElement | null>;
};

export default function AboutDialog({ onClose, returnFocusRef }: AboutDialogProps) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage?.startsWith("en") ? "en" : "de";
  const releaseDate = releaseInfo.releaseDate
    ? formatReleaseDate(releaseInfo.releaseDate, localeTag(i18n.resolvedLanguage))
    : t("release.dateUnassigned");

  return (
    <Modal
      className="about-dialog"
      layout="editor"
      labelledBy="about-dialog-title"
      onClose={onClose}
      returnFocusRef={returnFocusRef}
    >
      <h2 id="about-dialog-title">{t("about.title")}</h2>
      <EditorDialogBody>
        <header className="about-dialog-brand">
          <img src={appIcon} alt="" className="about-dialog-logo" />
          <div>
            <p className="about-dialog-name">AQA</p>
            <p className="about-dialog-subtitle">{t("app.tagline")}</p>
            <p className="about-dialog-release-summary">
              {t("release.versionValue", { version: releaseInfo.version })}
              <span aria-hidden="true"> · </span>
              {t(`release.status.${releaseInfo.releaseStatus}`)}
            </p>
            <p className="about-dialog-release-date">
              {t("release.dateLabel")}: {releaseDate}
            </p>
          </div>
        </header>

        <section aria-labelledby="about-project-title">
          <h3 id="about-project-title">{t("about.projectTitleLabel")}</h3>
          <p lang="de">{PROJECT_TITLE}</p>
        </section>

        <div className="about-dialog-columns">
          <section aria-labelledby="about-contributors-title">
            <h3 id="about-contributors-title">{t("about.contributorsLabel")}</h3>
            <ul>
              {CONTRIBUTORS.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          </section>
          <section aria-labelledby="about-assistants-title">
            <h3 id="about-assistants-title">{t("about.assistantsLabel")}</h3>
            <ul>
              {ASSISTANTS.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          </section>
        </div>

        <section aria-labelledby="about-affiliation-title">
          <h3 id="about-affiliation-title">{t("about.affiliationLabel")}</h3>
          <address lang={language}>
            {AFFILIATIONS[language].map((line) => (
              <span key={line}>{line}</span>
            ))}
          </address>
        </section>

        <section aria-labelledby="about-links-title">
          <h3 id="about-links-title">{t("about.linksLabel")}</h3>
          <dl className="release-links">
            <div>
              <dt>{t("about.universityProjectLink")}</dt>
              <dd>
                <a
                  href={releaseInfo.links.universityProject}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {t("about.openUniversityProject")}
                </a>
              </dd>
            </div>
            <div>
              <dt>{t("release.githubLabel")}</dt>
              <dd>
                {releaseInfo.links.githubRepository ? (
                  <a
                    href={releaseInfo.links.githubRepository}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t("release.openGithub")}
                  </a>
                ) : (
                  <>
                    <span className="release-link-unavailable" aria-disabled="true">
                      {t("release.unavailable")}
                    </span>
                    <span className="release-link-explanation">
                      {t("release.githubUnavailable")}
                    </span>
                  </>
                )}
              </dd>
            </div>
          </dl>
        </section>

        <footer className="about-dialog-legal">
          <p>{releaseInfo.copyright}</p>
          <p>{releaseInfo.license}</p>
        </footer>
      </EditorDialogBody>
      <DialogFooter>
        <Button variant="primary" onClick={onClose}>
          {t("common.close")}
        </Button>
      </DialogFooter>
    </Modal>
  );
}
