import { Link } from 'react-router-dom';

import type { Alert } from '@/api/types';
import { AlertStateBadge, SeverityBadge } from '@/components/Badges';
import { Button } from '@/components/Button';
import type { Column } from '@/components/DataTable';
import { Age, Reading } from '@/components/Reading';
import { formatValue } from '@/lib/format';

/** Measured value (with its age) against the limit it crossed. */
export function AlertValue({ alert, unit }: { alert: Alert; unit: string | undefined }) {
  if (alert.value === null && alert.threshold === null) return <span className="text-text-subtle">—</span>;
  return (
    <span className="inline-flex flex-col">
      {alert.value !== null ? (
        <Reading value={alert.value} unit={unit} time={alert.last_seen_at} />
      ) : (
        <span className="text-text-subtle">no value</span>
      )}
      {alert.threshold !== null ? (
        <span className="text-xs text-text-muted">limit {formatValue(alert.threshold, unit)}</span>
      ) : null}
    </span>
  );
}

/** Server link + site code; stops the row click so the link navigates instead of opening the drawer. */
export function AlertTarget({ alert }: { alert: Alert }) {
  return (
    <span className="inline-flex flex-col">
      {alert.server ? (
        <Link
          to={`/servers/${alert.server.id}`}
          onClick={(e) => e.stopPropagation()}
          className="font-medium text-accent hover:underline"
        >
          {alert.server.name}
        </Link>
      ) : (
        <span className="text-text-muted">{alert.collector ? `Collector ${alert.collector.name}` : '—'}</span>
      )}
      {alert.site ? <span className="text-xs text-text-subtle">{alert.site.code}</span> : null}
    </span>
  );
}

export interface AlertColumnsOptions {
  units: Record<string, string>;
  canAck: boolean;
  onQuickAck: (alert: Alert) => void;
  /** Alert id being acknowledged from its row. */
  ackingId: number | null;
}

export function alertColumns({ units, canAck, onQuickAck, ackingId }: AlertColumnsOptions): Column<Alert>[] {
  const cols: Column<Alert>[] = [
    {
      id: 'severity',
      header: 'Severity',
      cell: (a) => <SeverityBadge severity={a.severity} />,
      hideable: false,
      width: '7.5rem',
    },
    {
      id: 'title',
      header: 'Alert',
      hideable: false,
      cell: (a) => (
        <span className="block max-w-[22rem]">
          <span className="block font-medium text-text">{a.title}</span>
          <span className="block truncate text-xs text-text-subtle" title={a.rule.name}>
            {a.rule.name}
          </span>
        </span>
      ),
    },
    { id: 'server', header: 'Server', cell: (a) => <AlertTarget alert={a} /> },
    {
      id: 'component',
      header: 'Component',
      cell: (a) => a.component || <span className="text-text-subtle">—</span>,
    },
    {
      id: 'state',
      header: 'State',
      cell: (a) => <AlertStateBadge state={a.state} muted={a.muted} />,
    },
    {
      id: 'value',
      header: 'Value / limit',
      cell: (a) => <AlertValue alert={a} unit={a.metric ? units[a.metric] : undefined} />,
    },
    { id: 'opened', header: 'Opened', cell: (a) => <Age time={a.opened_at} staleAfterMs={Infinity} /> },
    {
      id: 'last_seen',
      header: 'Last seen',
      cell: (a) => <Age time={a.last_seen_at} staleAfterMs={Infinity} />,
    },
    {
      id: 'occurrences',
      header: 'Count',
      label: 'Occurrences',
      align: 'right',
      cell: (a) => <span className="tabular">{a.occurrences}</span>,
    },
    {
      id: 'acked_by',
      header: 'Acked by',
      cell: (a) =>
        a.acked_by ? (
          <span className="inline-flex flex-col">
            <span>{a.acked_by}</span>
            {a.acked_at ? <Age time={a.acked_at} staleAfterMs={Infinity} className="text-xs" /> : null}
          </span>
        ) : (
          <span className="text-text-subtle">—</span>
        ),
    },
  ];
  if (canAck) {
    cols.push({
      id: 'actions',
      header: <span className="sr-only">Actions</span>,
      label: 'Actions',
      hideable: false,
      align: 'right',
      cell: (a) =>
        a.state === 'open' ? (
          <Button
            size="sm"
            icon="check"
            aria-label={`Acknowledge alert: ${a.title}`}
            loading={ackingId === a.id}
            onClick={(e) => {
              e.stopPropagation();
              onQuickAck(a);
            }}
          >
            Ack
          </Button>
        ) : null,
    });
  }
  return cols;
}
