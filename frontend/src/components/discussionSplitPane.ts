export const DISCUSSION_SPLIT_PANE_STORAGE_KEY = "aqa:discussion-split-pane:v1";
export const DISCUSSION_SPLIT_PANE_STORAGE_VERSION = 1;
export const DISCUSSION_SPLIT_PANE_MIN_WIDTH = 240;
export const DISCUSSION_SPLIT_PANE_MAX_WIDTH = 640;
export const DISCUSSION_SPLIT_PANE_INITIAL_WIDTH = 360;
export const DISCUSSION_SPLIT_PANE_KEYBOARD_STEP = 16;
export const DISCUSSION_SPLIT_PANE_MIN_WORKSPACE_WIDTH = 480;
// The desktop grid has an 8px separator and two 12px column gaps.
export const DISCUSSION_SPLIT_PANE_GRID_CHROME_WIDTH = 32;
// Above this container width the discussion material pane behaves as a desktop
// sidebar with a draggable separator. Below or equal to it, the layout
// stacks material above workspace and the separator is hidden.
export const DISCUSSION_SPLIT_PANE_DESKTOP_BREAKPOINT = 1024;

export function isDesktopDiscussionLayout(containerWidth: number): boolean {
  return (
    Number.isFinite(containerWidth) && containerWidth > DISCUSSION_SPLIT_PANE_DESKTOP_BREAKPOINT
  );
}

export function getMaterialWidthLimit(containerWidth: number): number {
  const availableMaterialWidth = Number.isFinite(containerWidth)
    ? containerWidth -
      DISCUSSION_SPLIT_PANE_MIN_WORKSPACE_WIDTH -
      DISCUSSION_SPLIT_PANE_GRID_CHROME_WIDTH
    : DISCUSSION_SPLIT_PANE_MAX_WIDTH;
  return Math.max(
    DISCUSSION_SPLIT_PANE_MIN_WIDTH,
    Math.min(DISCUSSION_SPLIT_PANE_MAX_WIDTH, availableMaterialWidth),
  );
}

export function clampMaterialWidth(width: number, maxWidth: number): number {
  const safeMax = Math.max(DISCUSSION_SPLIT_PANE_MIN_WIDTH, maxWidth);
  const safeWidth = Number.isFinite(width) ? width : DISCUSSION_SPLIT_PANE_INITIAL_WIDTH;
  return Math.min(safeMax, Math.max(DISCUSSION_SPLIT_PANE_MIN_WIDTH, safeWidth));
}

export function parseStoredMaterialWidth(raw: string | null, maxWidth: number): number {
  const fallback = clampMaterialWidth(DISCUSSION_SPLIT_PANE_INITIAL_WIDTH, maxWidth);
  if (!raw) return fallback;

  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      !("version" in parsed) ||
      parsed.version !== DISCUSSION_SPLIT_PANE_STORAGE_VERSION ||
      !("width" in parsed) ||
      typeof parsed.width !== "number" ||
      !Number.isFinite(parsed.width)
    ) {
      return fallback;
    }
    return clampMaterialWidth(parsed.width, maxWidth);
  } catch {
    return fallback;
  }
}

export function getKeyboardMaterialWidth(
  currentWidth: number,
  key: string,
  maxWidth: number,
  step = DISCUSSION_SPLIT_PANE_KEYBOARD_STEP,
): number {
  switch (key) {
    case "ArrowLeft":
      return clampMaterialWidth(currentWidth - step, maxWidth);
    case "ArrowRight":
      return clampMaterialWidth(currentWidth + step, maxWidth);
    case "Home":
      return DISCUSSION_SPLIT_PANE_MIN_WIDTH;
    case "End":
      return Math.max(DISCUSSION_SPLIT_PANE_MIN_WIDTH, maxWidth);
    default:
      return clampMaterialWidth(currentWidth, maxWidth);
  }
}

/**
 * Pure helper that converts a horizontal pointer-delta into a new clamped
 * pane width. The drag deltas are applied to the *start* width, not the
 * current width, so callers should snapshot the width on pointerdown. A
 * non-finite delta is treated as zero movement and returns the start width.
 */
export function computeDraggedMaterialWidth(
  startWidth: number,
  deltaX: number,
  maxWidth: number,
): number {
  if (!Number.isFinite(deltaX)) {
    return clampMaterialWidth(startWidth, maxWidth);
  }
  return clampMaterialWidth(startWidth + deltaX, maxWidth);
}
