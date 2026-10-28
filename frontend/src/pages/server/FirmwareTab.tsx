import type { FirmwareItem } from '@/api/types';
import { Pill } from '@/components/Badges';
import { DataTable, type Column } from '@/components/DataTable';
import { Age } from '@/components/Reading';
import { healthClasses } from '@/lib/health';

/** Compliance as word + color + icon: Compliant / Off baseline / No baseline. */
export function ComplianceBadge({ compliant }: { compliant: boolean | null }) {
  if (compliant === true)
    return (
      <Pill icon="circle-check" className={healthClasses.OK.soft}>
        Compliant
      </Pill>
    );
  if (compliant === false)
    return (
      <Pill icon="triangle-alert" className={healthClasses.Warning.soft}>
        Off baseline
      </Pill>
    );
  return (
    <Pill icon="circle-help" className={healthClasses.Unknown.soft}>
      No baseline
    </Pill>
  );
}

const mono = (v: string | null) =>
  v ? <span className="font-mono text-xs">{v}</span> : <span className="text-text-subtle">—</span>;

const columns: Column<FirmwareItem>[] = [
  {
    id: 'component',
    header: 'Component',
    hideable: false,
    cell: (f) => (
      <span className="flex flex-col">
        <span className="font-medium text-text">{f.component}</span>
        <span className="text-xs text-text-subtle">{f.component_type}</span>
      </span>
    ),
  },
  { id: 'installed', header: 'Installed', cell: (f) => mono(f.version) },
  { id: 'approved', header: 'Approved', cell: (f) => mono(f.approved_version) },
  { id: 'compliance', header: 'Compliance', cell: (f) => <ComplianceBadge compliant={f.compliant} /> },
  {
    id: 'collected',
    header: 'Collected',
    cell: (f) => <Age time={f.collected_at} staleAfterMs={Infinity} />,
  },
];

export function FirmwareTab({ firmware }: { firmware: readonly FirmwareItem[] }) {
  const off = firmware.filter((f) => f.compliant === false).length;
  const ok = firmware.filter((f) => f.compliant === true).length;
  const rows = [...firmware].sort(
    (a, b) =>
      rank(a.compliant) - rank(b.compliant) ||
      a.component.localeCompare(b.component, 'en', { numeric: true }),
  );
  return (
    <DataTable
      caption="Firmware versions"
      columns={columns}
      rows={rows}
      getRowId={(f) => f.component_key}
      dense
      persistKey="server-firmware"
      emptyTitle="No firmware versions collected yet"
      emptyDescription="The collector reads firmware versions from the BMC inventory."
      summary={
        firmware.length
          ? `${ok} compliant · ${off} off baseline · ${firmware.length - ok - off} without baseline`
          : undefined
      }
    />
  );
}

/** Off baseline first, then no baseline, then compliant. */
function rank(c: boolean | null): number {
  return c === false ? 0 : c === null ? 1 : 2;
}
