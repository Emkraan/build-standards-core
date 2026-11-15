/* Choice controls: Checkbox, Radio, RadioGroup and Switch (UI standard section 7). Checkbox and
   Radio are native inputs, so keyboard, forms and screen readers behave as the platform does
   (Space toggles, arrows move within a radio group). The visible box is drawn beside the input,
   never instead of it. Switch is a button with role switch for settings that apply at once.
   Every control has a visible label (or an accessible one when the label is hidden), a disabled
   state and two sizes. */

import { createContext, forwardRef, useCallback, useContext, useEffect, useId, useImperativeHandle, useRef, useState } from 'react';
import type { ChangeEvent, InputHTMLAttributes, ButtonHTMLAttributes, ReactNode } from 'react';
import { IconCheck } from '../icons/icons';
import { cx } from '../lib/env';

export type ChoiceSize = 'sm' | 'md';

interface ChoiceTextProps {
  htmlFor: string;
  labelId?: string | undefined;
  label: ReactNode;
  description?: ReactNode;
  descriptionId?: string | undefined;
  hideLabel?: boolean | undefined;
}

/** The label (only the label names the control) and the description beside it. */
function ChoiceText({ htmlFor, labelId, label, description, descriptionId, hideLabel }: ChoiceTextProps) {
  return (
    <span className={cx('choice-text', hideLabel && 'kit-sr-only')}>
      <label className="choice-label" htmlFor={htmlFor} id={labelId}>
        {label}
      </label>
      {description ? (
        <span id={descriptionId} className="choice-desc">
          {description}
        </span>
      ) : null}
    </span>
  );
}

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'size'> {
  /** Visible label. Use `hideLabel` to keep it for screen readers only. */
  label: ReactNode;
  /** A second line under the label, linked by aria-describedby. */
  description?: ReactNode;
  hideLabel?: boolean | undefined;
  size?: ChoiceSize | undefined;
  /** The mixed state, for a select-all box over a partial selection. */
  indeterminate?: boolean | undefined;
  /** Called with the new checked state, after onChange. */
  onCheckedChange?: ((checked: boolean) => void) | undefined;
}

/** A native checkbox with a drawn box, a label and an optional description. */
export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { label, description, hideLabel, size = 'md', indeterminate = false, onCheckedChange, onChange, className, id, disabled, ...rest },
  ref,
) {
  const auto = useId();
  const inputId = id ?? `${auto}-check`;
  const descId = description ? `${auto}-desc` : undefined;
  const inner = useRef<HTMLInputElement | null>(null);
  useImperativeHandle(ref, () => inner.current as HTMLInputElement);
  // Re-applied on every render: a click clears the native flag, and the prop stays the truth.
  useEffect(() => {
    if (inner.current && inner.current.indeterminate !== indeterminate) inner.current.indeterminate = indeterminate;
  });
  const describedBy = [rest['aria-describedby'], descId].filter(Boolean).join(' ') || undefined;
  return (
    <span className={cx('choice', 'check', className)} data-size={size} data-disabled={disabled ? '' : undefined}>
      <span className="choice-control">
        <input
          {...rest}
          ref={inner}
          id={inputId}
          type="checkbox"
          className="choice-native"
          disabled={disabled}
          aria-describedby={describedBy}
          onChange={(event: ChangeEvent<HTMLInputElement>) => {
            onChange?.(event);
            onCheckedChange?.(event.currentTarget.checked);
          }}
        />
        <span className="check-box" aria-hidden="true">
          <IconCheck size={size === 'sm' ? 10 : 12} className="check-mark" />
          <span className="check-dash" />
        </span>
      </span>
      <ChoiceText htmlFor={inputId} label={label} description={description} descriptionId={descId} hideLabel={hideLabel} />
    </span>
  );
});

interface RadioGroupContextValue {
  name: string;
  value: string | undefined;
  size: ChoiceSize;
  disabled: boolean;
  describedBy: string | undefined;
  select: (value: string) => void;
}

const RadioGroupContext = createContext<RadioGroupContextValue | null>(null);

export interface RadioProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'size' | 'value'> {
  value: string;
  label: ReactNode;
  description?: ReactNode;
  hideLabel?: boolean | undefined;
  /** Inside a RadioGroup the group's size wins. */
  size?: ChoiceSize | undefined;
}

/** A native radio. Inside a RadioGroup it takes the group's name, value, size and disabled state. */
export const Radio = forwardRef<HTMLInputElement, RadioProps>(function Radio(
  { value, label, description, hideLabel, size, className, id, disabled, onChange, name, checked, defaultChecked, ...rest },
  ref,
) {
  const group = useContext(RadioGroupContext);
  const auto = useId();
  const inputId = id ?? `${auto}-radio`;
  const descId = description ? `${auto}-desc` : undefined;
  const isDisabled = Boolean(disabled || group?.disabled);
  const shownSize = group?.size ?? size ?? 'md';
  const describedBy = [rest['aria-describedby'], descId, group?.describedBy].filter(Boolean).join(' ') || undefined;
  const groupChecked = group ? group.value === value : checked;
  return (
    <span className={cx('choice', 'radio', className)} data-size={shownSize} data-disabled={isDisabled ? '' : undefined}>
      <span className="choice-control">
        <input
          {...rest}
          ref={ref}
          id={inputId}
          type="radio"
          className="choice-native"
          name={group?.name ?? name}
          value={value}
          checked={groupChecked}
          defaultChecked={group ? undefined : defaultChecked}
          disabled={isDisabled}
          aria-describedby={describedBy}
          onChange={(event: ChangeEvent<HTMLInputElement>) => {
            onChange?.(event);
            if (group && event.currentTarget.checked) group.select(value);
          }}
        />
        <span className="radio-dot" aria-hidden="true" />
      </span>
      <ChoiceText htmlFor={inputId} label={label} description={description} descriptionId={descId} hideLabel={hideLabel} />
    </span>
  );
});

