import { useMemo } from 'react';

import type { ServerComponent } from '@/api/types';
import { DataTable, type Column } from '@/components/DataTable';
import { EmptyState } from '@/components/EmptyState';
import { GlassCard } from '@/components/GlassCard';
import { formatValue } from '@/lib/format';

import { groupBy } from './common';

const TYPES: { type: string; label: string }[] = [
  { type: 'cpu', label: 'Processors' },
  { type: 'dimm', label: 'Memory modules' },
  { type: 'drive', label: 'Drives' },
  { type: 'psu', label: 'Power supplies' },
  { type: 'fan', label: 'Fans' },
  { type: 'nic', label: 'Network adapters' },
  { type: 'storage_controller', label: 'Storage controllers' },
  { type: 'volume', label: 'Volumes' },
];

const dash = <span className="text-text-subtle">—</span>;
const text = (v: string | null) => (v ? v : dash);

const columns: Column<ServerComponent>[] = [
  {
    id: 'name',
    header: 'Name',
    hideable: false,
    cell: (c) => <span className="font-medium text-text">{c.name}</span>,
  },
  { id: 'model', header: 'Model', cell: (c) => text(c.model) },
  { id: 'manufacturer', header: 'Manufacturer', cell: (c) => text(c.manufacturer) },
  {
    id: 'serial',
    header: 'Serial',
    cell: (c) => (c.serial ? <span className="font-mono text-xs">{c.serial}</span> : dash),
  },
  {
    id: 'capacity',
    header: 'Capacity',
    align: 'right',
    cell: (c) =>
      c.capacity === null ? (
        dash
      ) : (
        <span className="tabular">{formatValue(c.capacity, c.capacity_unit ?? undefined)}</span>
      ),
  },
  {
    id: 'firmware',
    header: 'Firmware',
    cell: (c) =>
      c.firmware_version ? <span className="font-mono text-xs">{c.firmware_version}</span> : dash,
  },
  { id: 'location', header: 'Location', cell: (c) => text(c.location) },
];

/** Installed hardware grouped by type; removed parts are hidden. */
export function InventoryTab({ components }: { components: readonly ServerComponent[] }) {
  const groups = useMemo(
    () =>
      groupBy(
        components.filter((c) => !c.removed_at),
        (c) => c.type,
      ),
    [components],
  );
  const known = new Set(TYPES.map((t) => t.type));
  const sections = [
    ...TYPES.filter((t) => groups.has(t.type)),
    ...[...groups.keys()].filter((t) => !known.has(t)).map((t) => ({ type: t, label: t })),
  ];

  if (sections.length === 0) {
    return (
      <GlassCard>
        <EmptyState
          icon="chip"
          title="No inventory collected yet"
          description="The collector reads the hardware inventory from the BMC after its first full poll."
        />
      </GlassCard>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {sections.map((t) => {
        const rows = [...(groups.get(t.type) ?? [])].sort((a, b) =>
          a.name.localeCompare(b.name, 'en', { numeric: true }),
        );
        return (
          <section key={t.type} aria-labelledby={`inv-${t.type}`}>
            <h2
              id={`inv-${t.type}`}
              className="mb-2 flex items-baseline gap-2 text-sm font-semibold uppercase tracking-wider text-text-muted"
            >
              {t.label}
              <span className="tabular text-xs font-normal normal-case text-text-subtle">{rows.length}</span>
            </h2>
            <DataTable
              caption={t.label}
              columns={columns}
              rows={rows}
              getRowId={(c) => c.id}
              dense
              persistKey="server-inventory"
            />
          </section>
        );
      })}
    </div>
  );
}
