import { useCursorList } from '@/api/hooks';
import type { AuditEntry } from '@/api/types';
import { Button } from '@/components/Button';
import { DataTable, type Column } from '@/components/DataTable';
import { GlassCard } from '@/components/GlassCard';
import { PageHeader } from '@/components/PageHeader';
import { Age } from '@/components/Reading';
import { formatTimestamp } from '@/lib/format';
import { numberParam, useUrlState } from '@/lib/useUrlState';

import { DateTimeField, listSummary, localToIso, SearchField } from './alerts/filterControls';
import { AuditDrawer } from './audit/AuditDrawer';

const DEFAULTS = { user: '', action: '', object_type: '', object_id: '', from: '', to: '', id: '' };

const dash = <span className="text-text-subtle">—</span>;

const columns: Column<AuditEntry>[] = [
  {
    id: 'time',
    header: 'Time',
    hideable: false,
    cell: (e) => (
      <span className="inline-flex flex-col">
        <span className="tabular whitespace-nowrap">{formatTimestamp(e.time)}</span>
        <Age time={e.time} staleAfterMs={Infinity} className="text-xs" />
      </span>
    ),
  },
  {
    id: 'user',
    header: 'User',
    cell: (e) => (
      <span className="inline-flex flex-col">
        <span>{e.user_name}</span>
        {e.user_sub && e.user_sub !== e.user_name ? (
          <span className="text-xs text-text-subtle">{e.user_sub}</span>
        ) : null}
      </span>
    ),
  },
  {
    id: 'action',
    header: 'Action',
    hideable: false,
    cell: (e) => <code className="text-xs">{e.action}</code>,
  },
  {
    id: 'object',
    header: 'Object',
    cell: (e) => (
      <span>
        {e.object_type}
        {e.object_id ? <span className="text-text-muted"> #{e.object_id}</span> : null}
      </span>
    ),
  },
  { id: 'ip', header: 'IP address', cell: (e) => (e.ip ? <code className="text-xs">{e.ip}</code> : dash) },
  {
    id: 'request_id',
    header: 'Request id',
    defaultHidden: true,
    cell: (e) => (e.request_id ? <code className="text-xs">{e.request_id}</code> : dash),
  },
];

export default function AuditPage() {
  const [f, setF] = useUrlState(DEFAULTS);
  const query = {
    user: f.user || undefined,
    action: f.action || undefined,
    object_type: f.object_type || undefined,
    object_id: f.object_id || undefined,
    from: localToIso(f.from),
    to: localToIso(f.to),
  };
  const list = useCursorList<AuditEntry>('/api/v1/audit', query);
  const selectedId = numberParam(f.id);
  const selected = list.items.find((e) => e.id === selectedId) ?? null;
  const filtered = Boolean(f.user || f.action || f.object_type || f.object_id || f.from || f.to);

  return (
    <div>
      <PageHeader
        title="Audit log"
        subtitle="Who changed what and when, newest first. Select an entry to see before and after."
      />

      <GlassCard className="mb-4" as="section" aria-label="Audit filters">
        <div className="grid items-start gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <SearchField
            label="User"
            search={false}
            value={f.user}
            onCommit={(user) => setF({ user })}
            hint="Name or id"
          />
          <SearchField
            label="Action"
            search={false}
            value={f.action}
            onCommit={(action) => setF({ action })}
            placeholder="e.g. alert.ack"
            hint={'End with "." for a prefix'}
          />
          <SearchField
            label="Object type"
            search={false}
            value={f.object_type}
            onCommit={(object_type) => setF({ object_type })}
            placeholder="e.g. server"
          />
          <SearchField
            label="Object id"
            search={false}
            value={f.object_id}
            onCommit={(object_id) => setF({ object_id })}
          />
          <DateTimeField label="From" value={f.from} onChange={(from) => setF({ from })} />
          <DateTimeField label="Before" value={f.to} onChange={(to) => setF({ to })} />
        </div>
        {filtered ? (
          <Button
            className="mt-3"
            size="sm"
            variant="ghost"
            icon="x"
            onClick={() => setF({ user: '', action: '', object_type: '', object_id: '', from: '', to: '' })}
          >
            Clear filters
          </Button>
        ) : null}
      </GlassCard>

      <DataTable<AuditEntry>
        {...list.tableProps}
        columns={columns}
        getRowId={(e) => e.id}
        caption="Audit log"
        persistKey="audit"
        onRowClick={(e) => setF({ id: e.id })}
        rowLabel={(e) => `${e.action} by ${e.user_name}, ${formatTimestamp(e.time)}: show changes`}
        summary={listSummary(list.items.length, list.hasNextPage, 'entries')}
        emptyTitle={filtered ? 'No entries match' : 'Nothing recorded yet'}
        emptyDescription={
          filtered
            ? 'Action and object type need the exact name; try a wider time range.'
            : 'Sign-ins, configuration changes and alert actions appear here.'
        }
      />

      <AuditDrawer entry={selected} onClose={() => setF({ id: null })} />
    </div>
  );
}
