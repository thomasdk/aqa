import { act, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import {
  ActionGroup,
  Card,
  DialogFooter,
  EditorDialogBody,
  EditorDialogError,
  EditorDialogForm,
  PageHeader,
  SectionHeader,
} from "./layout";

const roots: Root[] = [];

function mount(element: ReactElement): HTMLDivElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(element));
  roots.push(root);
  return container;
}

afterEach(() => {
  for (const root of roots.splice(0)) act(() => root.unmount());
  document.body.replaceChildren();
});

describe("design-system layout patterns", () => {
  it("renders a page heading, supporting copy, actions, and forwarded header properties", () => {
    const container = mount(
      <PageHeader
        title="Sessions"
        titleId="sessions-title"
        subtitle="Saved research sessions"
        actions={<button type="button">New Session</button>}
        aria-labelledby="sessions-title"
        data-purpose="sessions-header"
      />,
    );
    const header = container.querySelector("header")!;

    expect(header.getAttribute("aria-labelledby")).toBe("sessions-title");
    expect(header.dataset.purpose).toBe("sessions-header");
    expect(header.querySelector("h1")?.id).toBe("sessions-title");
    expect(header.querySelector("h1")?.textContent).toBe("Sessions");
    expect(header.querySelector("p")?.textContent).toBe("Saved research sessions");
    expect(header.querySelector("button")?.textContent).toBe("New Session");
  });

  it("uses h2 by default and supports a deliberate h3 section level", () => {
    const container = mount(
      <>
        <SectionHeader title="Models" titleId="models-title" />
        <SectionHeader title="Advanced" titleId="advanced-title" headingLevel={3} />
      </>,
    );

    expect(container.querySelector("h2")?.id).toBe("models-title");
    expect(container.querySelector("h3")?.id).toBe("advanced-title");
    expect(container.querySelectorAll("h1")).toHaveLength(0);
  });

  it("forwards optional grouping semantics without inventing them", () => {
    const container = mount(
      <>
        <ActionGroup aria-label="Session Actions" role="group" align="spread">
          <button type="button">Open</button>
          <button type="button">Delete</button>
        </ActionGroup>
        <ActionGroup data-purpose="visual-actions" />
      </>,
    );
    const groups = container.querySelectorAll<HTMLElement>(".ds-action-group");

    expect(groups[0].getAttribute("role")).toBe("group");
    expect(groups[0].getAttribute("aria-label")).toBe("Session Actions");
    expect(groups[0].querySelectorAll("button")).toHaveLength(2);
    expect(groups[1].hasAttribute("role")).toBe(false);
    expect(groups[1].dataset.purpose).toBe("visual-actions");
  });

  it("keeps Card a neutral container while forwarding deliberate properties", () => {
    const container = mount(
      <Card surface="recessed" aria-labelledby="card-title" data-purpose="result-card">
        <h3 id="card-title">Result</h3>
      </Card>,
    );
    const card = container.querySelector<HTMLElement>(".ds-card")!;

    expect(card.tagName).toBe("DIV");
    expect(card.hasAttribute("role")).toBe(false);
    expect(card.getAttribute("aria-labelledby")).toBe("card-title");
    expect(card.dataset.purpose).toBe("result-card");
    expect(card.classList.contains("ds-card--recessed")).toBe(true);
  });

  it("renders dialog actions in caller order and forwards footer properties", () => {
    const container = mount(
      <DialogFooter aria-label="Confirmation Actions" role="group" data-purpose="dialog-footer">
        <button type="button">Cancel</button>
        <button type="button">Confirm</button>
      </DialogFooter>,
    );
    const footer = container.querySelector<HTMLElement>(".ds-dialog-footer")!;

    expect(footer.getAttribute("role")).toBe("group");
    expect(footer.getAttribute("aria-label")).toBe("Confirmation Actions");
    expect(footer.dataset.purpose).toBe("dialog-footer");
    expect(Array.from(footer.querySelectorAll("button"), (button) => button.textContent)).toEqual([
      "Cancel",
      "Confirm",
    ]);
  });

  it("provides explicit editor body elements for content and native form submission", () => {
    const container = mount(
      <>
        <EditorDialogBody data-purpose="content-body">Content</EditorDialogBody>
        <EditorDialogForm id="editor-form" data-purpose="form-body">
          <input name="label" />
        </EditorDialogForm>
        <EditorDialogError data-purpose="form-error">Save failed</EditorDialogError>
      </>,
    );
    const bodies = container.querySelectorAll<HTMLElement>(".ds-editor-dialog-body");

    expect(bodies).toHaveLength(2);
    expect(bodies[0].tagName).toBe("DIV");
    expect(bodies[0].dataset.purpose).toBe("content-body");
    expect(bodies[1].tagName).toBe("FORM");
    expect(bodies[1].id).toBe("editor-form");
    expect(bodies[1].dataset.purpose).toBe("form-body");
    const error = container.querySelector<HTMLElement>(".ds-editor-dialog-error")!;
    expect(error.getAttribute("role")).toBe("alert");
    expect(error.dataset.purpose).toBe("form-error");
  });
});