export interface RadioOption {
  value: string;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean | undefined;
}

export interface RadioGroupProps {
  /** Group label, rendered as the legend. */
  label: ReactNode;
  /** Keeps the legend for screen readers only. */
  hideLabel?: boolean | undefined;
  /** Controlled value. */
  value?: string | undefined;
  /** Uncontrolled starting value. */
  defaultValue?: string | undefined;
  onChange?: ((value: string) => void) | undefined;
  /** Shortcut for simple groups. Radio children work too. */
  options?: readonly RadioOption[] | undefined;
  children?: ReactNode;
  /** Form name. Generated when omitted, so arrow keys stay inside this group. */
  name?: string | undefined;
  orientation?: 'vertical' | 'horizontal' | undefined;
  size?: ChoiceSize | undefined;
  disabled?: boolean | undefined;
  hint?: ReactNode;
  /** Inline error, linked to every radio in the group. */
  error?: ReactNode;
  className?: string | undefined;
}

/** A labelled group of radios. Arrow keys move the choice (native radio behaviour). */
export function RadioGroup({
  label,
  hideLabel = false,
  value,
  defaultValue,
  onChange,
  options,
  children,
  name,
  orientation = 'vertical',
  size = 'md',
  disabled = false,
  hint,
  error,
  className,
}: RadioGroupProps) {
  const auto = useId();
  const [inner, setInner] = useState<string | undefined>(defaultValue);
  const controlled = value !== undefined;
  const current = controlled ? value : inner;
  const select = useCallback(
    (next: string) => {
      if (!controlled) setInner(next);
      onChange?.(next);
    },
    [controlled, onChange],
  );
  const hasError = error !== undefined && error !== null && error !== false;
  const noteId = hasError || hint ? `${auto}-note` : undefined;
  const ctx: RadioGroupContextValue = { name: name ?? `${auto}-radios`, value: current, size, disabled, describedBy: noteId, select };
  return (
    <RadioGroupContext.Provider value={ctx}>
      <fieldset
        className={cx('radio-group', className)}
        data-orientation={orientation}
        data-invalid={hasError ? '' : undefined}
        disabled={disabled || undefined}
      >
        <legend className={cx('radio-group-label', hideLabel && 'kit-sr-only')}>{label}</legend>
        <div className="radio-group-items">
          {options?.map((o) => <Radio key={o.value} value={o.value} label={o.label} description={o.description} disabled={o.disabled} />)}
          {children}
        </div>
        {hasError ? (
          <p id={noteId} className="field-error">
            {error}
          </p>
        ) : hint ? (
          <p id={noteId} className="field-hint">
            {hint}
          </p>
        ) : null}
      </fieldset>
    </RadioGroupContext.Provider>
  );
}

export interface SwitchProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onChange' | 'value' | 'defaultValue' | 'type' | 'role'> {
  label: ReactNode;
  description?: ReactNode;
  hideLabel?: boolean | undefined;
  /** Controlled state. */
  checked?: boolean | undefined;
  /** Uncontrolled starting state. */
  defaultChecked?: boolean | undefined;
  onChange?: ((checked: boolean) => void) | undefined;
  size?: ChoiceSize | undefined;
  /** With a name, a hidden input submits `value` (default "on") while the switch is on. */
  name?: string | undefined;
  value?: string | undefined;
}

/** An on or off setting that applies at once. Space and Enter toggle it. */
export const Switch = forwardRef<HTMLButtonElement, SwitchProps>(function Switch(
  { label, description, hideLabel, checked, defaultChecked = false, onChange, size = 'md', name, value = 'on', className, id, disabled, onClick, ...rest },
  ref,
) {
  const auto = useId();
  const buttonId = id ?? `${auto}-switch`;
  const labelId = `${auto}-label`;
  const descId = description ? `${auto}-desc` : undefined;
  const [inner, setInner] = useState(defaultChecked);
  const on = checked ?? inner;
  const describedBy = [rest['aria-describedby'], descId].filter(Boolean).join(' ') || undefined;
  return (
    <span className={cx('choice', 'switch', className)} data-size={size} data-disabled={disabled ? '' : undefined}>
      <button
        {...rest}
        ref={ref}
        id={buttonId}
        type="button"
        role="switch"
        className="switch-track"
        aria-checked={on}
        aria-labelledby={rest['aria-labelledby'] ?? (rest['aria-label'] ? undefined : labelId)}
        aria-describedby={describedBy}
        disabled={disabled}
        onClick={(event) => {
          onClick?.(event);
          if (event.defaultPrevented) return;
          if (checked === undefined) setInner(!on);
          onChange?.(!on);
        }}
      >
        <span className="switch-thumb" aria-hidden="true" />
      </button>
      <ChoiceText htmlFor={buttonId} labelId={labelId} label={label} description={description} descriptionId={descId} hideLabel={hideLabel} />
      {name && on && !disabled ? <input type="hidden" name={name} value={value} /> : null}
    </span>
  );
});
