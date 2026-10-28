import { useMemo } from 'react';
import { Link } from 'react-router-dom';

import { useCursorList } from '@/api/hooks';
import type { ComponentListItem, ComponentType } from '@/api/types';
import { Pill } from '@/components/Badges';
import { Button } from '@/components/Button';
import { DataTable, type Column } from '@/components/DataTable';
import { Checkbox, FormField, Select } from '@/components/FormField';
import { Age } from '@/components/Reading';
import { useSiteFilter } from '@/components/shell/ShellContext';
import { formatValue } from '@/lib/format';
import { useUrlState } from '@/lib/useUrlState';

import { listSummary, resolveSite, SearchField } from '../alerts/filterControls';

import { ExportCsvButton } from './ExportCsvButton';

export const COMPONENT_TYPES: { value: ComponentType; label: string }[] = [
  { value: 'cpu', label: 'CPU' },
  { value: 'dimm', label: 'Memory (DIMM)' },
  { value: 'drive', label: 'Drive' },
  { value: 'psu', label: 'Power supply' },
  { value: 'fan', label: 'Fan' },
  { value: 'nic', label: 'Network adapter' },
  { value: 'storage_controller', label: 'Storage controller' },
  { value: 'volume', label: 'Volume' },
];
const TYPE_LABEL: Record<string, string> = Object.fromEntries(COMPONENT_TYPES.map((t) => [t.value, t.label]));

/** Parts filters use their own URL keys so switching tabs keeps each tab's filters (`q` is shared). */
const DEFAULTS = { q: '', type: '', manufacturer: '', part_model: '', removed: '' };

const dash = <span className="text-text-subtle">—</span>;

const columns: Column<ComponentListItem>[] = [
  { id: 'type', header: 'Type', hideable: false, cell: (c) => TYPE_LABEL[c.type] ?? c.type },
  { id: 'name', header: 'Name', hideable: false, cell: (c) => <span className="font-medium">{c.name}</span> },
  {
    id: 'server',
    header: 'Server',
    cell: (c) => (
      <Link to={`/servers/${c.server_id}`} className="font-medium text-accent hover:underline">
        {c.server_name}
      </Link>
    ),
  },
  { id: 'site', header: 'Site', cell: (c) => c.site_code },
  { id: 'model', header: 'Model', cell: (c) => c.model ?? dash },
  { id: 'manufacturer', header: 'Manufacturer', cell: (c) => c.manufacturer ?? dash },
  { id: 'serial', header: 'Serial', cell: (c) => (c.serial ? <code>{c.serial}</code> : dash) },
  {
    id: 'capacity',
    header: 'Capacity',
    align: 'right',
    cell: (c) =>
      c.capacity !== null ? (
        <span className="tabular">{formatValue(c.capacity, c.capacity_unit ?? undefined)}</span>
      ) : (
        dash
      ),
  },
  { id: 'firmware', header: 'Firmware', cell: (c) => c.firmware_version ?? dash },
  { id: 'location', header: 'Location', defaultHidden: true, cell: (c) => c.location ?? dash },
  {
    id: 'first_seen',
    header: 'First seen',
    defaultHidden: true,
    cell: (c) => <Age time={c.first_seen_at} staleAfterMs={Infinity} />,
  },
  { id: 'last_seen', header: 'Last seen', cell: (c) => <Age time={c.last_seen_at} /> },
  {
    id: 'removed',
    header: 'Removed',
    cell: (c) =>
      c.removed_at ? (
        <span className="inline-flex flex-col gap-0.5">
          <Pill icon="minus" className="bg-text/5 text-text-muted ring-1 ring-inset ring-text/15">
            Removed
          </Pill>
          <Age time={c.removed_at} staleAfterMs={Infinity} className="text-xs" />
        </span>
      ) : (
        <span className="text-text-subtle">Installed</span>
      ),
  },
];

export function PartsTab() {
  const [f, setF] = useUrlState(DEFAULTS);
  const { siteIds } = useSiteFilter();
  const site = resolveSite('', siteIds);

  const query = {
    q: f.q || undefined,
    type: f.type || undefined,
    manufacturer: f.manufacturer || undefined,
    model: f.part_model || undefined,
    include_removed: f.removed === '1' ? true : undefined,
    site_id: site.siteId,
  };
  const list = useCursorList<ComponentListItem>('/api/v1/components', query);
  const clientSites = site.clientSiteIds;
  const rows = useMemo(
    () => (clientSites ? list.items.filter((c) => clientSites.includes(c.site_id)) : list.items),
    [list.items, clientSites],
  );
  const filtered = Boolean(f.q || f.type || f.manufacturer || f.part_model || f.removed);

  return (
    <div className="flex flex-col gap-4">
      <div className="grid items-end gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <SearchField
          label="Search parts"
          value={f.q}
          onCommit={(q) => setF({ q })}
          placeholder="Name, serial, model, manufacturer"
        />
        <FormField label="Type">
          <Select
            value={f.type}
            onChange={(e) => setF({ type: e.target.value })}
            options={[{ value: '', label: 'All types' }, ...COMPONENT_TYPES]}
          />
        </FormField>
        <SearchField
          label="Manufacturer"
          search={false}
          value={f.manufacturer}
          onCommit={(manufacturer) => setF({ manufacturer })}
          placeholder="e.g. Samsung"
          hint="Exact name"
        />
        <SearchField
          label="Model"
          search={false}
          value={f.part_model}
          onCommit={(part_model) => setF({ part_model })}
          hint="Exact name"
        />
        <Checkbox
          className="h-9"
          label="Include removed parts"
          checked={f.removed === '1'}
          onChange={(e) => setF({ removed: e.target.checked ? '1' : '' })}
        />
      </div>

      <DataTable<ComponentListItem>
        {...list.tableProps}
        rows={rows}
        columns={columns}
        getRowId={(c) => c.id}
        caption="Parts"
        persistKey="inventory.parts"
        summary={listSummary(rows.length, list.hasNextPage, 'parts')}
        toolbar={
          <>
            <ExportCsvButton path="/api/v1/components/export.csv" query={query} filename="parts.csv" />
            {filtered ? (
              <Button
                size="sm"
                variant="ghost"
                icon="x"
                onClick={() => setF({ q: '', type: '', manufacturer: '', part_model: '', removed: '' })}
              >
                Clear filters
              </Button>
            ) : null}
          </>
        }
        emptyTitle={filtered ? 'No parts match' : 'No parts collected yet'}
        emptyDescription={
          filtered
            ? 'Check the spelling, or clear a filter. Manufacturer and model need the exact name.'
            : 'Parts appear after a collector has read a server’s inventory.'
        }
      />
    </div>
  );
}
