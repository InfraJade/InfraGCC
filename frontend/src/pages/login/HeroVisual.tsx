import { motion, useMotionValue, useSpring, useTransform } from 'framer-motion';
import { useRef, type CSSProperties } from 'react';

import { Icon, type IconName } from '@/components/Icon';
import { cn } from '@/lib/cn';

/**
 * Login hero: a cluster of server racks with blinking status LEDs and a heartbeat line sweeping across them
 * (the pulse from the logo), on a slowly turning globe grid. The scene tilts towards the pointer, and sensor
 * chips with moving sparklines float around it. Decorative only.
 */

interface Rack {
  x: number;
  y: number;
  w: number;
  h: number;
  units: number;
}

const RACKS: Rack[] = [
  { x: 70, y: 112, w: 112, h: 210, units: 7 },
  { x: 196, y: 58, w: 128, h: 264, units: 9 },
  { x: 338, y: 112, w: 112, h: 210, units: 7 },
];

const LED_COLORS = ['#34d399', '#38bdf8', '#60a5fa', '#34d399', '#22d3ee', '#fbbf24'];
/** Stable pseudo-random in [0, 1) for LED timing. */
const rnd = (i: number) => {
  const x = Math.sin(i * 12.9898) * 43758.5453;
  return x - Math.floor(x);
};

function RackShape({ rack, index }: { rack: Rack; index: number }) {
  const { x, y, w, h, units } = rack;
  const depth = 18;
  const unitH = (h - 24) / units;
  return (
    <g>
      {/* top face */}
      <path
        d={`M${x} ${y} L${x + depth} ${y - depth * 0.6} L${x + w + depth} ${y - depth * 0.6} L${x + w} ${y} Z`}
        fill="url(#rack-top)"
      />
      {/* side face */}
      <path
        d={`M${x + w} ${y} L${x + w + depth} ${y - depth * 0.6} L${x + w + depth} ${y + h - depth * 0.6} L${x + w} ${y + h} Z`}
        fill="url(#rack-side)"
      />
      {/* front */}
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={6}
        fill="url(#rack-front)"
        stroke="rgba(96,165,250,0.45)"
        strokeWidth={1.2}
      />
      {Array.from({ length: units }, (_, u) => {
        const uy = y + 12 + u * unitH;
        const seed = index * 40 + u * 5;
        return (
          <g key={u}>
            <rect
              x={x + 10}
              y={uy}
              width={w - 20}
              height={unitH - 6}
              rx={3}
              fill="rgba(15,30,55,0.9)"
              stroke="rgba(59,130,246,0.28)"
            />
            {/* drive bays */}
            {Array.from({ length: 4 }, (_, b) => (
              <rect
                key={b}
                x={x + 18 + b * 9}
                y={uy + (unitH - 6) / 2 - 2}
                width={6}
                height={4}
                rx={1}
                fill="rgba(148,163,184,0.35)"
              />
            ))}
            {Array.from({ length: 3 }, (_, l) => {
              const i = seed + l;
              const color = LED_COLORS[Math.floor(rnd(i) * LED_COLORS.length)]!;
              const style: CSSProperties = {
                animationDelay: `${(rnd(i + 99) * 2.4).toFixed(2)}s`,
                animationDuration: `${(1.4 + rnd(i + 7) * 2.2).toFixed(2)}s`,
              };
              return (
                <circle
                  key={l}
                  cx={x + w - 18 - l * 9}
                  cy={uy + (unitH - 6) / 2}
                  r={2.2}
                  fill={color}
                  className="animate-led"
                  style={{ ...style, filter: `drop-shadow(0 0 3px ${color})` }}
                />
              );
            })}
          </g>
        );
      })}
    </g>
  );
}

const ECG =
  'M20 200 H170 L186 200 L196 176 L206 222 L218 132 L232 252 L244 190 L256 200 H330 L342 200 L350 186 L358 208 L366 200 H500';

