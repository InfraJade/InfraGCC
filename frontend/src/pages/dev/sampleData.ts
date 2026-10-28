/** Deterministic sample data for the component gallery. */
import type { AuthUser } from '@/auth/oidc';
import type { RackServer } from '@/components/RackView';
import type { SensorPoint, SensorSeries } from '@/components/SensorChart';
import type { SearchResult, SiteOption } from '@/components/shell/ShellContext';

let seed = 42;
export function rand(): number {
  seed = (seed * 1664525 + 1013904223) % 4294967296;
  return seed / 4294967296;
}

export const sampleUser: AuthUser = {
  sub: 'gallery-user',
  username: 'engineer',
  name: 'Asha Engineer',
  email: 'engineer@gcc.example',
  roles: ['dc_engineer'],
  sites: [],
  groups: ['gcc-dc-engineer'],
  accessToken: 'gallery-token',
  expiresAt: null,
};

export const sampleSites: SiteOption[] = [
  { id: 1, code: 'PNQ1', name: 'Pune DC1', health: 'Warning' },
  { id: 2, code: 'HYD1', name: 'Hyderabad DC2', health: 'OK' },
];

export interface SampleServer {
  id: number;
  name: string;
  vendor: string;
  model: string;
  site: string;
  rack: string;
  health: string;
  inlet: number;
  power: number;
  seen: number;
}

const MODELS = [
  ['Dell', 'PowerEdge R750'],
  ['HPE', 'ProLiant DL380 Gen10'],
  ['Lenovo', 'ThinkSystem SR650 V3'],
] as const;
const HEALTHS = ['OK', 'OK', 'OK', 'OK', 'Warning', 'Critical', 'Unknown'];

export function makeServers(count: number, offset = 0): SampleServer[] {
  return Array.from({ length: count }, (_, k) => {
    const i = k + offset;
    const m = MODELS[i % MODELS.length] ?? MODELS[0];
    return {
      id: i + 1,
      name: `${i % 2 ? 'hyd1' : 'pnq1'}-srv-${String(i + 1).padStart(3, '0')}`,
      vendor: m[0],
      model: m[1],
      site: i % 2 ? 'HYD1' : 'PNQ1',
      rack: `R${String((i % 12) + 1).padStart(2, '0')}`,
      health: HEALTHS[i % HEALTHS.length] ?? 'OK',
      inlet: 20 + ((i * 37) % 120) / 10,
      power: 180 + ((i * 53) % 420),
      seen: Date.now() - ((i * 17) % 240) * 1000,
    };
  });
}

export const rackServers: RackServer[] = [
  {
    id: 1,
    name: 'pnq1-srv-001',
    positionU: 40,
    heightU: 2,
    health: 'OK',
    inletTempC: 22.4,
    inletTime: Date.now() - 20_000,
    model: 'PowerEdge R750',
  },
  {
    id: 2,
    name: 'pnq1-srv-002',
    positionU: 38,
    heightU: 2,
    health: 'OK',
    inletTempC: 23.1,
    inletTime: Date.now() - 35_000,
    model: 'ProLiant DL380 Gen10',
  },
  {
    id: 3,
    name: 'pnq1-srv-003',
    positionU: 36,
    heightU: 2,
    health: 'Warning',
    inletTempC: 28.6,
    inletTime: Date.now() - 50_000,
    model: 'ThinkSystem SR650 V3',
  },
  {
    id: 4,
    name: 'pnq1-srv-004',
    positionU: 33,
    heightU: 1,
    health: 'OK',
    inletTempC: 24.0,
    inletTime: Date.now() - 12_000,
    model: 'PowerEdge R650',
  },
  {
    id: 5,
    name: 'pnq1-srv-005',
    positionU: 32,
    heightU: 1,
    health: 'Critical',
    inletTempC: 36.2,
    inletTime: Date.now() - 8_000,
    model: 'PowerEdge R650',
  },
  {
    id: 6,
    name: 'pnq1-srv-006',
    positionU: 28,
    heightU: 2,
    health: 'OK',
    inletTempC: 23.8,
    inletTime: Date.now() - 41_000,
    model: 'ProLiant DL360 Gen10',
  },
  {
    id: 7,
    name: 'pnq1-srv-007',
    positionU: 24,
    heightU: 4,
    health: 'Unknown',
    inletTempC: null,
    inletTime: null,
    model: 'ThinkSystem SR950',
  },
  {
    id: 8,
    name: 'pnq1-srv-008',
    positionU: 18,
    heightU: 2,
    health: 'OK',
    inletTempC: 21.9,
    inletTime: Date.now() - 300_000,
    model: 'PowerEdge R750',
  },
  {
    id: 9,
    name: 'pnq1-srv-009',
    positionU: 12,
    heightU: 2,
    health: 'OK',
    inletTempC: 22.2,
    inletTime: Date.now() - 25_000,
    model: 'ProLiant DL380 Gen10',
  },
  {
    id: 10,
    name: 'pnq1-srv-010',
    positionU: 6,
    heightU: 1,
    health: 'Warning',
    inletTempC: 27.4,
    inletTime: Date.now() - 15_000,
    model: 'ThinkSystem SR630 V3',
  },
];

/** `n` points, one per minute, ending now. */
export function series(base: number, amplitude: number, n = 90, noise = 0.4): SensorPoint[] {
  const now = Date.now();
  return Array.from({ length: n }, (_, i): SensorPoint => {
    const t = now - (n - 1 - i) * 60_000;
    const v = base + amplitude * Math.sin(i / 9) + (rand() - 0.5) * noise * 2;
    return [t, i === Math.floor(n * 0.4) ? null : Math.round(v * 10) / 10];
  });
}

export function inletSeries(): SensorSeries[] {
  return [
    { id: 'inlet', name: 'Inlet', points: series(24, 2.5) },
    { id: 'exhaust', name: 'Exhaust', points: series(38, 3) },
  ];
}

export function fanSeries(): SensorSeries[] {
  return [1, 2, 3, 4].map((f) => ({
    id: `fan-${f}`,
    name: `Fan ${f}`,
    points: series(6000 + f * 350, 400, 90, 80),
  }));
}

export function appendPoint(s: SensorSeries[], jitter: number): SensorSeries[] {
  return s.map((x) => {
    const last = [...x.points].reverse().find((p) => p[1] !== null);
    const lastV = (last?.[1] as number | undefined) ?? 0;
    const next: SensorPoint = [Date.now(), Math.round((lastV + (rand() - 0.5) * jitter) * 10) / 10];
    return { ...x, points: [...x.points.slice(1), next] };
  });
}

export const sampleSearch = async (q: string, signal: AbortSignal): Promise<SearchResult[]> => {
  await new Promise((r) => setTimeout(r, 300));
  if (signal.aborted) return [];
  const all: SearchResult[] = [
    ...makeServers(24).map((s) => ({
      id: String(s.id),
      kind: 'server',
      label: s.name,
      sublabel: `${s.site} · ${s.rack} · ${s.model}`,
      to: `/servers/${s.id}`,
      health: s.health,
    })),
    { id: '3', kind: 'rack', label: 'PNQ1 · Hall A · R03', to: '/racks/3' },
    { id: '1', kind: 'site', label: 'PNQ1 · Pune DC1', to: '/sites/1', health: 'Warning' },
  ];
  return all.filter((r) => r.label.toLowerCase().includes(q.toLowerCase())).slice(0, 8);
};
