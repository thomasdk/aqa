import type { ReactElement } from "react";

/** Source of truth for ligatures bundled into the local icon-font subset. */
export const MATERIAL_SYMBOL_ICON_NAMES = [
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

export type MaterialSymbolName = (typeof MATERIAL_SYMBOL_ICON_NAMES)[number];

export interface MaterialSymbolProps {
  name: MaterialSymbolName;
  /**
   * When true, the icon is treated as a presentational ornament next to a
   * visible label and is hidden from assistive technology. The `label`
   * prop is then ignored.
   */
  decorative: boolean;
  /**
   * Required when `decorative` is false; ignored otherwise. Provides the
   * accessible name via aria-label.
   */
  label?: string;
  className?: string;
}

/**
 * Decorative icons are hidden from assistive technology. Semantic icons
 * require a non-empty accessible label and fail fast when it is missing.
 */
export const MaterialSymbol = ({
  name,
  decorative,
  label,
  className,
}: MaterialSymbolProps): ReactElement => {
  const classes = className ? `material-symbol ${className}` : "material-symbol";

  if (decorative) {
    return (
      <span className={classes} aria-hidden="true">
        {name}
      </span>
    );
  }

  if (typeof label !== "string" || label.trim().length === 0) {
    throw new Error(
      `MaterialSymbol: a non-empty \`label\` prop is required when \`decorative\` is false (icon "${name}").`,
    );
  }

  return (
    <span className={classes} role="img" aria-label={label}>
      {name}
    </span>
  );
};

export default MaterialSymbol;
