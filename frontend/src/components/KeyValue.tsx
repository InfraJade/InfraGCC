import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';

export interface KeyValueItem {
  label: string;
  value: ReactNode;
  /** Hide the row when the value is null/undefined/'' (default true). */
  hideEmpty?: boolean;
}

/** Two-column definition list for detail panels; empty values render as "—" unless hidden. */
export function KeyValueList({
  items,
  className,
  columns = 1,
}: {
  items: KeyValueItem[];
  className?: string;
  columns?: 1 | 2;
}) {
  const rows = items.filter(
    (i) => !(i.hideEmpty === true && (i.value === null || i.value === undefined || i.value === '')),
  );
  return (
    <dl
      className={cn(
        'grid gap-x-4 gap-y-2 text-sm',
        columns === 2 ? 'grid-cols-[auto_1fr] sm:grid-cols-[auto_1fr_auto_1fr]' : 'grid-cols-[auto_1fr]',
        className,
      )}
    >
      {rows.map((i) => (
        <div key={i.label} className="contents">
          <dt className="text-text-muted">{i.label}</dt>
          <dd className="min-w-0 break-words text-text">
            {i.value === null || i.value === undefined || i.value === '' ? (
              <span className="text-text-subtle">—</span>
            ) : (
              i.value
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
