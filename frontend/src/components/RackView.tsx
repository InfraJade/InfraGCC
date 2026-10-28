import { useId, useMemo, useState } from 'react';

import { cn } from '@/lib/cn';
import { formatAge, formatValue, type TimeInput } from '@/lib/format';
import { healthClasses, normalizeHealth } from '@/lib/health';
import { health as healthTokens } from '@/theme/tokens';

import { HealthBadge } from './HealthBadge';
import { Icon } from './Icon';
import { Reading } from './Reading';

export interface RackServer {
  id: number | string;
  name: string;
  /** Lowest U the server occupies (1 = bottom of the rack). */
  positionU: number;
  heightU: number;
  health: string | null | undefined;
  inletTempC?: number | null;
  inletTime?: TimeInput | null;
  model?: string;
  status?: string;
}

export interface RackViewProps {
  name: string;
  heightU: number;
  servers: readonly RackServer[];
  onServerClick?: (server: RackServer) => void;
  selectedId?: number | string | null;
  /** Pixel height of one U in the SVG coordinate system (the drawing scales to its container width). */
  uHeight?: number;
  /** Max rendered width (CSS), default 380px. */
  maxWidth?: number | string;
  className?: string;
}

const W = 360;
const GUTTER = 30;
const PAD_Y = 10;

export function rackRange(s: Pick<RackServer, 'positionU' | 'heightU'>): string {
  const top = s.positionU + Math.max(1, s.heightU) - 1;
  return top === s.positionU ? `U${s.positionU}` : `U${s.positionU}–U${top}`;
}

function serverLabel(s: RackServer, now: number): string {
  const h = healthTokens[normalizeHealth(s.health)].label;
  const inlet =
    s.inletTempC === null || s.inletTempC === undefined
      ? 'no inlet reading'
      : `inlet ${formatValue(s.inletTempC, '°C')}${s.inletTime ? `, ${formatAge(s.inletTime, now)}` : ''}`;
  return `${s.name}, ${rackRange(s)}, health ${h}, ${inlet}`;
}

