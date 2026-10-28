import { Link } from 'react-router-dom';

import type { RackSummary, RoomWithRacks } from '@/api/types';
import { EmptyState } from '@/components/EmptyState';
import { GlassCard } from '@/components/GlassCard';
import { HealthBadge } from '@/components/HealthBadge';
import { Icon } from '@/components/Icon';
import { Reading } from '@/components/Reading';
import { cn } from '@/lib/cn';
import { healthClasses, normalizeHealth } from '@/lib/health';

/** One room: its racks as a grid of tiles colored by worst health (word + color + icon). */
export function RoomCard({ room, readingTime }: { room: RoomWithRacks; readingTime: string | null }) {
  const racks = [...room.racks].sort((a, b) =>
    `${a.row ?? ''} ${a.name}`.localeCompare(`${b.row ?? ''} ${b.name}`, 'en', { numeric: true }),
  );
  return (
    <GlassCard
      as="section"
      aria-label={`Room ${room.name}`}
      title={
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span>{room.name}</span>
          {room.floor ? (
            <span className="text-xs font-normal text-text-muted">Floor {room.floor}</span>
          ) : null}
          <span className="text-xs font-normal text-text-subtle">
            {racks.length} rack{racks.length === 1 ? '' : 's'}
          </span>
        </span>
      }
      actions={<HealthBadge health={room.worst_health} size="sm" context={`Room ${room.name}`} />}
    >
      {racks.length === 0 ? (
        <EmptyState
          icon="rack"
          title="No racks in this room yet"
          description="DC engineers add racks under Admin → Racks."
        />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {racks.map((r) => (
            <li key={r.id}>
              <RackTile rack={r} readingTime={readingTime} />
            </li>
          ))}
        </ul>
      )}
    </GlassCard>
  );
}

export function RackTile({ rack, readingTime }: { rack: RackSummary; readingTime: string | null }) {
  const state = normalizeHealth(rack.worst_health);
  const c = healthClasses[state];
  const servers = rack.server_count ?? 0;
  const alerts = rack.open_alerts ?? 0;
  return (
    <Link
      to={`/racks/${rack.id}`}
      data-health={state}
      className="glass-subtle group relative flex h-full flex-col gap-2 overflow-hidden rounded-lg p-3 pl-4 transition duration-fast ease-standard hover:-translate-y-0.5 hover:bg-text/5 hover:shadow-md"
    >
      <span aria-hidden="true" className={cn('absolute inset-y-0 left-0 w-1.5', c.dot)} />
      <span className="flex items-start justify-between gap-2">
        <span className="min-w-0">
          <span className="flex items-center gap-1.5 truncate font-semibold text-text group-hover:underline">
            <Icon name="rack" size={14} className="shrink-0 text-text-subtle" />
            {rack.name}
          </span>
          {rack.row ? <span className="text-xs text-text-muted">Row {rack.row}</span> : null}
        </span>
        <HealthBadge health={rack.worst_health} size="sm" />
      </span>
      <span className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-text-muted">
        <span>
          <span className="tabular font-medium text-text">{servers}</span> server{servers === 1 ? '' : 's'}
        </span>
        <span>
          <span className="tabular font-medium text-text">
            {rack.used_u ?? 0}/{rack.height_u}
          </span>{' '}
          U used
        </span>
        <span className="col-span-2 flex flex-wrap items-baseline gap-x-1">
          <Icon name="zap" size={12} className="self-center text-text-subtle" />
          <Reading value={rack.power_w ?? null} unit="W" time={readingTime} />
        </span>
        <span className="col-span-2 flex flex-wrap items-baseline gap-x-1">
          <Icon name="thermometer" size={12} className="self-center text-text-subtle" />
          <span>Inlet max</span>
          <Reading value={rack.inlet_max_c ?? null} unit="°C" time={readingTime} />
        </span>
        <span
          className={cn(
            'col-span-2 flex items-center gap-1',
            alerts > 0 ? 'font-medium text-health-warning' : 'text-text-subtle',
          )}
        >
          <Icon name="bell" size={12} />
          {alerts === 0 ? 'No open alerts' : `${alerts} open alert${alerts === 1 ? '' : 's'}`}
        </span>
      </span>
    </Link>
  );
}
