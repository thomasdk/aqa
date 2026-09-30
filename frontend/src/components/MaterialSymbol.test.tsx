import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MaterialSymbol, MATERIAL_SYMBOL_ICON_NAMES } from "./MaterialSymbol";

const ALL_ICON_NAMES = [
  "account_tree",
  "add",
  "add_comment",
  "arrow_downward",
  "arrow_upward",
  "badge",
  "center_focus_strong",
  "check",
  "close",
  "delete",
  "edit",
  "error",
  "file_download",
  "folder_open",
  "forum",
  "help",
  "history",
  "hub",
  "info",
  "lock",
  "memory",
  "more_horiz",
  "note",
  "pending",
  "preview",
  "refresh",
  "reply",
  "schedule",
  "search",
  "settings",
  "south_east",
  "star",
  "star_border",
  "stop",
  "tune",
  "visibility",
  "visibility_off",
  "warning",
  "water_drop",
] as const;

describe("MaterialSymbol icon-name union", () => {
  it("exposes the closed union of supported icon names", () => {
    expect(new Set(MATERIAL_SYMBOL_ICON_NAMES)).toEqual(new Set(ALL_ICON_NAMES));
  });

  it("contains exactly the 39 AQA icons", () => {
    expect(MATERIAL_SYMBOL_ICON_NAMES).toHaveLength(39);
  });
});

describe("MaterialSymbol rendering", () => {
  it("renders a span with the material-symbol class and the icon ligature", () => {
    const html = renderToStaticMarkup(<MaterialSymbol name="search" decorative />);

    expect(html).toMatch(/^<span[^>]*>search<\/span>$/);
    expect(html).toMatch(/class="material-symbol"/);
  });

  it("marks decorative icons aria-hidden and omits the role/label", () => {
    const html = renderToStaticMarkup(<MaterialSymbol name="add" decorative />);

    expect(html).toMatch(/aria-hidden="true"/);
    expect(html).not.toMatch(/aria-label=/);
    expect(html).not.toMatch(/role="img"/);
  });

  it("renders role=img and aria-label for non-decorative icons", () => {
    const html = renderToStaticMarkup(
      <MaterialSymbol name="warning" decorative={false} label="Something went wrong" />,
    );

    expect(html).toMatch(/role="img"/);
    expect(html).toMatch(/aria-label="Something went wrong"/);
    expect(html).not.toMatch(/aria-hidden="true"/);
  });

  it("forwards an optional className to the span", () => {
    const html = renderToStaticMarkup(
      <MaterialSymbol name="settings" decorative className="icon-spinner" />,
    );

    expect(html).toMatch(/class="material-symbol icon-spinner"/);
  });

  it("renders the exact ligature text for every supported icon", () => {
    for (const name of ALL_ICON_NAMES) {
      const html = renderToStaticMarkup(<MaterialSymbol name={name} decorative />);
      expect(html).toContain(`>${name}</span>`);
    }
  });

  it("throws a clear error when a non-decorative icon is missing its label", () => {
    expect(() =>
      renderToStaticMarkup(<MaterialSymbol name="help" decorative={false} />),
    ).toThrowError(/label/i);
  });

  it("throws a clear error when a non-decorative icon is given an empty label", () => {
    expect(() =>
      renderToStaticMarkup(<MaterialSymbol name="help" decorative={false} label="" />),
    ).toThrowError(/label/i);
  });

  it("throws a clear error when a non-decorative icon is given a whitespace-only label", () => {
    expect(() =>
      renderToStaticMarkup(<MaterialSymbol name="help" decorative={false} label="   " />),
    ).toThrowError(/label/i);
  });
});
