import { useMemo, useState, type ReactNode } from 'react';

import { errorMessage } from '@/api/errors';
import { cn } from '@/lib/cn';
import { readJson, writeJson } from '@/lib/storage';

import { Button } from './Button';
import { EmptyState } from './EmptyState';
import { Icon } from './Icon';
import { Popover } from './Popover';
import { Skeleton } from './Skeleton';

export type SortDirection = 'asc' | 'desc';
export interface SortState {
  id: string;
  direction: SortDirection;
}

export interface Column<T> {
  id: string;
  header: ReactNode;
  /** Plain-text name for the column picker when `header` isn't a string. */
  label?: string;
  cell: (row: T) => ReactNode;
  sortable?: boolean;
  align?: 'left' | 'right' | 'center';
  /** e.g. "8rem" */
  width?: string;
  /** Can be hidden from the column picker (default true). */
  hideable?: boolean;
  defaultHidden?: boolean;
  className?: string;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: readonly T[];
  getRowId: (row: T) => string | number;
  /** Accessible table name (visually hidden). */
  caption: string;
  /** Server-driven sorting: the table never reorders rows itself. Click cycles asc → desc → none. */
  sort?: SortState | null;
  onSortChange?: (sort: SortState | null) => void;
  /** First page loading → skeleton rows. */
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  /** Cursor pagination: show "Load more" while the server returned a next_cursor. */
  hasMore?: boolean;
  onLoadMore?: () => void;
  loadingMore?: boolean;
  emptyTitle?: string;
  emptyDescription?: ReactNode;
  onRowClick?: (row: T) => void;
  /** Accessible label for a clickable row (default: first cell text is not available, so pass one). */
  rowLabel?: (row: T) => string;
  /** Controlled hidden columns; otherwise internal (and persisted when `persistKey` is set). */
  hiddenColumns?: string[];
  onHiddenColumnsChange?: (ids: string[]) => void;
  persistKey?: string;
  /** Scroll container height with a sticky header, e.g. "70vh". */
  maxHeight?: string;
  toolbar?: ReactNode;
  /** e.g. "Showing 50 of 312" */
  summary?: ReactNode;
  dense?: boolean;
  className?: string;
}

const alignClass = { left: 'text-left', right: 'text-right', center: 'text-center' } as const;

function nextSort(current: SortState | null | undefined, id: string): SortState | null {
  if (!current || current.id !== id) return { id, direction: 'asc' };
  if (current.direction === 'asc') return { id, direction: 'desc' };
  return null;
}

