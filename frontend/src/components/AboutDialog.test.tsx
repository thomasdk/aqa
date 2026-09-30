import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import AboutDialog from "./AboutDialog";

let root: Root | null = null;

afterEach(async () => {
  if (root) act(() => root?.unmount());
  root = null;
  document.body.replaceChildren();
  await setLocale("de");
});

function Fixture() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open About
      </button>
      {open && <AboutDialog onClose={() => setOpen(false)} />}
    </>
  );
}

describe("AboutDialog", () => {
  it("shows the exact project credits and safe shared links in both locales", async () => {
    await setLocale("en");
    const container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root?.render(<Fixture />));

    const opener = container.querySelector("button") as HTMLButtonElement;
    opener.focus();
    act(() => opener.click());

    const dialog = container.querySelector('[role="dialog"]') as HTMLDivElement;
    expect(dialog.getAttribute("aria-labelledby")).toBe("about-dialog-title");
    expect(dialog.textContent).toContain("About AQA");
    expect(dialog.textContent).toContain("Augmented Qualitative Analysis");
    expect(dialog.textContent).toContain(
      "AI as critical friend: Softwaregestützte dialogische Analyse zur Augmentation qualitativer Analysen (AQA)",
    );
    expect(dialog.textContent).toContain("Thomas Krause");
    expect(dialog.textContent).toContain("Sebastian Bornschlegl");
    expect(dialog.textContent).toContain("Susanne Vogl");
    expect(dialog.textContent).toContain("Laura Niess");
    expect(dialog.textContent).toContain("Jakob Funk");
    expect(dialog.textContent).toContain("Carla Menke");
    expect(dialog.textContent).toContain("Lasse Binder");
    expect(dialog.textContent).toContain("Institute for Social Sciences");
    expect(dialog.textContent).toContain("Sociology and Empirical Social Research");
    expect(dialog.textContent).toContain("University of Stuttgart");
    expect(dialog.querySelector<HTMLImageElement>(".about-dialog-logo")?.src).toContain(
      "favicon.svg",
    );
    expect(dialog.textContent).toContain("Copyright © 2026 Thomas Krause");
    expect(dialog.textContent).toContain("MIT License");

    const universityLink = dialog.querySelector<HTMLAnchorElement>("a");
    expect(universityLink?.href).toBe(
      "https://www.sowi.uni-stuttgart.de/abteilungen/ses/forschung/augmented-qualitative-analysis-aqa/",
    );
    expect(universityLink?.target).toBe("_blank");
    expect(universityLink?.rel).toBe("noopener noreferrer");
    expect(dialog.querySelectorAll("a")).toHaveLength(1);
    expect(dialog.querySelector('[aria-disabled="true"]')?.textContent).toBe("Unavailable");
    expect(dialog.textContent).toContain("The repository address has not been assigned yet.");

    await act(async () => setLocale("de"));
    expect(dialog.textContent).toContain("Über AQA");
    expect(dialog.textContent).toContain("Institut für Sozialwissenschaften");
    expect(dialog.textContent).toContain(
      "Abteilung für Soziologie mit Schwerpunkt sozialwissenschaftliche Forschungsmethoden",
    );
    expect(dialog.textContent).toContain("Universität Stuttgart");
    expect(dialog.textContent).toContain("Die Repository-Adresse wurde noch nicht festgelegt.");

    const close = Array.from(dialog.querySelectorAll("button")).find(
      (button) => button.textContent === "Schließen",
    ) as HTMLButtonElement;
    act(() => close.click());
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});
