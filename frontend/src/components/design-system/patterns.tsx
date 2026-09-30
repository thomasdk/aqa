import type { ComponentProps, ReactNode } from "react";
import { FavoriteStar } from "../FavoriteStar";
import { IconButton } from "../IconButton";
import { MaterialSymbol } from "../MaterialSymbol";

type ChoiceIndicatorProps = {
  className?: string;
  selected: boolean;
};

/** Decorative checked-circle companion for a native radio selection. */
export function ChoiceIndicator({ className = "", selected }: ChoiceIndicatorProps) {
  return (
    <span
      className={`ds-choice-indicator${selected ? " is-selected" : ""} ${className}`.trim()}
      aria-hidden="true"
    >
      {selected ? <MaterialSymbol name="check" decorative /> : null}
    </span>
  );
}

type StepMarkerProps = {
  children: ReactNode;
  className?: string;
};

/** Compact circular marker for numbered or completed workflow steps. */
export function StepMarker({ children, className = "" }: StepMarkerProps) {
  return (
    <span className={`ds-step-marker ${className}`.trim()} aria-hidden="true">
      {children}
    </span>
  );
}

type StatusBadgeProps = {
  children: ReactNode;
  className?: string;
  tone?: "neutral" | "info" | "success";
};

/** Compact, noninteractive state label with theme-safe semantic colors. */
export function StatusBadge({ children, className = "", tone = "neutral" }: StatusBadgeProps) {
  return (
    <span className={`ds-status-badge ds-status-badge--${tone} ${className}`.trim()}>
      {children}
    </span>
  );
}

type FavoriteToggleProps = Omit<
  ComponentProps<typeof IconButton>,
  "aria-pressed" | "children" | "label"
> & {
  activeLabel: string;
  inactiveLabel: string;
  pressed: boolean;
};

/** Accessible two-state star button shared by preferred and favorite choices. */
export function FavoriteToggle({
  activeLabel,
  className = "",
  inactiveLabel,
  pressed,
  title,
  ...props
}: FavoriteToggleProps) {
  const label = pressed ? activeLabel : inactiveLabel;
  return (
    <IconButton
      {...props}
      className={`ds-favorite-toggle ${className}`.trim()}
      aria-pressed={pressed}
      label={label}
      title={title ?? label}
    >
      <FavoriteStar isFavorite={pressed} />
    </IconButton>
  );
}
