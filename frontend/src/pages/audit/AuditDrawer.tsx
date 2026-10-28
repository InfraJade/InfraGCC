import type { AuditEntry } from '@/api/types';
import { Drawer } from '@/components/Drawer';
import { KeyValueList } from '@/components/KeyValue';
import { Age } from '@/components/Reading';
import { formatTimestamp } from '@/lib/format';

import { AuditDiff } from './AuditDiff';

function RawJson({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="min-w-0">
      <h4 className="mb-1 text-xs font-medium text-text-muted">{label}</h4>
      <pre className="max-h-72 overflow-auto rounded-md bg-surface-sunken/60 p-3 font-mono text-xs text-text ring-1 ring-text/10">
        {value === null || value === undefined ? 'null' : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

export function AuditDrawer({ entry, onClose }: { entry: AuditEntry | null; onClose: () => void }) {
  return (
    <Drawer
      open={entry !== null}
      onClose={onClose}
      widthClassName="max-w-2xl"
      title={entry ? entry.action : 'Audit entry'}
      description={entry ? `${entry.user_name} · ${formatTimestamp(entry.time)}` : undefined}
    >
      {entry ? (
        <div className="flex flex-col gap-5">
          <KeyValueList
            items={[
              {
                label: 'When',
                value: (
                  <span className="inline-flex flex-wrap items-baseline gap-x-1.5">
                    {formatTimestamp(entry.time)}
                    <Age time={entry.time} staleAfterMs={Infinity} className="text-xs" />
                  </span>
                ),
              },
              {
                label: 'User',
                value: entry.user_sub ? `${entry.user_name} (${entry.user_sub})` : entry.user_name,
              },
              { label: 'Action', value: <code>{entry.action}</code> },
              {
                label: 'Object',
                value: `${entry.object_type}${entry.object_id ? ` #${entry.object_id}` : ''}`,
              },
              { label: 'IP address', value: entry.ip },
              {
                label: 'Request id',
                value: entry.request_id ? <code className="text-xs">{entry.request_id}</code> : null,
              },
            ]}
          />
          <section aria-labelledby="audit-diff-title">
            <h3
              id="audit-diff-title"
              className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted"
            >
              What changed
            </h3>
            <AuditDiff before={entry.before} after={entry.after} />
          </section>
          <details className="group">
            <summary className="cursor-pointer text-sm font-medium text-text-muted hover:text-text">
              Raw JSON
            </summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <RawJson label="Before" value={entry.before} />
              <RawJson label="After" value={entry.after} />
            </div>
          </details>
        </div>
      ) : null}
    </Drawer>
  );
}
