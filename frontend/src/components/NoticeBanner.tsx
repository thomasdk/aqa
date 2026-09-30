import {
  forwardRef,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  type HTMLAttributes,
  type ReactNode,
  type RefObject,
} from "react";
import { useTranslation } from "react-i18next";
import { IconButton } from "./IconButton";
import { MaterialSymbol } from "./MaterialSymbol";

export type NoticeTone = "info" | "success" | "warning" | "error";

type NoticeBannerProps = Omit<HTMLAttributes<HTMLDivElement>, "children"> & {
  children: ReactNode;
  dismissReturnFocusRef?: RefObject<HTMLElement | null>;
  onDismiss?: () => void;
  tone: NoticeTone;
};

const FALLBACK_FOCUS_SELECTOR = [
  "button:not([disabled])",
  "a[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function isUsableFocusTarget(element: HTMLElement | null, scope: HTMLElement | Document): boolean {
  if (!element?.isConnected || !scope.contains(element)) return false;
  if (
    element.matches(':disabled, [aria-disabled="true"]') ||
    element.closest('[inert], [aria-hidden="true"]')
  )
    return false;

  for (let current: HTMLElement | null = element; current; current = current.parentElement) {
    const style = getComputedStyle(current);
    if (style.display === "none" || style.visibility === "hidden") return false;
  }
  return true;
}

function focusFirstUsable(
  targets: Array<HTMLElement | null>,
  scope: HTMLElement | Document,
): boolean {
  for (const target of targets) {
    if (!isUsableFocusTarget(target, scope)) continue;
    target!.focus();
    if (document.activeElement === target) return true;
  }
  return false;
}

/** A persistent or dismissible message announced according to its urgency. */
export const NoticeBanner = forwardRef<HTMLDivElement, NoticeBannerProps>(
  ({ children, className = "", dismissReturnFocusRef, onDismiss, role, tone, ...props }, ref) => {
    const { t } = useTranslation();
    const bannerRef = useRef<HTMLDivElement>(null);
    const dismissReturnFocusRefRef = useRef(dismissReturnFocusRef);
    const restoreFocusOnUnmountRef = useRef(false);
    const fallbackTargetsRef = useRef<HTMLElement[]>([]);
    const focusScopeRef = useRef<HTMLElement | Document>(document);
    useImperativeHandle(ref, () => bannerRef.current!, []);
    dismissReturnFocusRefRef.current = dismissReturnFocusRef;

    useLayoutEffect(
      () => () => {
        const banner = bannerRef.current;
        if (!restoreFocusOnUnmountRef.current || !banner?.contains(document.activeElement)) return;

        const focusScope = focusScopeRef.current;
        const fallbackTargets = fallbackTargetsRef.current;
        queueMicrotask(() => {
          if (document.activeElement && document.activeElement !== document.body) return;
          if (focusFirstUsable([dismissReturnFocusRefRef.current?.current ?? null], focusScope)) {
            return;
          }
          if (focusFirstUsable(fallbackTargets, focusScope)) return;
          if (focusScope instanceof HTMLElement && isUsableFocusTarget(focusScope, focusScope)) {
            focusScope.focus();
          }
        });
      },
      [],
    );

    const isError = tone === "error";
    const closeLabel = t(isError ? "common.closeError" : "common.closeNotice");
    const icon =
      tone === "success"
        ? "check"
        : tone === "info"
          ? "info"
          : tone === "error"
            ? "error"
            : "warning";

    return (
      <div
        {...props}
        ref={bannerRef}
        className={`notice-banner notice-banner--${tone} ${className}`.trim()}
        role={role ?? (isError ? "alert" : "status")}
        aria-live={role === "note" || role === "alert" || isError ? undefined : "polite"}
      >
        <MaterialSymbol className="notice-banner__icon" name={icon} decorative />
        <span className="notice-banner__message">{children}</span>
        {onDismiss && (
          <IconButton
            className="notice-banner__dismiss"
            label={closeLabel}
            title={closeLabel}
            onClick={() => {
              const banner = bannerRef.current;
              restoreFocusOnUnmountRef.current = Boolean(banner?.contains(document.activeElement));
              if (restoreFocusOnUnmountRef.current && banner) {
                const modal = banner.closest<HTMLElement>('[role="dialog"][aria-modal="true"]');
                const scope: HTMLElement | Document = modal ?? document;
                const candidates = Array.from(
                  scope.querySelectorAll<HTMLElement>(FALLBACK_FOCUS_SELECTOR),
                ).filter((element) => !banner.contains(element));
                const position = candidates.findIndex(
                  (element) =>
                    banner.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING,
                );
                focusScopeRef.current = scope;
                fallbackTargetsRef.current =
                  position < 0
                    ? candidates.reverse()
                    : [...candidates.slice(position), ...candidates.slice(0, position).reverse()];
              }
              onDismiss();
            }}
          >
            <MaterialSymbol name="close" decorative />
          </IconButton>
        )}
      </div>
    );
  },
);

NoticeBanner.displayName = "NoticeBanner";

export default NoticeBanner;
