import { Link } from 'react-router-dom';

import type { ServerDetail } from '@/api/types';
import { OnlineBadge } from '@/components/Badges';
import { GlassCard } from '@/components/GlassCard';
import { KeyValueList } from '@/components/KeyValue';
import { Age } from '@/components/Reading';
import { rackRange } from '@/components/RackView';

const linkClass = 'text-accent hover:underline';

/** Identity, location and management facts of one server. */
export function FactsCard({ server }: { server: ServerDetail }) {
  const s = server;
  return (
    <GlassCard as="section" title="Facts" aria-label="Server facts">
      <KeyValueList
        items={[
          { label: 'Vendor', value: s.vendor },
          { label: 'Model', value: s.model },
          { label: 'Serial', value: s.serial ? <span className="font-mono">{s.serial}</span> : null },
          { label: 'Asset tag', value: s.asset_tag },
          { label: 'BMC host', value: <span className="font-mono">{s.bmc_host}</span> },
          { label: 'BMC model', value: s.bmc_model },
          { label: 'BMC MAC', value: s.bmc_mac ? <span className="font-mono">{s.bmc_mac}</span> : null },
          { label: 'Hostname', value: s.hostname ? <span className="font-mono">{s.hostname}</span> : null },
          {
            label: 'Host IPs',
            value: s.host_ips.length ? (
              <span className="flex flex-col font-mono">
                {s.host_ips.map((ip) => (
                  <span key={ip}>{ip}</span>
                ))}
              </span>
            ) : null,
          },
          {
            label: 'Site',
            value: (
              <Link to={`/sites/${s.site.id}`} className={linkClass}>
                {s.site.code} {s.site.name}
              </Link>
            ),
          },
          { label: 'Room', value: s.room?.name },
          {
            label: 'Rack',
            value: s.rack ? (
              <Link to={`/racks/${s.rack.id}`} className={linkClass}>
                {s.rack.name}
              </Link>
            ) : null,
          },
          {
            label: 'Position',
            value:
              s.position_u !== null
                ? rackRange({ positionU: s.position_u, heightU: s.height_u })
                : 'Unplaced',
          },
          {
            label: 'Collector',
            value: s.collector ? (
              <span className="flex flex-wrap items-center gap-2">
                {s.collector.name}
                <OnlineBadge online={s.collector.online} />
              </span>
            ) : (
              s.collector_name
            ),
          },
          { label: 'Discovered', value: s.discovered_at ? <Age time={s.discovered_at} /> : 'Not yet' },
          {
            label: 'Notes',
            value: s.notes ? <span className="whitespace-pre-wrap">{s.notes}</span> : null,
          },
        ]}
      />
    </GlassCard>
  );
}