/** SVG rack elevation: U numbers, servers at their position and height, health word+color, inlet temp. */
export function RackView({
  name,
  heightU,
  servers,
  onServerClick,
  selectedId,
  uHeight = 22,
  maxWidth = 380,
  className,
}: RackViewProps) {
  const titleId = useId();
  const [hover, setHover] = useState<RackServer | null>(null);
  const totalH = heightU * uHeight + PAD_Y * 2;
  const inner = W - GUTTER * 2;

  const { placed, free } = useMemo(() => {
    const occupied = new Set<number>();
    const ok: RackServer[] = [];
    for (const s of servers) {
      const h = Math.max(1, s.heightU);
      if (s.positionU < 1 || s.positionU + h - 1 > heightU) continue; // outside this rack's height
      ok.push(s);
      for (let u = s.positionU; u < s.positionU + h; u++) occupied.add(u);
    }
    const emptyUs: number[] = [];
    for (let u = 1; u <= heightU; u++) if (!occupied.has(u)) emptyUs.push(u);
    return { placed: ok, free: emptyUs };
  }, [servers, heightU]);

  const yOf = (topU: number) => PAD_Y + (heightU - topU) * uHeight;
  const now = Date.now();
  // Below the server in the upper half of the rack, above it in the lower half.
  const tooltipPosition = (s: RackServer) => {
    const bottom = yOf(s.positionU) + uHeight;
    const top = yOf(s.positionU + Math.max(1, s.heightU) - 1);
    return bottom / totalH < 0.6
      ? { top: `calc(${(bottom / totalH) * 100}% + 6px)` }
      : { bottom: `calc(${(1 - top / totalH) * 100}% + 6px)` };
  };

  return (
    <div className={cn('relative w-full', className)} style={{ maxWidth }}>
      <svg
        viewBox={`0 0 ${W} ${totalH}`}
        className="h-auto w-full select-none"
        role="group"
        aria-labelledby={titleId}
      >
        <title id={titleId}>
          {`Rack ${name}, ${heightU} U, ${placed.length} server${placed.length === 1 ? '' : 's'}, ${free.length} U free`}
        </title>
        {/* frame + rails */}
        <rect
          x={GUTTER - 6}
          y={2}
          width={inner + 12}
          height={totalH - 4}
          rx={10}
          className="fill-surface-sunken/70 stroke-text/15"
          strokeWidth={1}
        />
        {Array.from({ length: heightU }, (_, i) => {
          const u = heightU - i;
          const y = yOf(u);
          return (
            <g key={u} aria-hidden="true">
              <text
                x={GUTTER - 10}
                y={y + uHeight / 2}
                textAnchor="end"
                dominantBaseline="central"
                className="fill-text-subtle font-mono"
                fontSize={9}
              >
                {u}
              </text>
              <text
                x={W - GUTTER + 10}
                y={y + uHeight / 2}
                textAnchor="start"
                dominantBaseline="central"
                className="fill-text-subtle font-mono"
                fontSize={9}
              >
                {u}
              </text>
            </g>
          );
        })}

        {free.map((u) => (
          <rect
            key={`free-${u}`}
            data-empty-u={u}
            aria-hidden="true"
            x={GUTTER + 2}
            y={yOf(u) + 1.5}
            width={inner - 4}
            height={uHeight - 3}
            rx={3}
            className="fill-transparent stroke-text/10"
            strokeDasharray="3 3"
          />
        ))}

        {placed.map((s) => {
          const h = Math.max(1, s.heightU);
          const state = normalizeHealth(s.health);
          const tok = healthTokens[state];
          const cls = healthClasses[state];
          const y = yOf(s.positionU + h - 1) + 1;
          const hh = h * uHeight - 2;
          const cy = y + Math.min(hh, uHeight) / 2;
          const selected = selectedId !== undefined && selectedId !== null && selectedId === s.id;
          const activate = () => onServerClick?.(s);
          return (
            <g
              key={s.id}
              data-server-id={s.id}
              data-health={state}
              role={onServerClick ? 'button' : 'img'}
              tabIndex={0}
              aria-label={serverLabel(s, now)}
              aria-pressed={onServerClick && selected ? true : undefined}
              className={cn('group outline-none', onServerClick && 'cursor-pointer')}
              onClick={activate}
              onKeyDown={(e) => {
                if (onServerClick && (e.key === 'Enter' || e.key === ' ')) {
                  e.preventDefault();
                  activate();
                }
              }}
              onMouseEnter={() => setHover(s)}
              onMouseLeave={() => setHover((cur) => (cur?.id === s.id ? null : cur))}
              onFocus={() => setHover(s)}
              onBlur={() => setHover((cur) => (cur?.id === s.id ? null : cur))}
            >
              <rect
                x={GUTTER + 1}
                y={y}
                width={inner - 2}
                height={hh}
                rx={4}
                className={cn(
                  cls.fill,
                  cls.stroke,
                  'transition-[stroke-width] duration-fast group-hover:[stroke-width:2] group-focus-visible:[stroke-width:2.5]',
                )}
                strokeWidth={selected ? 2.5 : 1.2}
              />
              {/* health stripe so the state reads even at a glance */}
              <rect
                x={GUTTER + 1}
                y={y}
                width={4}
                height={hh}
                rx={2}
                className={cn(cls.text)}
                fill="currentColor"
              />
              {selected ? (
                <rect
                  x={GUTTER - 2}
                  y={y - 3}
                  width={inner + 4}
                  height={hh + 6}
                  rx={6}
                  className="fill-none stroke-accent"
                  strokeWidth={1.5}
                />
              ) : null}
              <text
                x={GUTTER + 12}
                y={cy}
                dominantBaseline="central"
                className="fill-text font-medium"
                fontSize={11}
              >
                {s.name.length > 18 ? `${s.name.slice(0, 17)}…` : s.name}
              </text>
              <g className={cls.text}>
                <Icon name={tok.icon} x={GUTTER + 142} y={cy - 6} size={12} />
                <text
                  x={GUTTER + 158}
                  y={cy}
                  dominantBaseline="central"
                  fill="currentColor"
                  fontSize={10.5}
                  fontWeight={600}
                >
                  {tok.label}
                </text>
              </g>
              <text
                x={W - GUTTER - 8}
                y={cy}
                textAnchor="end"
                dominantBaseline="central"
                className="fill-text-muted font-mono"
                fontSize={10.5}
              >
                {s.inletTempC === null || s.inletTempC === undefined ? '—' : formatValue(s.inletTempC, '°C')}
              </text>
            </g>
          );
        })}
      </svg>

      {hover ? (
        <div
          role="tooltip"
          className="glass-strong pointer-events-none absolute left-1/2 z-tooltip w-64 -translate-x-1/2 rounded-lg p-3 text-xs"
          style={tooltipPosition(hover)}
        >
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="truncate font-semibold text-text">{hover.name}</span>
            <HealthBadge health={hover.health} size="sm" />
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-text-muted">
            <dt>Position</dt>
            <dd className="text-text">{rackRange(hover)}</dd>
            {hover.model ? (
              <>
                <dt>Model</dt>
                <dd className="text-text">{hover.model}</dd>
              </>
            ) : null}
            <dt>Inlet</dt>
            <dd>
              <Reading value={hover.inletTempC ?? null} unit="°C" time={hover.inletTime ?? null} />
            </dd>
          </dl>
          {onServerClick ? <p className="mt-1.5 text-text-subtle">Click or press Enter to open</p> : null}
        </div>
      ) : null}
    </div>
  );
}
