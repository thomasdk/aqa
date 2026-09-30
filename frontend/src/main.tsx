/// <reference types="vite/client" />
import { initializeAppearance, waitForNativeAppearance } from "./appearance";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./i18n";
import "./styles.css";
import { hydrateApplicationPreferences } from "./uiPreferences";
import DesignSystemGallery from "./components/design-system/DesignSystemGallery";

const disposeAppearance = initializeAppearance();
if (import.meta.hot) import.meta.hot.dispose(disposeAppearance);

async function startApplication(): Promise<void> {
  const notificationPermissionAutoAttempted = await hydrateApplicationPreferences();
  await waitForNativeAppearance();
  const showDesignSystemGallery =
    window.location.pathname === "/design-system" ||
    new URLSearchParams(window.location.search).get("gallery") === "components";
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      {showDesignSystemGallery ? (
        <DesignSystemGallery />
      ) : (
        <App notificationPermissionAutoAttempted={notificationPermissionAutoAttempted} />
      )}
    </React.StrictMode>,
  );
}

void startApplication();
