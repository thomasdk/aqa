import { act, useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { createRoot } from "react-dom/client";
import i18n from "../../i18n";
import { Field, IntegerInput } from "./controls";

function change(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  setter.call(input, value);
  act(() => input.dispatchEvent(new Event("input", { bubbles: true })));
}

async function mount() {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  function Example() {
    const [value, setValue] = useState("32768");
    return (
      <Field label="Tokens" description="Whole count">
        <IntegerInput value={value} onValueChange={setValue} min={8192} max={131072} />
      </Field>
    );
  }
  await act(async () => root.render(<Example />));
  return { container, root, input: container.querySelector("input") as HTMLInputElement };
}

afterEach(async () => {
  document.body.replaceChildren();
  await act(async () => i18n.changeLanguage("en"));
});

describe("IntegerInput", () => {
  it("groups on blur, preserves edits and selection, and changes locale without changing digits", async () => {
    await i18n.changeLanguage("en");
    const { input, root } = await mount();
    expect(input.value).toBe("32,768");
    act(() => input.focus());
    expect(input.value).toBe("32,768");
    input.setSelectionRange(1, 3);
    change(input, "31268");
    expect(input.value).toBe("31268");
    change(input, "131,072");
    expect(input.value).toBe("131,072");
    act(() => input.blur());
    expect(input.value).toBe("131,072");
    await act(async () => i18n.changeLanguage("de"));
    expect(input.value).toBe("131.072");
    await act(async () => root.unmount());
  });

  it("keeps invalid and empty drafts visible and increments only within bounds", async () => {
    await i18n.changeLanguage("en");
    const { input, root } = await mount();
    act(() => input.focus());
    change(input, "8,00");
    act(() => input.blur());
    expect(input.value).toBe("8,00");
    act(() => input.focus());
    change(input, "");
    act(() => input.blur());
    expect(input.value).toBe("");
    act(() => input.focus());
    change(input, "8192");
    act(() =>
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })),
    );
    expect(input.value).toBe("8192");
    act(() => input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true })));
    expect(input.value).toBe("8193");
    change(input, "131072");
    act(() => input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true })));
    expect(input.value).toBe("131072");
    await act(async () => root.unmount());
  });
});
