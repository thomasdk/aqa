import {
  forwardRef,
  createContext,
  useId,
  useContext,
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { useTranslation } from "react-i18next";
import { formatNumber, parseLocalizedInteger } from "../../i18n";

export type ButtonVariant =
  "primary" | "secondary" | "danger" | "dangerPrimary" | "toolbar" | "text";
export type ControlSize = "small" | "medium";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  loading?: boolean;
  loadingLabel?: ReactNode;
  size?: ControlSize;
  variant?: ButtonVariant;
};

/** The canonical text-action control. Specialized icon-only actions use IconButton. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      children,
      className = "",
      disabled,
      loading = false,
      loadingLabel,
      size = "medium",
      type = "button",
      variant = "secondary",
      ...props
    },
    ref,
  ) => (
    <button
      {...props}
      ref={ref}
      type={type}
      className={`ds-button ds-button--${variant} ds-control--${size} ${className}`.trim()}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {loading && loadingLabel !== undefined ? loadingLabel : children}
    </button>
  ),
);

Button.displayName = "Button";

type FieldProps = {
  children: ReactNode;
  className?: string;
  description?: ReactNode;
  descriptionId?: string;
  error?: ReactNode;
  errorId?: string;
  htmlFor?: string;
  label: ReactNode;
  required?: boolean;
};

type FieldContextValue = {
  controlId: string;
  describedBy?: string;
  invalid: boolean;
  required: boolean;
};

const FieldContext = createContext<FieldContextValue | null>(null);

function joinIds(...values: Array<string | undefined>): string | undefined {
  const ids = values.flatMap((value) => value?.split(/\s+/).filter(Boolean) ?? []);
  return ids.length > 0 ? Array.from(new Set(ids)).join(" ") : undefined;
}

/** Label, help, and validation structure shared by conventional form fields. */
export function Field({
  children,
  className = "",
  description,
  descriptionId,
  error,
  errorId,
  htmlFor,
  label,
  required = false,
}: FieldProps) {
  const generatedControlId = useId();
  const generatedDescriptionId = useId();
  const generatedErrorId = useId();
  const controlId = htmlFor ?? generatedControlId;
  const resolvedDescriptionId = description ? (descriptionId ?? generatedDescriptionId) : undefined;
  const resolvedErrorId = error ? (errorId ?? generatedErrorId) : undefined;
  const describedBy = joinIds(resolvedDescriptionId, resolvedErrorId);

  return (
    <div className={`ds-field ${className}`.trim()}>
      <label className="ds-field__label" htmlFor={controlId}>
        {label}
        {required && <span aria-hidden="true"> *</span>}
      </label>
      {description && (
        <div className="ds-field__description" id={resolvedDescriptionId}>
          {description}
        </div>
      )}
      <FieldContext.Provider value={{ controlId, describedBy, invalid: Boolean(error), required }}>
        {children}
      </FieldContext.Provider>
      {error && (
        <div className="ds-field__error" id={resolvedErrorId} role="alert">
          {error}
        </div>
      )}
    </div>
  );
}

type InvalidControl = {
  invalid?: boolean;
};

export type InputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "size"> &
  InvalidControl & {
    size?: ControlSize;
  };

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className = "", invalid, size = "medium", ...props }, ref) => {
    const field = useContext(FieldContext);
    const resolvedInvalid = invalid ?? field?.invalid ?? false;
    return (
      <input
        {...props}
        ref={ref}
        id={props.id ?? field?.controlId}
        required={props.required ?? field?.required}
        className={`ds-control ds-input ds-control--${size} ${className}`.trim()}
        aria-describedby={joinIds(props["aria-describedby"], field?.describedBy)}
        aria-invalid={props["aria-invalid"] ?? (resolvedInvalid || undefined)}
      />
    );
  },
);

Input.displayName = "Input";

export type IntegerInputProps = Omit<InputProps, "type" | "value" | "onChange" | "min" | "max"> & {
  value: string;
  onValueChange: (value: string) => void;
  min?: number;
  max?: number;
};

/** Locale-grouped integer display with an unformatted draft while editing. */
export const IntegerInput = forwardRef<HTMLInputElement, IntegerInputProps>(
  ({ value, onValueChange, min, max, onFocus, onBlur, onKeyDown, ...props }, ref) => {
    const { i18n } = useTranslation();
    const language = i18n.resolvedLanguage ?? i18n.language;
    const [editing, setEditing] = useState(false);
    const previousLanguage = useRef(language);
    useEffect(() => {
      if (previousLanguage.current !== language) {
        const previous = parseLocalizedInteger(value, previousLanguage.current);
        if (previous !== null && value !== String(previous)) onValueChange(String(previous));
        previousLanguage.current = language;
      }
    }, [language, onValueChange, value]);
    const parsed = parseLocalizedInteger(value, language);
    const display = editing || parsed === null ? value : formatNumber(parsed);
    return (
      <Input
        {...props}
        ref={ref}
        type="text"
        role="spinbutton"
        inputMode="numeric"
        min={min}
        max={max}
        step={1}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={parsed ?? undefined}
        value={display}
        onChange={(event) => {
          setEditing(true);
          onValueChange(event.target.value);
        }}
        onFocus={onFocus}
        onBlur={(event) => {
          const complete = parseLocalizedInteger(value, language);
          if (complete !== null && value !== String(complete)) onValueChange(String(complete));
          setEditing(false);
          onBlur?.(event);
        }}
        onKeyDown={(event) => {
          if (
            (event.key === "ArrowUp" || event.key === "ArrowDown") &&
            !event.altKey &&
            !event.ctrlKey &&
            !event.metaKey
          ) {
            event.preventDefault();
            const current = parseLocalizedInteger(value, language);
            const next = current === null ? null : current + (event.key === "ArrowUp" ? 1 : -1);
            if (
              next !== null &&
              (min === undefined || next >= min) &&
              (max === undefined || next <= max)
            ) {
              setEditing(true);
              onValueChange(String(next));
            }
          }
          onKeyDown?.(event);
        }}
      />
    );
  },
);

IntegerInput.displayName = "IntegerInput";

export type SelectProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, "size"> &
  InvalidControl & {
    size?: ControlSize;
  };

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className = "", invalid, size = "medium", ...props }, ref) => {
    const field = useContext(FieldContext);
    const resolvedInvalid = invalid ?? field?.invalid ?? false;
    return (
      <select
        {...props}
        ref={ref}
        id={props.id ?? field?.controlId}
        required={props.required ?? field?.required}
        className={`ds-control ds-select ds-control--${size} ${className}`.trim()}
        aria-describedby={joinIds(props["aria-describedby"], field?.describedBy)}
        aria-invalid={props["aria-invalid"] ?? (resolvedInvalid || undefined)}
      />
    );
  },
);

Select.displayName = "Select";

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> &
  InvalidControl & {
    size?: ControlSize;
  };

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className = "", invalid, size = "medium", ...props }, ref) => {
    const field = useContext(FieldContext);
    const resolvedInvalid = invalid ?? field?.invalid ?? false;
    return (
      <textarea
        {...props}
        ref={ref}
        id={props.id ?? field?.controlId}
        required={props.required ?? field?.required}
        className={`ds-control ds-textarea ds-control--${size} ${className}`.trim()}
        aria-describedby={joinIds(props["aria-describedby"], field?.describedBy)}
        aria-invalid={props["aria-invalid"] ?? (resolvedInvalid || undefined)}
      />
    );
  },
);

Textarea.displayName = "Textarea";
