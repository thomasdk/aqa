import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import {
  clampMaterialWidth,
  computeDraggedMaterialWidth,
  DISCUSSION_SPLIT_PANE_INITIAL_WIDTH,
  DISCUSSION_SPLIT_PANE_MAX_WIDTH,
  DISCUSSION_SPLIT_PANE_STORAGE_KEY,
  DISCUSSION_SPLIT_PANE_STORAGE_VERSION,
  getKeyboardMaterialWidth,
  getMaterialWidthLimit,
  isDesktopDiscussionLayout,
  parseStoredMaterialWidth,
} from "../discussionSplitPane";

const MATERIAL_RAIL_WIDTH = 44;

/**
 * Owns the resizable material pane's UI-only state.
 *
 * This controller intentionally persists only the versioned pane width; it
 * never stores material or other discussion data in browser storage.
 */
export function useDiscussionMaterialPane(measurementKey: unknown) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [width, setWidth] = useState(() => {
    if (typeof window === "undefined") {
      return DISCUSSION_SPLIT_PANE_INITIAL_WIDTH;
    }
    try {
      return parseStoredMaterialWidth(
        window.localStorage.getItem(DISCUSSION_SPLIT_PANE_STORAGE_KEY),
        DISCUSSION_SPLIT_PANE_MAX_WIDTH,
      );
    } catch {
      return DISCUSSION_SPLIT_PANE_INITIAL_WIDTH;
    }
  });
  const [containerWidth, setContainerWidth] = useState(0);
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const separatorRef = useRef<HTMLDivElement | null>(null);
  const dragStartWidthRef = useRef(DISCUSSION_SPLIT_PANE_INITIAL_WIDTH);
  const dragStartXRef = useRef(0);
  const isDraggingRef = useRef(false);

  const maxWidth =
    containerWidth > 0 ? getMaterialWidthLimit(containerWidth) : DISCUSSION_SPLIT_PANE_MAX_WIDTH;
  const isDesktop = isDesktopDiscussionLayout(containerWidth);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const layout = layoutRef.current;
    if (!layout) return;

    const applyContainerWidth = (nextWidth: number) => {
      if (!Number.isFinite(nextWidth) || nextWidth <= 0) return;
      setContainerWidth(nextWidth);
      setWidth((previous) => clampMaterialWidth(previous, getMaterialWidthLimit(nextWidth)));
    };
    const measure = () => applyContainerWidth(layout.getBoundingClientRect().width);
    measure();

    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver((entries) => {
            const entry = entries.find((candidate) => candidate.target === layout);
            applyContainerWidth(entry?.contentRect.width ?? layout.getBoundingClientRect().width);
          });
    observer?.observe(layout);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [measurementKey]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(
        DISCUSSION_SPLIT_PANE_STORAGE_KEY,
        JSON.stringify({
          version: DISCUSSION_SPLIT_PANE_STORAGE_VERSION,
          width,
        }),
      );
    } catch {
      // Storage is an optional convenience (private mode and quota may deny it).
    }
  }, [width]);

  const toggle = useCallback(() => setIsCollapsed((previous) => !previous), []);

  const onPointerDown = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      isDraggingRef.current = true;
      dragStartWidthRef.current = width;
      dragStartXRef.current = event.clientX;
      event.preventDefault();
    },
    [width],
  );

  const onPointerMove = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (!isDraggingRef.current) return;
      setWidth(
        computeDraggedMaterialWidth(
          dragStartWidthRef.current,
          event.clientX - dragStartXRef.current,
          maxWidth,
        ),
      );
    },
    [maxWidth],
  );

  const releasePointer = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (!isDraggingRef.current) return;
    isDraggingRef.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, []);

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      switch (event.key) {
        case "ArrowLeft":
        case "ArrowRight":
        case "Home":
        case "End":
          event.preventDefault();
          setWidth(getKeyboardMaterialWidth(width, event.key, maxWidth));
          break;
        case "Enter":
        case " ":
          event.preventDefault();
          setIsCollapsed((previous) => !previous);
          break;
        case "Escape":
          event.currentTarget.blur();
          break;
      }
    },
    [maxWidth, width],
  );

  const onDoubleClick = useCallback(() => {
    setWidth(clampMaterialWidth(DISCUSSION_SPLIT_PANE_INITIAL_WIDTH, maxWidth));
  }, [maxWidth]);

  const style: CSSProperties = isDesktop
    ? {
        ["--material-pane-width" as string]: `${isCollapsed ? MATERIAL_RAIL_WIDTH : width}px`,
      }
    : {};

  return {
    isCollapsed,
    width,
    maxWidth,
    isDesktop,
    layoutRef,
    separatorRef,
    style,
    toggle,
    onPointerDown,
    onPointerMove,
    releasePointer,
    onKeyDown,
    onDoubleClick,
  };
}