export function DataTable<T>({
  columns,
  rows,
  getRowId,
  caption,
  sort,
  onSortChange,
  loading,
  error,
  onRetry,
  hasMore,
  onLoadMore,
  loadingMore,
  emptyTitle = 'Nothing to show',
  emptyDescription,
  onRowClick,
  rowLabel,
  hiddenColumns,
  onHiddenColumnsChange,
  persistKey,
  maxHeight,
  toolbar,
  summary,
  dense,
  className,
}: DataTableProps<T>) {
  const defaults = useMemo(() => columns.filter((c) => c.defaultHidden).map((c) => c.id), [columns]);
  const [internalHidden, setInternalHidden] = useState<string[]>(() =>
    persistKey ? readJson(`gcc.table.${persistKey}.hidden`, defaults, isStringArray) : defaults,
  );
  const hidden = hiddenColumns ?? internalHidden;
  const setHidden = (ids: string[]) => {
    if (onHiddenColumnsChange) onHiddenColumnsChange(ids);
    if (!hiddenColumns) {
      setInternalHidden(ids);
      if (persistKey) writeJson(`gcc.table.${persistKey}.hidden`, ids);
    }
  };
  const visible = columns.filter((c) => !hidden.includes(c.id));
  const hideable = columns.filter((c) => c.hideable !== false);
  const cellPad = dense ? 'px-3 py-1.5' : 'px-4 py-2.5';

  let body: ReactNode;
  if (loading) {
    body = Array.from({ length: 6 }, (_, i) => (
      <tr key={`sk-${i}`} className="border-t hairline">
        {visible.map((c) => (
          <td key={c.id} className={cellPad}>
            <Skeleton className="h-3.5 w-3/4" />
          </td>
        ))}
      </tr>
    ));
  } else if (error && rows.length === 0) {
    body = (
      <tr>
        <td colSpan={visible.length}>
          <EmptyState
            tone="error"
            title="Couldn't load this list"
            description={errorMessage(error)}
            action={
              onRetry ? (
                <Button icon="refresh" size="sm" onClick={onRetry}>
                  Retry
                </Button>
              ) : undefined
            }
          />
        </td>
      </tr>
    );
  } else if (rows.length === 0) {
    body = (
      <tr>
        <td colSpan={visible.length}>
          <EmptyState title={emptyTitle} description={emptyDescription} />
        </td>
      </tr>
    );
  } else {
    body = rows.map((row) => {
      const id = getRowId(row);
      const clickable = Boolean(onRowClick);
      return (
        // Rows are focusable and activate on Enter/Space when clickable; links inside cells still work.
        <tr
          key={id}
          data-row-id={id}
          tabIndex={clickable ? 0 : undefined}
          aria-label={clickable && rowLabel ? rowLabel(row) : undefined}
          onClick={clickable ? () => onRowClick?.(row) : undefined}
          onKeyDown={
            clickable
              ? (e) => {
                  if (e.target !== e.currentTarget) return;
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onRowClick?.(row);
                  }
                }
              : undefined
          }
          className={cn(
            'border-t hairline transition-colors duration-fast',
            clickable &&
              'cursor-pointer hover:bg-text/[0.04] focus-visible:bg-text/[0.06] focus-visible:outline-offset-[-2px]',
          )}
        >
          {visible.map((c) => (
            <td
              key={c.id}
              className={cn(cellPad, 'align-middle text-sm', alignClass[c.align ?? 'left'], c.className)}
            >
              {c.cell(row)}
            </td>
          ))}
        </tr>
      );
    });
  }

  return (
    <div className={cn('glass flex flex-col overflow-hidden rounded-xl', className)}>
      {toolbar || hideable.length > 0 || summary ? (
        <div className="flex flex-wrap items-center gap-2 border-b hairline px-3 py-2">
          <div className="flex flex-1 flex-wrap items-center gap-2">{toolbar}</div>
          {summary ? <div className="text-xs text-text-muted">{summary}</div> : null}
          {hideable.length > 0 ? (
            <Popover
              label="Visible columns"
              trigger={(p) => (
                <Button {...p} size="sm" variant="ghost" icon="columns">
                  Columns
                </Button>
              )}
            >
              <fieldset className="p-1.5">
                <legend className="px-1 pb-1 text-xs font-medium uppercase tracking-wider text-text-subtle">
                  Show columns
                </legend>
                {hideable.map((c) => {
                  const name = c.label ?? (typeof c.header === 'string' ? c.header : c.id);
                  const checked = !hidden.includes(c.id);
                  return (
                    <label
                      key={c.id}
                      className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm hover:bg-text/5"
                    >
                      <input
                        type="checkbox"
                        className="accent-[rgb(var(--c-accent))]"
                        checked={checked}
                        disabled={checked && visible.length === 1}
                        onChange={() =>
                          setHidden(checked ? [...hidden, c.id] : hidden.filter((h) => h !== c.id))
                        }
                      />
                      {name}
                    </label>
                  );
                })}
              </fieldset>
            </Popover>
          ) : null}
        </div>
      ) : null}

      <div className="overflow-auto" style={maxHeight ? { maxHeight } : undefined}>
        <table className="w-full border-collapse" aria-busy={loading || loadingMore || undefined}>
          <caption className="sr-only">{caption}</caption>
          <thead className="sticky top-0 z-10 bg-surface/90 backdrop-blur-md">
            <tr>
              {visible.map((c) => {
                const active = sort?.id === c.id ? sort.direction : null;
                const ariaSort =
                  active === 'asc'
                    ? 'ascending'
                    : active === 'desc'
                      ? 'descending'
                      : c.sortable
                        ? 'none'
                        : undefined;
                return (
                  <th
                    key={c.id}
                    scope="col"
                    aria-sort={ariaSort}
                    style={c.width ? { width: c.width } : undefined}
                    className={cn(
                      cellPad,
                      'whitespace-nowrap text-xs font-semibold uppercase tracking-wider text-text-muted',
                      alignClass[c.align ?? 'left'],
                    )}
                  >
                    {c.sortable && onSortChange ? (
                      <button
                        type="button"
                        onClick={() => onSortChange(nextSort(sort, c.id))}
                        className={cn(
                          'group inline-flex items-center gap-1 rounded uppercase hover:text-text',
                          active && 'text-text',
                        )}
                      >
                        {c.header}
                        <Icon
                          name={
                            active === 'asc' ? 'arrow-up' : active === 'desc' ? 'arrow-down' : 'arrow-up-down'
                          }
                          size={12}
                          className={active ? 'text-accent' : 'opacity-40 group-hover:opacity-80'}
                        />
                      </button>
                    ) : (
                      c.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </div>

      {rows.length > 0 && (hasMore || error) ? (
        <div className="flex items-center justify-center gap-3 border-t hairline px-3 py-2.5">
          {error ? (
            <span role="alert" className="text-sm text-health-critical">
              {errorMessage(error)}
            </span>
          ) : null}
          {hasMore && onLoadMore ? (
            <Button size="sm" onClick={onLoadMore} loading={loadingMore} icon="chevron-down">
              {loadingMore ? 'Loading…' : 'Load more'}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => typeof x === 'string');
}
