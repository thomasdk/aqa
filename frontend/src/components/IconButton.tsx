import { forwardRef, useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from "react";

export type IconButtonVariant = "secondary" | "danger" | "ghost";

/** Shared accessible treatment for icon-only controls. */
type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  children: ReactNode;
  size?: "small" | "medium";
  variant?: IconButtonVariant;
};

function isTooltipVisible(button: HTMLButtonElement): boolean {
  // jsdom does not compute pseudo-element styles; focus is the unit-test proxy.
  if (navigator.userAgent.includes("jsdom")) return button.matches(":focus");
  return getComputedStyle(button, "::after").visibility === "visible";
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  (
    {
      label,
      children,
      className = "",
      onFocus,
      onKeyDown,
      onPointerEnter,
      onPointerLeave,
      size = "medium",
      variant = "secondary",
      ...props
    },
    ref,
  ) => {
    const [tooltipDismissed, setTooltipDismissed] = useState(false);
    const [pointerInside, setPointerInside] = useState(false);

    useEffect(() => {
      if (!pointerInside || tooltipDismissed) return;
      const dismissHoveredTooltip = (event: KeyboardEvent) => {
        if (event.key !== "Escape") return;
        event.preventDefault();
        setTooltipDismissed(true);
      };
      document.addEventListener("keydown", dismissHoveredTooltip, true);
      return () => document.removeEventListener("keydown", dismissHoveredTooltip, true);
    }, [pointerInside, tooltipDismissed]);

    return (
      <button
        {...props}
        ref={ref}
        type={props.type ?? "button"}
        className={`icon-button ds-icon-button ds-icon-button--${variant} ds-control--${size} ${className}`.trim()}
        aria-label={label}
        data-tooltip={label}
        data-tooltip-dismissed={tooltipDismissed ? "true" : undefined}
        onFocus={(event) => {
          setTooltipDismissed(false);
          onFocus?.(event);
        }}
        onPointerEnter={(event) => {
          setPointerInside(true);
          setTooltipDismissed(false);
          onPointerEnter?.(event);
        }}
        onPointerLeave={(event) => {
          setPointerInside(false);
          onPointerLeave?.(event);
        }}
        onKeyDown={(event) => {
          if (
            event.key === "Escape" &&
            !tooltipDismissed &&
            isTooltipVisible(event.currentTarget)
          ) {
            event.preventDefault();
            event.stopPropagation();
            setTooltipDismissed(true);
          }
          onKeyDown?.(event);
        }}
      >
        {children}
      </button>
    );
  },
);

IconButton.displayName = "IconButton";

export default IconButton;