export function HeroVisual({ className }: { className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const px = useMotionValue(0);
  const py = useMotionValue(0);
  const sx = useSpring(px, { stiffness: 120, damping: 18 });
  const sy = useSpring(py, { stiffness: 120, damping: 18 });
  const rotateY = useTransform(sx, [-0.5, 0.5], [-12, 12]);
  const rotateX = useTransform(sy, [-0.5, 0.5], [8, -8]);
  const shiftX = useTransform(sx, [-0.5, 0.5], [-14, 14]);
  const shiftY = useTransform(sy, [-0.5, 0.5], [-10, 10]);

  return (
    <div
      ref={ref}
      className={cn('relative select-none', className)}
      style={{ perspective: 1100 }}
      onPointerMove={(e) => {
        const r = ref.current?.getBoundingClientRect();
        if (!r) return;
        px.set((e.clientX - r.left) / r.width - 0.5);
        py.set((e.clientY - r.top) / r.height - 0.5);
      }}
      onPointerLeave={() => {
        px.set(0);
        py.set(0);
      }}
      aria-hidden="true"
    >
      <motion.div style={{ rotateX, rotateY, transformStyle: 'preserve-3d' }} className="relative">
        <svg viewBox="0 0 520 380" className="h-auto w-full overflow-visible">
          <defs>
            <linearGradient id="rack-front" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#13284a" />
              <stop offset="1" stopColor="#0a1426" />
            </linearGradient>
            <linearGradient id="rack-top" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor="#25467a" />
              <stop offset="1" stopColor="#1a3560" />
            </linearGradient>
            <linearGradient id="rack-side" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor="#0d1c36" />
              <stop offset="1" stopColor="#081224" />
            </linearGradient>
            <radialGradient id="floor-glow" cx="0.5" cy="0.5" r="0.5">
              <stop offset="0" stopColor="rgba(56,189,248,0.45)" />
              <stop offset="1" stopColor="rgba(56,189,248,0)" />
            </radialGradient>
            <linearGradient id="ecg-stroke" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor="#38bdf8" stopOpacity="0" />
              <stop offset="0.25" stopColor="#38bdf8" />
              <stop offset="0.6" stopColor="#2bc98c" />
              <stop offset="1" stopColor="#2bc98c" stopOpacity="0" />
            </linearGradient>
            <filter id="glow" x="-20%" y="-50%" width="140%" height="200%">
              <feGaussianBlur stdDeviation="4" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* Globe grid behind the racks */}
          <g transform="translate(400 120)" opacity="0.55">
            <circle r="92" fill="none" stroke="rgba(56,189,248,0.35)" strokeWidth="1.2" />
            <g className="animate-spin-slow" style={{ transformOrigin: '0 0' }}>
              {[-60, -30, 0, 30, 60].map((a) => (
                <ellipse
                  key={a}
                  rx={Math.abs(Math.cos((a * Math.PI) / 180)) * 92 + 4}
                  ry="92"
                  fill="none"
                  stroke="rgba(56,189,248,0.22)"
                  transform={`rotate(${a})`}
                />
              ))}
            </g>
            {[-46, 0, 46].map((yy) => (
              <ellipse
                key={yy}
                cy={yy}
                rx={Math.sqrt(92 * 92 - yy * yy)}
                ry="10"
                fill="none"
                stroke="rgba(56,189,248,0.2)"
              />
            ))}
          </g>

          <ellipse cx="262" cy="336" rx="230" ry="34" fill="url(#floor-glow)" />
          {RACKS.map((r, i) => (
            <RackShape key={i} rack={r} index={i} />
          ))}

          {/* Heartbeat across the racks */}
          <path d={ECG} fill="none" stroke="rgba(56,189,248,0.18)" strokeWidth="3" strokeLinejoin="round" />
          <path
            d={ECG}
            fill="none"
            stroke="url(#ecg-stroke)"
            strokeWidth="3.2"
            strokeLinejoin="round"
            strokeLinecap="round"
            filter="url(#glow)"
            strokeDasharray="320 680"
            className="animate-ecg"
          />
        </svg>
      </motion.div>

      {/* Floating sensor chips (parallax opposite to the tilt) */}
      <motion.div style={{ x: shiftX, y: shiftY }} className="pointer-events-none absolute inset-0">
        <SensorChip
          icon="thermometer"
          label="Inlet temperature"
          unit="°C"
          className="left-[-2%] top-[8%]"
          delay={0}
          color="#38bdf8"
        />
        <SensorChip
          icon="fan"
          label="Fan speed"
          unit="RPM"
          className="right-[-4%] top-[44%]"
          delay={1.2}
          color="#2bc98c"
        />
        <SensorChip
          icon="zap"
          label="Power draw"
          unit="W"
          className="bottom-[6%] left-[4%]"
          delay={0.6}
          color="#60a5fa"
        />
        <StatusChip className="right-[6%] top-[2%]" />
      </motion.div>
    </div>
  );
}

/** One wave period (96 units wide) starting at x = `dx`. */
const period = (dx: number) =>
  `C${dx + 8} 2, ${dx + 16} 18, ${dx + 24} 10 S${dx + 40} 2, ${dx + 48} 12 S${dx + 64} 18, ${dx + 72} 8 S${dx + 88} 4, ${dx + 96} 10`;
/** Two identical periods side by side; the SVG scrolls by half its width, so the loop is seamless. */
const WAVE = `M0 10 ${period(0)} ${period(96)}`;

/** A glass chip with a sensor name and a continuously scrolling sparkline. */
function SensorChip({
  icon,
  label,
  unit,
  className,
  delay,
  color,
}: {
  icon: IconName;
  label: string;
  unit: string;
  className?: string;
  delay: number;
  color: string;
}) {
  return (
    <motion.div
      className={cn(
        'glass-strong absolute flex items-center gap-2.5 rounded-xl px-3 py-2 shadow-lg',
        className,
      )}
      animate={{ y: [0, -8, 0] }}
      transition={{ duration: 5, repeat: Infinity, ease: 'easeInOut', delay }}
    >
      <span
        className="flex h-7 w-7 items-center justify-center rounded-lg"
        style={{ background: `${color}22`, color }}
      >
        <Icon name={icon} size={15} />
      </span>
      <span className="flex flex-col">
        <span className="text-[11px] font-medium text-text">{label}</span>
        <span className="text-[10px] text-text-subtle">live · {unit}</span>
      </span>
      <span className="relative h-5 w-16 overflow-hidden">
        <svg
          viewBox="0 0 192 20"
          className="absolute left-0 top-0 h-5 w-32 animate-wave"
          preserveAspectRatio="none"
        >
          <path d={WAVE} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" />
        </svg>
      </span>
    </motion.div>
  );
}

function StatusChip({ className }: { className?: string }) {
  return (
    <motion.div
      className={cn(
        'glass-strong absolute flex items-center gap-2 rounded-full px-3 py-1.5 shadow-lg',
        className,
      )}
      animate={{ y: [0, -6, 0] }}
      transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut', delay: 2 }}
    >
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-health-ok" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-health-ok" />
      </span>
      <span className="text-[11px] font-medium text-text">Redfish · Dell · HPE · Lenovo</span>
    </motion.div>
  );
}
