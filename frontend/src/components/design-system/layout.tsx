import type { FormHTMLAttributes, HTMLAttributes, ReactNode } from "react";

type ActionGroupProps = HTMLAttributes<HTMLDivElement> & {
  align?: "start" | "end" | "spread";
};

export function ActionGroup({ align = "end", className = "", ...props }: ActionGroupProps) {
  return (
    <div {...props} className={`ds-action-group ds-action-group--${align} ${className}`.trim()} />
  );
}

type HeaderProps = HTMLAttributes<HTMLElement> & {
  actions?: ReactNode;
  subtitle?: ReactNode;
  title: ReactNode;
  titleId?: string;
};

type SectionHeaderProps = HeaderProps & {
  headingLevel?: 2 | 3;
};

export function PageHeader({
  actions,
  className = "",
  subtitle,
  title,
  titleId,
  ...props
}: HeaderProps) {
  return (
    <header {...props} className={`ds-page-header ${className}`.trim()}>
      <div className="ds-page-header__copy">
        <h1 id={titleId}>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <ActionGroup>{actions}</ActionGroup>}
    </header>
  );
}

export function SectionHeader({
  actions,
  className = "",
  headingLevel = 2,
  subtitle,
  title,
  titleId,
  ...props
}: SectionHeaderProps) {
  const Heading = headingLevel === 3 ? "h3" : "h2";
  return (
    <header {...props} className={`ds-section-header ${className}`.trim()}>
      <div className="ds-section-header__copy">
        <Heading id={titleId}>{title}</Heading>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <ActionGroup>{actions}</ActionGroup>}
    </header>
  );
}

type CardProps = HTMLAttributes<HTMLDivElement> & {
  surface?: "raised" | "recessed";
};

export function Card({ className = "", surface = "raised", ...props }: CardProps) {
  return <div {...props} className={`ds-card ds-card--${surface} ${className}`.trim()} />;
}

export function DialogFooter({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <ActionGroup {...props} className={`ds-dialog-footer ${className}`.trim()} />;
}

export function EditorDialogBody({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={`ds-editor-dialog-body ${className}`.trim()} />;
}

export function EditorDialogError({
  className = "",
  role = "alert",
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div {...props} role={role} className={`ds-editor-dialog-error ${className}`.trim()} />;
}

export function EditorDialogForm({
  className = "",
  ...props
}: FormHTMLAttributes<HTMLFormElement>) {
  return <form {...props} className={`ds-editor-dialog-body ${className}`.trim()} />;
}
