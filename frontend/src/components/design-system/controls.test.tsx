import { act, createRef, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Button, Field, Input, Select, Textarea, type ButtonVariant } from "./controls";

type Mounted = {
  container: HTMLDivElement;
  root: Root;
};

const mounted: Mounted[] = [];

function mount(element: ReactElement): HTMLDivElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(element));
  mounted.push({ container, root });
  return container;
}

afterEach(() => {
  for (const entry of mounted.splice(0)) act(() => entry.root.unmount());
  document.body.replaceChildren();
});

describe("Button", () => {
  it.each<ButtonVariant>(["primary", "secondary", "danger", "dangerPrimary", "toolbar", "text"])(
    "keeps the %s variant a native button",
    (variant) => {
      const container = mount(<Button variant={variant}>Continue</Button>);
      const button = container.querySelector("button");

      expect(button).toBeInstanceOf(HTMLButtonElement);
      expect(button?.type).toBe("button");
      expect(button?.textContent).toBe("Continue");
      expect(button?.classList.contains(`ds-button--${variant}`)).toBe(true);
    },
  );

  it("forwards an explicit type, ref, properties, and click behavior", () => {
    const ref = createRef<HTMLButtonElement>();
    const onClick = vi.fn();
    const container = mount(
      <Button
        ref={ref}
        type="submit"
        name="save"
        value="now"
        aria-pressed="true"
        data-purpose="save"
        onClick={onClick}
      >
        Save
      </Button>,
    );
    const button = container.querySelector("button")!;

    expect(ref.current).toBe(button);
    expect(button.type).toBe("submit");
    expect(button.name).toBe("save");
    expect(button.value).toBe("now");
    expect(button.getAttribute("aria-pressed")).toBe("true");
    expect(button.dataset.purpose).toBe("save");
    act(() => button.click());
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("exposes loading as busy and disabled with an intentional loading name", () => {
    const onClick = vi.fn();
    const container = mount(
      <Button loading loadingLabel="Saving" onClick={onClick}>
        Save
      </Button>,
    );
    const button = container.querySelector("button")!;

    expect(button.disabled).toBe(true);
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.textContent).toBe("Saving");
    act(() => button.click());
    expect(onClick).not.toHaveBeenCalled();
  });

  it("keeps its stable name while busy when no loading label is supplied", () => {
    const container = mount(<Button loading>Save</Button>);
    expect(container.querySelector("button")?.textContent).toBe("Save");
  });

  it("exposes both documented control sizes", () => {
    const container = mount(
      <>
        <Button size="small">Small</Button>
        <Button size="medium">Medium</Button>
      </>,
    );
    const buttons = container.querySelectorAll("button");
    expect(buttons[0].classList.contains("ds-control--small")).toBe(true);
    expect(buttons[1].classList.contains("ds-control--medium")).toBe(true);
  });
});

describe("Field and form controls", () => {
  it("generates a label association and joins caller, description, and error references", () => {
    const inputRef = createRef<HTMLInputElement>();
    const onInput = vi.fn();
    const container = mount(
      <>
        <div id="external-help">External help</div>
        <Field
          label="Project Name"
          description="Shown to collaborators"
          error="Name is required"
          required
        >
          <Input
            ref={inputRef}
            name="project-name"
            aria-describedby="external-help external-help"
            data-purpose="project-name"
            onInput={onInput}
          />
        </Field>
      </>,
    );
    const input = container.querySelector<HTMLInputElement>('input[name="project-name"]')!;
    const label = container.querySelector("label")!;
    const description = container.querySelector<HTMLElement>(".ds-field__description")!;
    const error = container.querySelector<HTMLElement>('[role="alert"]')!;

    expect(inputRef.current).toBe(input);
    expect(input.id).not.toBe("");
    expect(label.htmlFor).toBe(input.id);
    expect(input.labels?.item(0)).toBe(label);
    expect(input.required).toBe(true);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")?.split(" ")).toEqual([
      "external-help",
      description.id,
      error.id,
    ]);
    expect(input.dataset.purpose).toBe("project-name");
    act(() => input.dispatchEvent(new InputEvent("input", { bubbles: true, data: "A" })));
    expect(onInput).toHaveBeenCalledOnce();
  });

  it("honors explicit association ids for a select", () => {
    const ref = createRef<HTMLSelectElement>();
    const container = mount(
      <Field
        htmlFor="model"
        label="Model"
        description="Choose a model"
        descriptionId="model-help"
        error="Choose one"
        errorId="model-error"
      >
        <Select ref={ref} defaultValue="">
          <option value="">Choose</option>
          <option value="local">Local</option>
        </Select>
      </Field>,
    );
    const select = container.querySelector("select")!;

    expect(ref.current).toBe(select);
    expect(select.id).toBe("model");
    expect(select.labels?.item(0)?.textContent).toBe("Model");
    expect(select.getAttribute("aria-describedby")).toBe("model-help model-error");
    expect(select.getAttribute("aria-invalid")).toBe("true");
  });

  it("lets an individual control deliberately override inherited required and invalid state", () => {
    const container = mount(
      <Field label="Optional Note" error="Parent validation" required>
        <Textarea required={false} invalid={false} rows={4} defaultValue="Draft" />
      </Field>,
    );
    const textarea = container.querySelector("textarea")!;

    expect(textarea.required).toBe(false);
    expect(textarea.hasAttribute("aria-invalid")).toBe(false);
    expect(textarea.rows).toBe(4);
    expect(textarea.value).toBe("Draft");
  });

  it("keeps Input, Select, and Textarea native and independently usable outside Field", () => {
    const container = mount(
      <>
        <Input aria-label="Search" invalid size="small" />
        <Select aria-label="Sort" defaultValue="recent" size="small">
          <option value="recent">Recent</option>
        </Select>
        <Textarea aria-label="Notes" defaultValue="Evidence" />
      </>,
    );
    const input = container.querySelector("input")!;
    const select = container.querySelector("select")!;
    const textarea = container.querySelector("textarea")!;

    expect(input).toBeInstanceOf(HTMLInputElement);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.classList.contains("ds-control--small")).toBe(true);
    expect(select).toBeInstanceOf(HTMLSelectElement);
    expect(select.value).toBe("recent");
    expect(select.classList.contains("ds-control--small")).toBe(true);
    expect(textarea).toBeInstanceOf(HTMLTextAreaElement);
    expect(textarea.value).toBe("Evidence");
  });
});
