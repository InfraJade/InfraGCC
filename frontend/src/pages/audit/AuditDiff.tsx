import { useMemo } from 'react';

import { Pill } from '@/components/Badges';
import { cn } from '@/lib/cn';

import { diffObjects, formatDiffValue, type ChangeKind } from './diff';

const KIND: Record<ChangeKind, { label: string; cls: string; row: string }> = {
  changed: {
    label: 'Changed',
    cls: 'text-accent bg-accent/10 ring-1 ring-inset ring-accent/30',
    row: 'bg-accent/[0.06]',
  },
  added: {
    label: 'Added',
    cls: 'text-health-ok bg-health-ok/10 ring-1 ring-inset ring-health-ok/30',
    row: 'bg-health-ok/[0.06]',
  },
  removed: {
    label: 'Removed',
    cls: 'text-health-critical bg-health-critical/10 ring-1 ring-inset ring-health-critical/30',
    row: 'bg-health-critical/[0.06]',
  },
  unchanged: { label: 'Same', cls: 'text-text-subtle bg-text/5 ring-1 ring-inset ring-text/10', row: '' },
};

/** Before/after as a field table: each row says in words whether the field changed, was added or removed. */
export function AuditDiff({
  before,
  after,
}: {
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}) {
  const rows = useMemo(() => diffObjects(before, after), [before, after]);
  if (rows.length === 0)
    return (
      <p className="text-sm text-text-subtle">No before or after values were recorded for this action.</p>
    );
  const counts = rows.reduce<Record<ChangeKind, number>>(
    (acc, r) => ({ ...acc, [r.kind]: acc[r.kind] + 1 }),
    { changed: 0, added: 0, removed: 0, unchanged: 0 },
  );
  const parts = (['changed', 'added', 'removed'] as const)
    .filter((k) => counts[k] > 0)
    .map((k) => `${counts[k]} ${KIND[k].label.toLowerCase()}`);
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-text-muted">
        {parts.length ? parts.join(', ') : 'No field changed'}
        {counts.unchanged ? `, ${counts.unchanged} unchanged` : ''}
      </p>
      <div className="overflow-x-auto rounded-lg ring-1 ring-text/10">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">Changes between the before and after values</caption>
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-text-muted">
              <th scope="col" className="px-3 py-2 font-semibold">
                Field
              </th>
              <th scope="col" className="px-3 py-2 font-semibold">
                Change
              </th>
              <th scope="col" className="px-3 py-2 font-semibold">
                Before
              </th>
              <th scope="col" className="px-3 py-2 font-semibold">
                After
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.key}
                data-change={r.kind}
                className={cn('border-t hairline align-top', KIND[r.kind].row)}
              >
                <th scope="row" className="px-3 py-2 text-left font-mono text-xs font-medium text-text">
                  {r.key}
                </th>
                <td className="px-3 py-2">
                  <Pill className={KIND[r.kind].cls}>{KIND[r.kind].label}</Pill>
                </td>
                <td className="px-3 py-2">
                  <DiffValue
                    value={r.before}
                    missing={r.kind === 'added'}
                    strike={r.kind === 'changed' || r.kind === 'removed'}
                  />
                </td>
                <td className="px-3 py-2">
                  <DiffValue value={r.after} missing={r.kind === 'removed'} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DiffValue({ value, missing, strike }: { value: unknown; missing?: boolean; strike?: boolean }) {
  if (missing) return <span className="text-xs italic text-text-subtle">not set</span>;
  return (
    <code
      className={cn(
        'whitespace-pre-wrap break-all font-mono text-xs text-text',
        strike && 'text-text-muted line-through decoration-text-subtle',
      )}
    >
      {formatDiffValue(value)}
    </code>
  );
}
