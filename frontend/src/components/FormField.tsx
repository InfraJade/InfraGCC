import {
  cloneElement,
  forwardRef,
  isValidElement,
  useId,
  type InputHTMLAttributes,
  type ReactElement,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react';

import { cn } from '@/lib/cn';

import { Icon } from './Icon';

export const controlClass =
  'w-full rounded-md border border-text/15 bg-surface-sunken/60 px-3 text-sm text-text placeholder:text-text-subtle transition-colors duration-fast hover:border-text/25 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30 disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-health-critical';

export interface FormFieldProps {
  label: ReactNode;
  /** The control; it receives id, aria-describedby, aria-invalid and required. */
  children: ReactElement<Record<string, unknown>>;
  hint?: ReactNode;
  error?: string | null;
  required?: boolean;
  className?: string;
  /** Hide the label visually (still announced). */
  hideLabel?: boolean;
}

/** Label + control + hint + error, wired for screen readers. */
export function FormField({ label, children, hint, error, required, className, hideLabel }: FormFieldProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errId].filter(Boolean).join(' ') || undefined;
  const control = isValidElement(children)
    ? cloneElement(children, {
        id,
        'aria-describedby': describedBy,
        'aria-invalid': error ? true : undefined,
        required,
      })
    : children;
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <label htmlFor={id} className={cn('text-xs font-medium text-text-muted', hideLabel && 'sr-only')}>
        {label}
        {required ? (
          <span className="ml-0.5 text-health-critical" aria-hidden="true">
            *
          </span>
        ) : null}
      </label>
      {control}
      {hint && !error ? (
        <p id={hintId} className="text-xs text-text-subtle">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errId} className="flex items-center gap-1 text-xs text-health-critical">
          <Icon name="triangle-alert" size={12} />
          {error}
        </p>
      ) : null}
    </div>
  );
}

export const TextInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function TextInput({ className, type = 'text', ...rest }, ref) {
    return <input ref={ref} type={type} className={cn(controlClass, 'h-9', className)} {...rest} />;
  },
);

export const NumberInput = forwardRef<
  HTMLInputElement,
  Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & { unit?: string }
>(function NumberInput({ className, unit, ...rest }, ref) {
  return (
    <div className="relative">
      <input
        ref={ref}
        type="number"
        inputMode="decimal"
        className={cn(controlClass, 'tabular h-9', unit && 'pr-12', className)}
        {...rest}
      />
      {unit ? (
        <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-text-subtle">
          {unit}
        </span>
      ) : null}
    </div>
  );
});

export const TextArea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function TextArea({ className, rows = 3, ...rest }, ref) {
    return <textarea ref={ref} rows={rows} className={cn(controlClass, 'py-2', className)} {...rest} />;
  },
);

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'children'> {
  options: SelectOption[];
  placeholder?: string;
}

/** Native select (best keyboard/mobile behavior), styled. */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { options, placeholder, className, ...rest },
  ref,
) {
  return (
    <div className="relative">
      <select ref={ref} className={cn(controlClass, 'h-9 appearance-none pr-9', className)} {...rest}>
        {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
        {options.map((o) => (
          <option key={o.value} value={o.value} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
      </select>
      <Icon
        name="chevron-down"
        size={14}
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-text-subtle"
      />
    </div>
  );
});

export function Checkbox({
  label,
  className,
  ...rest
}: Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & { label: ReactNode }) {
  return (
    <label className={cn('inline-flex cursor-pointer items-center gap-2 text-sm text-text', className)}>
      <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--c-accent))]" {...rest} />
      {label}
    </label>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <span id={`${id}-l`} className="text-sm text-text">
          {label}
        </span>
        {description ? (
          <p id={`${id}-d`} className="text-xs text-text-subtle">
            {description}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={`${id}-l`}
        aria-describedby={description ? `${id}-d` : undefined}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-fast disabled:opacity-50',
          checked ? 'bg-accent' : 'bg-text/20',
        )}
      >
        <span
          className={cn(
            'inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-fast ease-standard',
            checked ? 'translate-x-[18px]' : 'translate-x-0.5',
          )}
        />
      </button>
    </div>
  );
}
