import { Link } from 'react-router-dom';

import type { ComplianceServer } from '@/api/types';
import { Drawer } from '@/components/Drawer';
import { Icon } from '@/components/Icon';
import { Age } from '@/components/Reading';

export type ComplianceDiff = ComplianceServer['differences'][number];

const TYPE_LABEL: Record<string, string> = {
  bios: 'BIOS',
  bmc: 'BMC',
  drive: 'Drive',
  nic: 'Network adapter',
  storage_controller: 'Storage controller',
  psu: 'Power supply',
  cpu: 'CPU',
  dimm: 'Memory',
};
export const componentTypeLabel = (t: string) => TYPE_LABEL[t.toLowerCase()] ?? t;

/** Installed vs approved firmware for one server, one row per differing component. */
export function DifferencesList({ differences }: { differences: ComplianceDiff[] }) {
  return (
    <ul className="flex flex-col divide-y divide-text/10" aria-label="Firmware differences">
      {differences.map((d) => (
        <li key={d.component_key} className="py-3 first:pt-0">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-medium text-text">{d.component}</span>
            <span className="text-xs text-text-muted">{componentTypeLabel(d.component_type)}</span>
          </div>
          <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-sm">
            <dt className="text-text-muted">Installed</dt>
            <dd className="flex items-center gap-1.5">
              <Icon name="triangle-alert" size={13} className="text-health-warning" />
              <code className="text-text">{d.installed_version}</code>
              <span className="sr-only">(differs from the baseline)</span>
            </dd>
            <dt className="text-text-muted">Approved</dt>
            <dd>
              <code className="text-text">{d.approved_version}</code>
            </dd>
            <dt className="text-text-muted">Collected</dt>
            <dd>
              <Age time={d.collected_at} staleAfterMs={24 * 3600_000} />
            </dd>
          </dl>
        </li>
      ))}
    </ul>
  );
}

export function DifferencesDrawer({
  server,
  onClose,
}: {
  server: ComplianceServer | null;
  onClose: () => void;
}) {
  return (
    <Drawer
      open={server !== null}
      onClose={onClose}
      title={server ? `${server.server_name}: firmware off baseline` : 'Firmware differences'}
      description={
        server
          ? [server.site_code, server.rack_name, [server.vendor, server.model].filter(Boolean).join(' ')]
              .filter(Boolean)
              .join(' · ')
          : undefined
      }
    >
      {server ? (
        <div className="flex flex-col gap-4">
          <p className="text-sm text-text-muted">
            {server.differences.length === 1
              ? '1 component differs from the approved baseline for this model.'
              : `${server.differences.length} components differ from the approved baseline for this model.`}
          </p>
          <DifferencesList differences={server.differences} />
          <Link
            to={`/servers/${server.server_id}`}
            className="inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline"
          >
            Open the server
            <Icon name="chevron-right" size={14} />
          </Link>
        </div>
      ) : null}
    </Drawer>
  );
}
