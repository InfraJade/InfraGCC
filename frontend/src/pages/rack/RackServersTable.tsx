import { Link } from 'react-router-dom';

import type { RackServer } from '@/api/types';
import { ServerStatusBadge, SeverityBadge } from '@/components/Badges';
import { DataTable, type Column } from '@/components/DataTable';
import { HealthBadge } from '@/components/HealthBadge';
import { rackRange } from '@/components/RackView';
import { Reading } from '@/components/Reading';

/** A rack server with its health after the live overlay. */
export type RackRow = RackServer & { liveHealth: string };

function uRange(s: RackServer): string {
  return s.position_u === null ? 'Unplaced' : rackRange({ positionU: s.position_u, heightU: s.height_u });
}

const columns: Column<RackRow>[] = [
  {
    id: 'u',
    header: 'U',
    cell: (s) => <span className="tabular font-mono text-xs text-text-muted">{uRange(s)}</span>,
    hideable: false,
    width: '6rem',
  },
  {
    id: 'name',
    header: 'Server',
    hideable: false,
    cell: (s) => (
      <span className="flex flex-col">
        <Link to={`/servers/${s.id}`} className="font-medium text-text hover:text-accent hover:underline">
          {s.name}
        </Link>
        <span className="font-mono text-xs text-text-subtle">{s.bmc_host}</span>
      </span>
    ),
  },
  { id: 'health', header: 'Health', cell: (s) => <HealthBadge health={s.liveHealth} size="sm" /> },
  { id: 'status', header: 'Status', cell: (s) => <ServerStatusBadge status={s.status} /> },
  {
    id: 'model',
    header: 'Model',
    cell: (s) =>
      s.vendor || s.model ? (
        <span className="text-text-muted">{[s.vendor, s.model].filter(Boolean).join(' ')}</span>
      ) : (
        <span className="text-text-subtle">—</span>
      ),
  },
  {
    id: 'inlet',
    header: 'Inlet',
    cell: (s) =>
      s.inlet_temp ? (
        <Reading value={s.inlet_temp.value} unit={s.inlet_temp.unit} time={s.inlet_temp.time} />
      ) : (
        <span className="text-text-subtle">no reading</span>
      ),
  },
  {
    id: 'power',
    header: 'Power',
    cell: (s) =>
      s.power ? (
        <Reading value={s.power.value} unit={s.power.unit} time={s.power.time} />
      ) : (
        <span className="text-text-subtle">no reading</span>
      ),
  },
  {
    id: 'alerts',
    header: 'Open alerts',
    cell: (s) => {
      const n = s.open_alerts ?? 0;
      if (n === 0) return <span className="text-text-subtle">None</span>;
      return (
        <span className="flex items-center gap-2">
          <span className="tabular font-medium text-text">{n}</span>
          {s.worst_alert_severity ? <SeverityBadge severity={s.worst_alert_severity} /> : null}
        </span>
      );
    },
  },
];

/** Servers of a rack, top of the rack first (unplaced servers last). */
export function RackServersTable({ rows, rackName }: { rows: readonly RackRow[]; rackName: string }) {
  const sorted = [...rows].sort((a, b) => (b.position_u ?? -1) - (a.position_u ?? -1));
  return (
    <DataTable
      caption={`Servers in rack ${rackName}`}
      columns={columns}
      rows={sorted}
      getRowId={(s) => s.id}
      dense
      persistKey="rack-servers"
      emptyTitle="No servers in this rack"
      emptyDescription="DC engineers onboard servers into a rack under Admin → Server onboarding."
      summary={`${rows.length} server${rows.length === 1 ? '' : 's'}`}
    />
  );
}
