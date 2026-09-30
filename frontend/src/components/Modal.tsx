import {
  useId,
  useLayoutEffect,
  useRef,
  type MouseEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { useTranslation } from "react-i18next";
import { Button, DialogFooter } from "./design-system";

type ModalProps = {
  children: ReactNode;
  className?: string;
  layout?: "default" | "editor";
  label?: string;
  labelledBy?: string;
  onClose: () => void;
  initialFocusRef?: RefObject<HTMLElement | null>;
  returnFocusRef?: RefObject<HTMLElement | null>;
};

type ModalEntry = {
  dialog: HTMLDivElement;
  overlay: HTMLDivElement;
  lastFocused: HTMLElement | null;
};

type IsolationState = {
  ariaHidden: string | null;
  inert: boolean;
  inertAttribute: string | null;
};

const focusableSelector = [
  "a[href]",
  "area[href]",
  "button",
  "input",
  "select",
  "textarea",
  "iframe",
  "object",
  "embed",
  "audio[controls]",
  "video[controls]",
  "summary",
  '[contenteditable]:not([contenteditable="false"])',
  "[tabindex]",
].join(",");

const modalStack: ModalEntry[] = [];
const isolatedElements = new Map<HTMLElement, IsolationState>();
const handledKeyEvents = new WeakSet<KeyboardEvent>();

function isUnavailable(element: HTMLElement, boundary?: HTMLElement): boolean {
  if (element.matches(':disabled, input[type="hidden"]')) return true;

  let current: HTMLElement | null = element;
  while (current) {
    if (
      current.hidden ||
      current.hasAttribute("inert") ||
      current.getAttribute("aria-hidden") === "true"
    ) {
      return true;
    }
    const style = window.getComputedStyle(current);
    if (style.display === "none" || style.visibility === "hidden") return true;
    if (current === boundary) break;
    current = current.parentElement;
  }
  return false;
}

function isProgrammaticFocusTarget(element: HTMLElement, boundary?: HTMLElement): boolean {
  if (!element.isConnected || isUnavailable(element, boundary)) return false;
  return element.tabIndex >= 0 || element.hasAttribute("tabindex") || element.isContentEditable;
}

function getTabbableElements(dialog: HTMLElement): HTMLElement[] {
  return Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector)).filter(
    (element) => element.tabIndex >= 0 && !isUnavailable(element, dialog),
  );
}

function focusElement(element: HTMLElement): boolean {
  element.focus({ preventScroll: true });
  return document.activeElement === element;
}

function focusDialog(entry: ModalEntry): void {
  const { dialog } = entry;
  if (
    entry.lastFocused &&
    dialog.contains(entry.lastFocused) &&
    isProgrammaticFocusTarget(entry.lastFocused, dialog) &&
    focusElement(entry.lastFocused)
  ) {
    return;
  }

  const controls = getTabbableElements(dialog);
  const target = controls[0];
  if (!target || !focusElement(target)) focusElement(dialog);
}

function getTopModal(): ModalEntry | undefined {
  return modalStack.reduce<ModalEntry | undefined>((top, candidate) => {
    if (!top || top.dialog.contains(candidate.overlay)) return candidate;
    if (candidate.dialog.contains(top.overlay)) return top;
    return top.overlay.compareDocumentPosition(candidate.overlay) & Node.DOCUMENT_POSITION_FOLLOWING
      ? candidate
      : top;
  }, undefined);
}

function backgroundBranches(overlay: HTMLElement): HTMLElement[] {
  const branches = new Set<HTMLElement>();
  let current: HTMLElement | null = overlay;
  while (current && current !== document.body) {
    const parentElement: HTMLElement | null = current.parentElement;
    if (!parentElement) break;
    for (const sibling of parentElement.children) {
      if (sibling !== current && sibling instanceof HTMLElement) branches.add(sibling);
    }
    current = parentElement;
  }
  return Array.from(branches);
}

function restoreBackground(): void {
  for (const [element, state] of isolatedElements) {
    element.inert = state.inert;
    if (state.inertAttribute === null) element.removeAttribute("inert");
    else element.setAttribute("inert", state.inertAttribute);
    if (state.ariaHidden === null) element.removeAttribute("aria-hidden");
    else element.setAttribute("aria-hidden", state.ariaHidden);
  }
  isolatedElements.clear();
}

function syncBackgroundIsolation(): void {
  restoreBackground();
  const top = getTopModal();
  if (!top) return;

  for (const element of backgroundBranches(top.overlay)) {
    isolatedElements.set(element, {
      ariaHidden: element.getAttribute("aria-hidden"),
      inert: element.inert,
      inertAttribute: element.getAttribute("inert"),
    });
    element.inert = true;
    element.setAttribute("inert", "");
    element.setAttribute("aria-hidden", "true");
  }
}

/**
 * A blocking dialog that isolates the background, contains focus, and restores
 * focus to an explicit return target or its opener after close.
 */
