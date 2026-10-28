/**
 * Small filter controls shared by the Alerts, Inventory, Firmware and Audit screens: a debounced search box
 * that writes to the URL, a segmented single choice, a multi-select toggle group, a site picker that follows
 * the global site filter, date-time fields and the "Showing N of M+" list summary.
 */
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';

import { FormField, Select, TextInput } from '@/components/FormField';
import { Icon, type IconName } from '@/components/Icon';
import { useSiteFilter } from '@/components/shell/ShellContext';
import { cn } from '@/lib/cn';
import { useDebouncedValue } from '@/lib/useDebouncedValue';
import { numberParam } from '@/lib/useUrlState';

// ---------------------------------------------------------------------------------------- search box

export interface SearchFieldProps {
  label: string;
  /** The committed value (from the URL). */
  value: string;
  /** Called with the new text once typing pauses. */
  onCommit: (value: string) => void;
  placeholder?: string;
  hint?: ReactNode;
  delayMs?: number;
  className?: string;
  /** Show a search icon and use type="search" (default true). */
  search?: boolean;
  hideLabel?: boolean;
}

/**
 * Text filter committed after the user pauses typing. Follows outside changes of `value` (e.g. the global
 * search navigating to `?q=`) without echoing them back.
 */
export function SearchField({
  label,
  value,
  onCommit,
  placeholder,
  hint,
  delayMs = 300,
  className,
  search = true,
  hideLabel,
}: SearchFieldProps) {
  const [text, setText] = useState(value);
  const committed = useRef(value);
  const commitRef = useRef(onCommit);
  commitRef.current = onCommit;

  useEffect(() => {
    if (value !== committed.current) {
      committed.current = value;
      setText(value);
    }
  }, [value]);

  const debounced = useDebouncedValue(text, delayMs);
  useEffect(() => {
    const next = debounced.trim();
    if (next !== committed.current.trim()) {
      committed.current = next;
      commitRef.current(next);
    }
  }, [debounced]);

  return (
    <FormField label={label} hint={hint} className={className} hideLabel={hideLabel}>
      <SearchInput
        value={text}
        placeholder={placeholder}
        search={search}
        onChange={setText}
        onEnter={() => {
          const next = text.trim();
          if (next !== committed.current.trim()) {
            committed.current = next;
            commitRef.current(next);
          }
        }}
      />
    </FormField>
  );
}

