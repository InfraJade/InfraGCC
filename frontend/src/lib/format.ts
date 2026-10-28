/**
 * Number, unit and age formatting. DESIGN rule: every number shows its unit and how old it is,
 * e.g. "41 °C, 30 s ago".
 */

export type TimeInput = string | number | Date;

export function toMillis(t: TimeInput): number {
  if (t instanceof Date) return t.getTime();
  if (typeof t === 'number') return t;
  return Date.parse(t);
}

/** "now", "12 s ago", "5 min ago", "3 h ago", "2 d ago". Future times (clock skew) read as "now". */
export function formatAge(time: TimeInput, now: number = Date.now()): string {
  const ms = toMillis(time);
  if (Number.isNaN(ms)) return 'unknown age';
  const s = Math.floor((now - ms) / 1000);
  if (s < 1) return 'now';
  if (s < 60) return `${s} s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.floor(h / 24)} d ago`;
}

/** How often an age label needs to re-render to stay accurate. */
export function ageTickMs(time: TimeInput, now: number = Date.now()): number {
  const s = (now - toMillis(time)) / 1000;
  if (!Number.isFinite(s) || s < 120) return 1000;
  if (s < 3600) return 15_000;
  return 60_000;
}

/** Default decimals by unit: RPM/W 0; °C, % and V 1 (0 for whole numbers and values ≥ 100). */
export function defaultPrecision(unit: string | undefined, value: number): number {
  switch (unit) {
    case 'RPM':
    case 'W':
    case 'rpm':
      return 0;
    case '°C':
    case 'V':
    case '%':
      return Math.abs(value) >= 100 || Number.isInteger(value) ? 0 : 1;
    default:
      return Number.isInteger(value) ? 0 : 1;
  }
}

const nfCache = new Map<number, Intl.NumberFormat>();

export function formatNumber(value: number, precision: number): string {
  let nf = nfCache.get(precision);
  if (!nf) {
    nf = new Intl.NumberFormat('en-US', {
      minimumFractionDigits: precision,
      maximumFractionDigits: precision,
    });
    nfCache.set(precision, nf);
  }
  return nf.format(value);
}

/** "41.2 °C", "2,100 RPM", "87 %". Null/NaN → "—". */
export function formatValue(value: number | null | undefined, unit?: string, precision?: number): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const p = precision ?? defaultPrecision(unit, value);
  const n = formatNumber(value, p);
  return unit ? `${n} ${unit}` : n;
}

/** Absolute timestamp for tooltips/titles. */
export function formatTimestamp(time: TimeInput): string {
  const ms = toMillis(time);
  if (Number.isNaN(ms)) return 'unknown time';
  return new Date(ms).toLocaleString('en-GB', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}