export function Modal({
  children,
  className = "",
  layout = "default",
  label,
  labelledBy,
  onClose,
  initialFocusRef,
  returnFocusRef,
}: ModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  const initialTargetRef = useRef(initialFocusRef);
  const returnTargetRef = useRef(returnFocusRef);
  onCloseRef.current = onClose;
  initialTargetRef.current = initialFocusRef;
  returnTargetRef.current = returnFocusRef;

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    const overlay = overlayRef.current;
    if (!dialog || !overlay) return;

    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const entry: ModalEntry = { dialog, overlay, lastFocused: null };
    modalStack.push(entry);

    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        getTopModal() !== entry ||
        handledKeyEvents.has(event) ||
        event.defaultPrevented ||
        event.isComposing
      ) {
        return;
      }
      if (event.key === "Escape") {
        handledKeyEvents.add(event);
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;

      const controls = getTabbableElements(dialog);
      const active = document.activeElement;
      if (controls.length === 0) {
        handledKeyEvents.add(event);
        event.preventDefault();
        focusElement(dialog);
        return;
      }

      const index = active instanceof HTMLElement ? controls.indexOf(active) : -1;
      if (index === -1 || active === dialog) {
        handledKeyEvents.add(event);
        event.preventDefault();
        focusElement(event.shiftKey ? controls[controls.length - 1] : controls[0]);
      } else if (event.shiftKey && index === 0) {
        handledKeyEvents.add(event);
        event.preventDefault();
        focusElement(controls[controls.length - 1]);
      } else if (!event.shiftKey && index === controls.length - 1) {
        handledKeyEvents.add(event);
        event.preventDefault();
        focusElement(controls[0]);
      }
    };

    const handleFocusIn = (event: FocusEvent) => {
      if (getTopModal() !== entry) return;
      if (event.target instanceof HTMLElement && dialog.contains(event.target)) {
        if (event.target !== dialog) entry.lastFocused = event.target;
        return;
      }
      focusDialog(entry);
    };

    let recoveryQueued = false;
    let active = true;
    const observer = new MutationObserver(() => {
      if (recoveryQueued) return;
      recoveryQueued = true;
      queueMicrotask(() => {
        recoveryQueued = false;
        if (!active || getTopModal() !== entry) return;
        const focused = document.activeElement;
        if (
          !(focused instanceof HTMLElement) ||
          !dialog.contains(focused) ||
          (focused !== dialog && isUnavailable(focused, dialog))
        ) {
          if (entry.lastFocused === focused) entry.lastFocused = null;
          focusDialog(entry);
        }
      });
    });

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("focusin", handleFocusIn);
    observer.observe(dialog, {
      attributeFilter: ["aria-hidden", "class", "disabled", "hidden", "inert", "style", "tabindex"],
      attributes: true,
      childList: true,
      subtree: true,
    });

    const requested = initialTargetRef.current?.current;
    if (
      requested &&
      dialog.contains(requested) &&
      isProgrammaticFocusTarget(requested, dialog) &&
      focusElement(requested)
    ) {
      entry.lastFocused = requested;
    } else {
      focusDialog(entry);
    }
    syncBackgroundIsolation();

    return () => {
      active = false;
      observer.disconnect();
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("focusin", handleFocusIn);

      const wasTop = getTopModal() === entry;
      const index = modalStack.indexOf(entry);
      if (index >= 0) modalStack.splice(index, 1);
      syncBackgroundIsolation();
      if (!wasTop) return;

      const current = document.activeElement;
      if (
        current instanceof HTMLElement &&
        current !== document.body &&
        current.isConnected &&
        !dialog.contains(current)
      ) {
        return;
      }

      const nextModal = getTopModal();
      if (nextModal) {
        focusDialog(nextModal);
        return;
      }

      const explicitReturn = returnTargetRef.current?.current;
      if (
        explicitReturn &&
        isProgrammaticFocusTarget(explicitReturn) &&
        focusElement(explicitReturn)
      ) {
        return;
      }
      if (opener && isProgrammaticFocusTarget(opener)) focusElement(opener);
    };
  }, []);

  const closeOnBackdrop = (event: MouseEvent<HTMLDivElement>) => {
    if (
      event.target === event.currentTarget &&
      dialogRef.current &&
      getTopModal()?.dialog === dialogRef.current
    ) {
      onCloseRef.current();
    }
  };

  return (
    <div
      ref={overlayRef}
      className="modal-overlay"
      onMouseDown={closeOnBackdrop}
      role="presentation"
    >
      <div
        className={`modal-content modal-content--${layout} ${className}`.trim()}
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        aria-labelledby={labelledBy}
        tabIndex={-1}
      >
        {children}
      </div>
    </div>
  );
}

type ConfirmDialogBaseProps = {
  title: string;
  message: ReactNode;
  cancelLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
  disabled?: boolean;
  pendingLabel?: string;
  returnFocusRef?: RefObject<HTMLElement | null>;
};

type ConfirmDialogProps = ConfirmDialogBaseProps &
  (
    | {
        variant: "delete";
        confirmLabel?: never;
      }
    | {
        variant?: "default" | "destructive";
        confirmLabel: string;
      }
  );

/** A standard confirmation dialog with an explicit safe initial action. */
export function ConfirmDialog({
  title,
  message,
  cancelLabel,
  confirmLabel,
  variant = "default",
  onCancel,
  onConfirm,
  disabled = false,
  pendingLabel,
  returnFocusRef,
}: ConfirmDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const destructive = variant === "delete" || variant === "destructive";
  const visibleConfirmLabel =
    disabled && pendingLabel
      ? pendingLabel
      : variant === "delete"
        ? t("common.delete")
        : confirmLabel;
  const cancelWhenEnabled = () => {
    if (!disabled) onCancel();
  };
  return (
    <Modal
      className="confirm-dialog"
      labelledBy={titleId}
      onClose={cancelWhenEnabled}
      initialFocusRef={cancelRef}
      returnFocusRef={returnFocusRef}
    >
      <h2 id={titleId}>{title}</h2>
      <div className="modal-message">{message}</div>
      <DialogFooter>
        <Button ref={cancelRef} variant="secondary" onClick={onCancel} disabled={disabled}>
          {cancelLabel}
        </Button>
        <Button
          variant={destructive ? "dangerPrimary" : "primary"}
          onClick={onConfirm}
          disabled={disabled}
          loading={disabled && Boolean(pendingLabel)}
          loadingLabel={pendingLabel}
        >
          {visibleConfirmLabel}
        </Button>
      </DialogFooter>
    </Modal>
  );
}

export default Modal;
