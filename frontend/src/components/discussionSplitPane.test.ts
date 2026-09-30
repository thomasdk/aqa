import { describe, expect, it } from "vitest";
import {
  DISCUSSION_SPLIT_PANE_DESKTOP_BREAKPOINT,
  DISCUSSION_SPLIT_PANE_GRID_CHROME_WIDTH,
  DISCUSSION_SPLIT_PANE_MIN_WIDTH,
  DISCUSSION_SPLIT_PANE_MAX_WIDTH,
  DISCUSSION_SPLIT_PANE_MIN_WORKSPACE_WIDTH,
  clampMaterialWidth,
  computeDraggedMaterialWidth,
  getKeyboardMaterialWidth,
  getMaterialWidthLimit,
  isDesktopDiscussionLayout,
  parseStoredMaterialWidth,
} from "./discussionSplitPane";

describe("discussion split-pane width helpers", () => {
  it("exposes the 1024px desktop breakpoint constant", () => {
    expect(DISCUSSION_SPLIT_PANE_DESKTOP_BREAKPOINT).toBe(1024);
    expect(isDesktopDiscussionLayout(1024)).toBe(false);
    expect(isDesktopDiscussionLayout(1025)).toBe(true);
    expect(isDesktopDiscussionLayout(Number.NaN)).toBe(false);
  });

  it("reserves a 480px workspace and separator/grid chrome", () => {
    const maxWidth = getMaterialWidthLimit(1200);

    expect(maxWidth).toBe(DISCUSSION_SPLIT_PANE_MAX_WIDTH);
    expect(getMaterialWidthLimit(1100)).toBe(
      1100 - DISCUSSION_SPLIT_PANE_MIN_WORKSPACE_WIDTH - DISCUSSION_SPLIT_PANE_GRID_CHROME_WIDTH,
    );
    expect(getMaterialWidthLimit(1025)).toBe(513);
    expect(getMaterialWidthLimit(700)).toBe(DISCUSSION_SPLIT_PANE_MIN_WIDTH);
    expect(getMaterialWidthLimit(Number.NaN)).toBe(DISCUSSION_SPLIT_PANE_MAX_WIDTH);
    expect(clampMaterialWidth(100, maxWidth)).toBe(DISCUSSION_SPLIT_PANE_MIN_WIDTH);
    expect(clampMaterialWidth(900, maxWidth)).toBe(maxWidth);
  });

  it("recovers only a valid versioned localStorage value", () => {
    const maxWidth = getMaterialWidthLimit(1200);

    expect(parseStoredMaterialWidth('{"version":1,"width":420}', maxWidth)).toBe(420);
    expect(parseStoredMaterialWidth('{"version":1,"width":9999}', maxWidth)).toBe(maxWidth);
    expect(parseStoredMaterialWidth('{"version":2,"width":420}', maxWidth)).toBe(360);
    expect(parseStoredMaterialWidth("not-json", maxWidth)).toBe(360);
    expect(parseStoredMaterialWidth(null, maxWidth)).toBe(360);
  });

  it("maps keyboard commands to clamped width changes", () => {
    const maxWidth = getMaterialWidthLimit(1200);

    expect(getKeyboardMaterialWidth(360, "ArrowLeft", maxWidth)).toBe(344);
    expect(getKeyboardMaterialWidth(360, "ArrowRight", maxWidth)).toBe(376);
    expect(getKeyboardMaterialWidth(360, "Home", maxWidth)).toBe(DISCUSSION_SPLIT_PANE_MIN_WIDTH);
    expect(getKeyboardMaterialWidth(360, "End", maxWidth)).toBe(maxWidth);
    expect(getKeyboardMaterialWidth(360, "ArrowUp", maxWidth)).toBe(360);
  });

  it("clamps dragged widths to [MIN, container-limited max]", () => {
    const maxWidth = getMaterialWidthLimit(1200);

    expect(computeDraggedMaterialWidth(360, 60, maxWidth)).toBe(420);
    expect(computeDraggedMaterialWidth(360, -60, maxWidth)).toBe(300);
    expect(computeDraggedMaterialWidth(260, -9999, maxWidth)).toBe(DISCUSSION_SPLIT_PANE_MIN_WIDTH);
    expect(computeDraggedMaterialWidth(600, 9999, maxWidth)).toBe(maxWidth);
    expect(computeDraggedMaterialWidth(DISCUSSION_SPLIT_PANE_MIN_WIDTH, -10, maxWidth)).toBe(
      DISCUSSION_SPLIT_PANE_MIN_WIDTH,
    );
    expect(computeDraggedMaterialWidth(360, Number.NaN, maxWidth)).toBe(360);
  });
});
