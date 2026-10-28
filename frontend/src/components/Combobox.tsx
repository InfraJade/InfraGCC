import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

import { controlClass } from './FormField';
import { Icon } from './Icon';
import { useDismiss } from './overlay';
import { Spinner } from './Spinner';

export interface ComboboxOption {
  value: string;
  label: string;
  description?: string;
  icon?: ReactNode;
}

export interface ComboboxProps {
  options: readonly ComboboxOption[];
  value: string | null;
  onChange: (value: string | null) => void;
  placeholder?: string;
  /** Accessible name when not wrapped in a FormField. */
  'aria-label'?: string;
  id?: string;
  /** Async mode: called with the typed text; parent supplies filtered `options`. Otherwise filters locally. */
  onInputChange?: (text: string) => void;
  loading?: boolean;
  emptyText?: string;
  clearable?: boolean;
  disabled?: boolean;
  className?: string;
  'aria-describedby'?: string;
  'aria-invalid'?: boolean;
}

/** Searchable single select (WAI-ARIA 1.2 combobox with a listbox popup). */
export function Combobox({
  options,
  value,
  onChange,
  placeholder = 'Search…',
  id,
  onInputChange,
  loading,
  emptyText = 'No matches',
  clearable = true,
  disabled,
  className,
  ...aria
}: ComboboxProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const listId = `${inputId}-list`;
  const selected = options.find((o) => o.value === value) ?? null;
  const [text, setText] = useState(selected?.label ?? '');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Show the selected label when the value changes from outside.
  useEffect(() => {
    if (!open) setText(selected?.label ?? '');
  }, [selected?.label, open]);

  const filtered = useMemo(() => {
    if (onInputChange) return options;
    const q = text.trim().toLowerCase();
    if (!q || q === selected?.label.toLowerCase()) return options;
    return options.filter(
      (o) => o.label.toLowerCase().includes(q) || o.description?.toLowerCase().includes(q),
    );
  }, [options, text, onInputChange, selected?.label]);

  useDismiss([wrapRef], open, () => {
    setOpen(false);
    setText(selected?.label ?? '');
  });

  const choose = (o: ComboboxOption) => {
    onChange(o.value);
    setText(o.label);
    setOpen(false);
  };

  return (
    <div ref={wrapRef} className={cn('relative', className)}>
      <input
        id={inputId}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && filtered[active] ? `${listId}-${active}` : undefined}
        aria-label={aria['aria-label']}
        aria-describedby={aria['aria-describedby']}
        aria-invalid={aria['aria-invalid']}
        autoComplete="off"
        disabled={disabled}
        placeholder={placeholder}
        value={text}
        className={cn(controlClass, 'h-9 pr-14')}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
          setActive(0);
          onInputChange?.(e.target.value);
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setOpen(true);
            setActive((a) => Math.min(a + 1, Math.max(0, filtered.length - 1)));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === 'Enter') {
            const o = filtered[active];
            if (open && o) {
              e.preventDefault();
              choose(o);
            }
          } else if (e.key === 'Escape') {
            setOpen(false);
            setText(selected?.label ?? '');
          }
        }}
      />
      <div className="absolute inset-y-0 right-2 flex items-center gap-1 text-text-subtle">
        {loading ? <Spinner size={14} /> : null}
        {clearable && value !== null && !disabled ? (
          <button
            type="button"
            aria-label="Clear selection"
            className="rounded p-0.5 hover:text-text"
            onClick={() => {
              onChange(null);
              setText('');
              onInputChange?.('');
            }}
          >
            <Icon name="x" size={14} />
          </button>
        ) : (
          <Icon name="chevron-down" size={14} />
        )}
      </div>
      {open ? (
        <ul
          id={listId}
          role="listbox"
          aria-label={aria['aria-label'] ?? 'Options'}
          className="glass-strong absolute z-dropdown mt-1 max-h-64 w-full overflow-auto rounded-lg p-1"
        >
          {filtered.length === 0 ? (
            <li className="px-3 py-2 text-sm text-text-subtle" role="presentation">
              {loading ? 'Searching…' : emptyText}
            </li>
          ) : (
            filtered.map((o, i) => (
              // Keyboard selection is handled by the combobox input (aria-activedescendant).
              // eslint-disable-next-line jsx-a11y/click-events-have-key-events
              <li
                key={o.value}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={o.value === value}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(o)}
                onMouseEnter={() => setActive(i)}
                className={cn(
                  'flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-sm',
                  i === active ? 'bg-text/10 text-text' : 'text-text',
                )}
              >
                {o.icon}
                <span className="flex-1">
                  <span className="block">{o.label}</span>
                  {o.description ? (
                    <span className="block text-xs text-text-subtle">{o.description}</span>
                  ) : null}
                </span>
                {o.value === value ? <Icon name="check" size={14} className="text-accent" /> : null}
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}
