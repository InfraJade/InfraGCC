import { useEffect, useId, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { errorMessage } from '@/api/errors';
import { cn } from '@/lib/cn';
import { useDebouncedValue } from '@/lib/useDebouncedValue';

import { HealthBadge } from '../HealthBadge';
import { Icon, type IconName } from '../Icon';
import { useDismiss } from '../overlay';
import { Spinner } from '../Spinner';
import type { SearchResult, SearchSource } from './ShellContext';

const kindIcon: Record<string, IconName> = {
  site: 'building',
  room: 'layers',
  rack: 'rack',
  server: 'server',
  component: 'chip',
  alert: 'bell',
};

export interface GlobalSearchProps {
  search: SearchSource | null;
  placeholder?: string;
  debounceMs?: number;
  minChars?: number;
  className?: string;
}

/** Debounced global search with a results dropdown (combobox pattern). Ctrl/⌘+K focuses it. */
export function GlobalSearch({
  search,
  placeholder = 'Search servers, racks, serials…',
  debounceMs = 250,
  minChars = 2,
  className,
}: GlobalSearchProps) {
  const id = useId();
  const listId = `${id}-results`;
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounced = useDebouncedValue(q.trim(), debounceMs);

  useDismiss([wrapRef], open, () => setOpen(false));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    if (!search || debounced.length < minChars) {
      setResults([]);
      setLoading(false);
      setError(null);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    search(debounced, ctrl.signal)
      .then((r) => {
        if (!ctrl.signal.aborted) {
          setResults(r);
          setActive(0);
        }
      })
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setError(e);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [debounced, search, minChars]);

  const go = (r: SearchResult) => {
    setOpen(false);
    setQ('');
    void navigate(r.to);
  };

  const showPanel = open && q.trim().length >= minChars;

  return (
    <div ref={wrapRef} className={cn('relative w-full max-w-md', className)}>
      <Icon
        name="search"
        size={16}
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-subtle"
      />
      <input
        ref={inputRef}
        type="search"
        role="combobox"
        aria-label="Global search"
        aria-expanded={showPanel}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showPanel && results[active] ? `${listId}-${active}` : undefined}
        placeholder={placeholder}
        value={q}
        disabled={!search}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActive((a) => Math.min(a + 1, Math.max(0, results.length - 1)));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActive((a) => Math.max(0, a - 1));
          } else if (e.key === 'Enter') {
            const r = results[active];
            if (r) {
              e.preventDefault();
              go(r);
            }
          } else if (e.key === 'Escape') {
            setOpen(false);
          }
        }}
        className="h-9 w-full rounded-lg border border-text/10 bg-text/5 pl-9 pr-16 text-sm text-text placeholder:text-text-subtle focus:border-accent focus:bg-surface/60 focus:outline-none focus:ring-2 focus:ring-accent/30 disabled:opacity-60"
      />
      <span className="pointer-events-none absolute right-2.5 top-1/2 hidden -translate-y-1/2 items-center gap-1 sm:flex">
        {loading ? <Spinner size={14} className="text-text-subtle" /> : null}
        <kbd className="rounded border border-text/15 px-1.5 font-mono text-[10px] text-text-subtle">
          Ctrl K
        </kbd>
      </span>

      {showPanel ? (
        <div className="glass-strong absolute left-0 right-0 top-full z-dropdown mt-2 overflow-hidden rounded-xl">
          <ul
            id={listId}
            role="listbox"
            aria-label="Search results"
            className="max-h-80 overflow-y-auto p-1.5"
          >
            {error ? (
              <li role="presentation" className="px-3 py-3 text-sm text-health-critical">
                {errorMessage(error)}
              </li>
            ) : results.length === 0 ? (
              <li role="presentation" className="px-3 py-3 text-sm text-text-subtle">
                {loading || debounced !== q.trim() ? 'Searching…' : `No results for “${q.trim()}”`}
              </li>
            ) : (
              results.map((r, i) => (
                // Keyboard selection is handled by the combobox input (aria-activedescendant).
                // eslint-disable-next-line jsx-a11y/click-events-have-key-events
                <li
                  key={`${r.kind}-${r.id}`}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => go(r)}
                  onMouseEnter={() => setActive(i)}
                  className={cn(
                    'flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2',
                    i === active && 'bg-text/10',
                  )}
                >
                  <Icon name={kindIcon[r.kind] ?? 'search'} size={16} className="shrink-0 text-text-subtle" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-text">{r.label}</span>
                    <span className="block truncate text-xs text-text-subtle">
                      <span className="capitalize">{r.kind}</span>
                      {r.sublabel ? ` · ${r.sublabel}` : ''}
                    </span>
                  </span>
                  {r.health !== undefined ? <HealthBadge health={r.health} size="sm" /> : null}
                </li>
              ))
            )}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
