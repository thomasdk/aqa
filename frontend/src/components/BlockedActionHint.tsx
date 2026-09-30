import type { HTMLAttributes, ReactNode } from "react";
import { MaterialSymbol } from "./MaterialSymbol";

type BlockedActionHintProps = Omit<HTMLAttributes<HTMLParagraphElement>, "children"> & {
  children: ReactNode;
};

/** A stable prerequisite shown next to the control it currently blocks. */
export function BlockedActionHint({ children, className = "", ...props }: BlockedActionHintProps) {
  return (
    <p {...props} className={`blocked-action-hint ${className}`.trim()}>
      <MaterialSymbol name="help" decorative />
      <span>{children}</span>
    </p>
  );
}

export default BlockedActionHint;
