import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { MaterialSymbol, type MaterialSymbolName } from "./MaterialSymbol";
import { radioGroupTargetIndex } from "./radioGroupNavigation";

export const WORKBENCH_VIEWS = [
  "setup",
  "discussion",
  "network",
  "local-ai",
  "roles",
  "preview",
  "system",
  "sessions",
] as const;

export type WorkbenchView = (typeof WORKBENCH_VIEWS)[number];

type ViewNavigationProps = {
  view: WorkbenchView;
  onNavigate: (view: WorkbenchView) => void;
};

const primaryViews: Array<{ view: WorkbenchView; label: string; icon: MaterialSymbolName }> = [
  { view: "setup", label: "nav.setup", icon: "tune" },
  { view: "discussion", label: "nav.discussion", icon: "forum" },
  { view: "sessions", label: "nav.continue", icon: "history" },
];

const configurationViews: Array<{
  view: WorkbenchView;
  label: string;
  icon: MaterialSymbolName;
}> = [
  { view: "local-ai", label: "nav.localAi", icon: "memory" },
  { view: "network", label: "nav.network", icon: "hub" },
  { view: "roles", label: "nav.roles", icon: "badge" },
  { view: "preview", label: "nav.preview", icon: "preview" },
  { view: "system", label: "nav.system", icon: "settings" },
];

const configurationViewIds = new Set(configurationViews.map((item) => item.view));

const ViewNavigation = ({ view, onNavigate }: ViewNavigationProps) => {
  const { t } = useTranslation();
  const configurationMenuRef = useRef<HTMLDivElement>(null);
  const configurationMenuButtonRef = useRef<HTMLButtonElement>(null);
  const [configurationMenuOpen, setConfigurationMenuOpen] = useState(false);
  const isConfigurationActive = configurationViewIds.has(view);

  useEffect(() => {
    if (!configurationMenuOpen) return;
    const closeWhenOutside = (event: PointerEvent) => {
      if (!configurationMenuRef.current?.contains(event.target as Node)) {
        setConfigurationMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeWhenOutside);
    return () => document.removeEventListener("pointerdown", closeWhenOutside);
  }, [configurationMenuOpen]);

  const navigateTo = (destination: WorkbenchView) => {
    const returnFocus = configurationMenuRef.current?.contains(document.activeElement) ?? false;
    onNavigate(destination);
    setConfigurationMenuOpen(false);
    if (returnFocus) configurationMenuButtonRef.current?.focus();
  };

  const focusConfigurationItem = (index: number) => {
    const items = configurationMenuRef.current?.querySelectorAll<HTMLButtonElement>(
      ".configuration-menu-panel .configuration-menu-item",
    );
    items?.[index]?.focus();
  };

  return (
    <div className="primary-navigation">
      <div className="primary-navigation-main" role="group" aria-label={t("app.navigation")}>
        {primaryViews.map((item) => (
          <button
            key={item.view}
            type="button"
            className={`view-tab ${view === item.view ? "is-active" : ""}`}
            data-view={item.view}
            onClick={() => navigateTo(item.view)}
            aria-current={view === item.view ? "page" : undefined}
          >
            <MaterialSymbol name={item.icon} decorative />
            {t(item.label)}
          </button>
        ))}

        <div
          className={`configuration-menu ${isConfigurationActive ? "is-active" : ""} ${configurationMenuOpen ? "is-open" : ""}`}
          ref={configurationMenuRef}
        >
          <button
            ref={configurationMenuButtonRef}
            type="button"
            className="view-tab"
            data-configure-menu
            aria-expanded={configurationMenuOpen}
            aria-haspopup="menu"
            aria-controls="configuration-menu-panel"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setConfigurationMenuOpen(false);
                return;
              }
              if (!configurationMenuOpen && (event.key === "Enter" || event.key === " ")) {
                event.preventDefault();
                setConfigurationMenuOpen(true);
                queueMicrotask(() => focusConfigurationItem(0));
                return;
              }
              if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
              event.preventDefault();
              setConfigurationMenuOpen(true);
              queueMicrotask(() =>
                focusConfigurationItem(
                  event.key === "ArrowDown" ? 0 : configurationViews.length - 1,
                ),
              );
            }}
            onClick={() => setConfigurationMenuOpen((open) => !open)}
          >
            <MaterialSymbol name="settings" decorative />
            <span>{t("nav.configure")}</span>
            <MaterialSymbol name="more_horiz" decorative className="configuration-menu-chevron" />
          </button>
          <div
            className="configuration-menu-panel"
            id="configuration-menu-panel"
            role="menu"
            tabIndex={-1}
            aria-label={t("nav.configure")}
            hidden={!configurationMenuOpen}
            onKeyDown={(event) => {
              if (event.key === "Tab") {
                setConfigurationMenuOpen(false);
                return;
              }
              if (event.key === "Escape") {
                event.preventDefault();
                setConfigurationMenuOpen(false);
                configurationMenuButtonRef.current?.focus();
                return;
              }
              const items = Array.from(
                event.currentTarget.querySelectorAll<HTMLButtonElement>(".configuration-menu-item"),
              );
              const currentIndex = items.indexOf(document.activeElement as HTMLButtonElement);
              const targetIndex = radioGroupTargetIndex(event.key, currentIndex, items.length);
              if (targetIndex === null) return;
              event.preventDefault();
              items[targetIndex]?.focus();
            }}
          >
            {configurationViews.map((item) => (
              <button
                key={item.view}
                type="button"
                role="menuitem"
                tabIndex={-1}
                className={`configuration-menu-item ${view === item.view ? "is-active" : ""}`}
                data-view={item.view}
                onClick={() => navigateTo(item.view)}
                aria-current={view === item.view ? "page" : undefined}
              >
                <MaterialSymbol name={item.icon} decorative />
                <span>{t(item.label)}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default ViewNavigation;