/** Input that receives the id/aria props FormField clones onto it. */
function SearchInput({
  value,
  onChange,
  onEnter,
  placeholder,
  search,
  ...aria
}: {
  value: string;
  onChange: (v: string) => void;
  onEnter: () => void;
  placeholder?: string;
  search: boolean;
}) {
  return (
    <div className="relative">
      {search ? (
        <Icon
          name="search"
          size={14}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-subtle"
        />
      ) : null}
      <TextInput
        {...aria}
        type={search ? 'search' : 'text'}
        value={value}
        placeholder={placeholder}
        className={search ? 'pl-8' : undefined}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onEnter();
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------------- segmented control

export interface ChoiceOption<V extends string> {
  value: V;
  label: ReactNode;
  icon?: IconName;
}

/** One choice out of a few (radio group styled as a segmented control). Arrow keys move the choice. */
export function SegmentedControl<V extends string>({
  label,
  value,
  options,
  onChange,
  className,
}: {
  label: string;
  value: V;
  options: ChoiceOption<V>[];
  onChange: (value: V) => void;
  className?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    let next = -1;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (i + 1) % options.length;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (i - 1 + options.length) % options.length;
    if (next < 0) return;
    e.preventDefault();
    const opt = options[next];
    if (opt) {
      onChange(opt.value);
      refs.current[next]?.focus();
    }
  };
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn('glass-subtle inline-flex max-w-full gap-1 overflow-x-auto rounded-lg p-1', className)}
    >
      {options.map((o, i) => {
        const selected = o.value === value;
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={cn(
              'inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors duration-fast',
              selected ? 'bg-text/10 text-text shadow-sm' : 'text-text-muted hover:text-text',
            )}
          >
            {o.icon ? <Icon name={o.icon} size={14} /> : null}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** Several independent on/off choices (toggle buttons with aria-pressed). Empty selection = no filter. */
export function ToggleGroup<V extends string>({
  label,
  values,
  options,
  onChange,
  className,
}: {
  label: string;
  values: V[];
  options: ChoiceOption<V>[];
  onChange: (values: V[]) => void;
  className?: string;
}) {
  return (
    <div role="group" aria-label={label} className={cn('flex flex-wrap gap-1.5', className)}>
      {options.map((o) => {
        const on = values.includes(o.value);
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(on ? values.filter((v) => v !== o.value) : [...values, o.value])}
            className={cn(
              'inline-flex h-9 items-center gap-1.5 rounded-md border px-3 text-sm font-medium transition-colors duration-fast',
              on
                ? 'border-accent/60 bg-accent/10 text-text'
                : 'border-text/15 text-text-muted hover:border-text/25 hover:text-text',
            )}
          >
            {o.icon ? <Icon name={o.icon} size={14} /> : null}
            {o.label}
            {on ? <Icon name="check" size={13} className="text-accent" /> : null}
          </button>
        );
      })}
    </div>
  );
}

/** Comma-separated URL value → known values only. */
export function parseList<V extends string>(raw: string, allowed: readonly V[]): V[] {
  return raw
    .split(',')
    .map((s) => s.trim())
    .filter((s): s is V => (allowed as readonly string[]).includes(s));
}

// --------------------------------------------------------------------------------------------- sites

export interface ResolvedSite {
  /** Send as `site_id`. */
  siteId: number | undefined;
  /** Filter rows client-side to these sites (several sites picked in the top bar). */
  clientSiteIds: number[] | null;
  /** Value for <SiteSelect>. */
  selectValue: string;
}

/**
 * The site a list should ask for: an explicit `site_id` from the URL ("all" = every site) wins; otherwise
 * the global site filter when it has exactly one site; several global sites filter client-side.
 */
export function resolveSite(urlValue: string, globalIds: number[]): ResolvedSite {
  if (urlValue === 'all') return { siteId: undefined, clientSiteIds: null, selectValue: 'all' };
  const n = numberParam(urlValue);
  if (n !== undefined) return { siteId: n, clientSiteIds: null, selectValue: String(n) };
  if (globalIds.length === 1)
    return { siteId: globalIds[0], clientSiteIds: null, selectValue: String(globalIds[0]) };
  return { siteId: undefined, clientSiteIds: globalIds.length > 1 ? globalIds : null, selectValue: 'all' };
}

/** Site picker for a list; defaults to the global site filter. `onChange` gets the URL value to store. */
export function SiteSelect({
  urlValue,
  onChange,
  className,
}: {
  urlValue: string;
  onChange: (urlValue: string) => void;
  className?: string;
}) {
  const { siteIds, sites } = useSiteFilter();
  const resolved = resolveSite(urlValue, siteIds);
  const allLabel = siteIds.length > 1 ? `Sites in the top-bar filter (${siteIds.length})` : 'All sites';
  return (
    <FormField label="Site" className={className}>
      <Select
        value={resolved.selectValue}
        onChange={(e) => {
          const v = e.target.value;
          // "All" overrides a single global site explicitly; otherwise it just follows the top bar.
          onChange(v === 'all' ? (siteIds.length === 1 ? 'all' : '') : v);
        }}
        options={[
          { value: 'all', label: allLabel },
          ...sites.map((s) => ({ value: String(s.id), label: `${s.code} · ${s.name}` })),
        ]}
      />
    </FormField>
  );
}

// ---------------------------------------------------------------------------------------- date-times

/** `datetime-local` value ("2026-10-26T09:30") → ISO string, or undefined when empty/invalid. */
export function localToIso(value: string): string | undefined {
  if (!value) return undefined;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? undefined : new Date(ms).toISOString();
}

export function DateTimeField({
  label,
  value,
  onChange,
  hint,
  className,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <FormField label={label} hint={hint} className={className}>
      <TextInput type="datetime-local" value={value} onChange={(e) => onChange(e.target.value)} />
    </FormField>
  );
}

// ------------------------------------------------------------------------------------------- summary

/** "Showing 50 of 50+ servers" while the server has more pages, "Showing all 12 servers" otherwise. */
export function listSummary(count: number, hasMore: boolean, noun: string): string {
  if (hasMore) return `Showing ${count} of ${count}+ ${noun} · more available`;
  return count === 1 ? `Showing 1 ${noun.replace(/s$/, '')}` : `Showing all ${count} ${noun}`;
}
