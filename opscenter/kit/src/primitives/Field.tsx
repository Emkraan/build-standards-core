/* Field: a visible sentence-case label, the control, then a hint or an inline error. The control
   gets its id, aria-describedby, aria-invalid and required from the field, and an invalid control
   takes the certified danger border (UI standard section 7). */

import { createContext, forwardRef, useContext, useId } from 'react';
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';
import { IconAlert, IconChevronDown } from '../icons/icons';
import { cx } from '../lib/env';

interface FieldContextValue {
  id: string;
  describedBy: string | undefined;
  invalid: boolean;
  required: boolean;
}

const FieldContext = createContext<FieldContextValue | null>(null);

export interface FieldProps {
  label: string;
  children?: ReactNode;
  hint?: ReactNode;
  /** Inline error. Replaces the hint and marks the control invalid. */
  error?: ReactNode;
  required?: boolean | undefined;
  /** Shows an "Optional" pill. */
  optional?: boolean | undefined;
  /** Character counter for a maxLength, for example { value: 42, max: 200 }. */
  counter?: { value: number; max: number } | undefined;
  /** id for the control. Generated when omitted. */
  id?: string | undefined;
  className?: string | undefined;
}

export function Field({ label, children, hint, error, required = false, optional = false, counter, id, className }: FieldProps) {
  const auto = useId();
  const controlId = id ?? `${auto}-control`;
  const hintId = `${auto}-hint`;
  const errorId = `${auto}-error`;
  const counterId = `${auto}-counter`;
  const hasError = error !== undefined && error !== null && error !== false;
  const hasHint = !hasError && hint !== undefined && hint !== null;
  const describedBy = [hasError ? errorId : null, hasHint ? hintId : null, counter ? counterId : null].filter(Boolean).join(' ') || undefined;
  return (
    <FieldContext.Provider value={{ id: controlId, describedBy, invalid: hasError, required }}>
      <div className={cx('field', className)} data-invalid={hasError ? '' : undefined}>
        <div className="field-top">
          <label className="field-label" htmlFor={controlId}>
            {label}
            {required ? (
              <span className="field-req" aria-hidden="true">
                *
              </span>
            ) : null}
            {optional ? <span className="field-optional">Optional</span> : null}
          </label>
          {counter ? (
            <span id={counterId} className="field-counter" data-over={counter.value > counter.max ? '' : undefined}>
              {counter.value} / {counter.max}
            </span>
          ) : null}
        </div>
        {children}
        {hasError ? (
          <p id={errorId} className="field-error">
            <IconAlert size={14} />
            <span>{error}</span>
          </p>
        ) : hasHint ? (
          <p id={hintId} className="field-hint">
            {hint}
          </p>
        ) : null}
      </div>
    </FieldContext.Provider>
  );
}

interface ControlA11y {
  id?: string | undefined;
  'aria-describedby'?: string | undefined;
  'aria-invalid'?: boolean | 'true' | 'false' | 'grammar' | 'spelling' | undefined;
  required?: boolean | undefined;
}

/** Merges the field's id, description, invalid and required state into a control's props. */
export function useFieldControl<P extends ControlA11y>(props: P): P {
  const field = useContext(FieldContext);
  if (!field) return props;
  const describedBy = [field.describedBy, props['aria-describedby']].filter(Boolean).join(' ') || undefined;
  return {
    ...props,
    id: props.id ?? field.id,
    'aria-describedby': describedBy,
    'aria-invalid': props['aria-invalid'] ?? (field.invalid ? true : undefined),
    required: props.required ?? (field.required || undefined),
  };
}

export interface FormSectionProps {
  /** The section name, rendered as the fieldset legend. */
  title: ReactNode;
  /** One muted line under the title saying what the section controls. */
  description?: ReactNode;
  /** Two columns above the phone breakpoint (one below), or one throughout. Default 2. */
  columns?: 1 | 2 | undefined;
  className?: string | undefined;
  children: ReactNode;
}

/** A titled group of fields inside a long form, so a dozen inputs read as sections and not a wall.
    A real fieldset and legend, so the grouping is announced. A child with the `form-section-full`
    class spans both columns. */
export function FormSection({ title, description, columns = 2, className, children }: FormSectionProps) {
  return (
    <fieldset className={cx('form-section', className)} data-columns={columns}>
      <legend className="form-section-title">{title}</legend>
      {description ? <p className="form-section-desc">{description}</p> : null}
      <div className="form-section-body">{children}</div>
    </fieldset>
  );
}

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  /** 'md' (default, 36px) or 'sm', which matches the Segmented height for compact toolbars. A
      number is the native character width, as before. */
  size?: 'sm' | 'md' | number | undefined;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ className, size, ...rest }, ref) {
  const props = useFieldControl(rest);
  return (
    <input
      {...props}
      ref={ref}
      size={typeof size === 'number' ? size : undefined}
      data-size={size === 'sm' ? 'sm' : undefined}
      className={cx('input', className)}
    />
  );
});

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean | undefined;
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> {
  /** 'md' (default, 36px) or 'sm', the compact toolbar height shared with Input and Segmented. */
  size?: 'sm' | 'md' | undefined;
  options?: readonly SelectOption[] | undefined;
  /** id (or space separated ids) of the element that names this select, for a select outside a
      Field, such as a toolbar filter labelled by a visible heading. Sets aria-labelledby. */
  labelledBy?: string | undefined;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select({ className, options, children, labelledBy, size, ...rest }, ref) {
  const props = useFieldControl(labelledBy ? { ...rest, 'aria-labelledby': labelledBy } : rest);
  return (
    <span className="select-wrap">
      <select {...props} ref={ref} data-size={size === 'sm' ? 'sm' : undefined} className={cx('input', 'select', className)}>
        {options?.map((o) => (
          <option key={o.value} value={o.value} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
        {children}
      </select>
      <IconChevronDown className="select-chevron" size={14} />
    </span>
  );
});

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea({ className, ...rest }, ref) {
  const props = useFieldControl(rest);
  return <textarea {...props} ref={ref} className={cx('input', 'textarea', className)} />;
});
