/**
 * The demo data set: three sites, five rooms, fifteen racks, about sixty Dell / HPE / Lenovo servers with
 * parts, firmware, event logs and a set of realistic faults (failed PSU, slow fan, hot aisle, worn drive,
 * unreachable BMC, ...), plus the alerts those faults raise, alert history, rules, thresholds, routes,
 * maintenance windows, baselines, users and an audit trail.
 *
 * Everything is generated from a fixed seed, so the data is the same on every load; timestamps are relative to
 * the moment the data set is built. Sensor values are not stored: `sensorValue()` computes them for any time,
 * so the latest readings, the live feed and the history charts always agree.
 */
import type {
  AlertActivity,
  AlertDetail,
  AlertRoute,
  AlertRule,
  AuditEntry,
  Baseline,
  Health,
  Metric,
  ServerComponent,
  ServerEvent,
  Threshold,
  User,
} from '@/api/types';

// ---------------------------------------------------------------------------------------------- randomness

/** Deterministic PRNG (mulberry32). */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Stable hash of a few numbers → [0, 1). */
export function hash01(...parts: number[]): number {
  let h = 2166136261;
  for (const p of parts) {
    h ^= p | 0;
    h = Math.imul(h, 16777619);
    h ^= h >>> 13;
  }
  h = Math.imul(h ^ (h >>> 16), 2246822507);
  h = Math.imul(h ^ (h >>> 13), 3266489909);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

export function strHash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(h, 31) + s.charCodeAt(i)) | 0;
  return h;
}

const iso = (ms: number) => new Date(Math.round(ms / 1000) * 1000).toISOString().replace('.000Z', 'Z');
const MIN = 60_000;
const HOUR = 3_600_000;
const DAY = 86_400_000;

// ---------------------------------------------------------------------------------------------- types

export interface DemoSite {
  id: number;
  code: string;
  name: string;
  city: string;
  country: string;
  timezone: string;
  /** Offset of the daily temperature/load cycle, fraction of a day. */
  phase: number;
  created_at: string;
  updated_at: string;
}

export interface DemoRoom {
  id: number;
  site_id: number;
  name: string;
  floor: string | null;
}

export interface DemoRack {
  id: number;
  room_id: number;
  name: string;
  row: string | null;
  height_u: number;
  power_capacity_w: number | null;
  /** Inlet offset in °C (hot aisle). */
  inletOffset: number;
}

export interface DemoCollector {
  id: number;
  site_id: number;
  name: string;
  version: string | null;
  hostname: string | null;
  enabled: boolean;
  /** Seconds since the last heartbeat; null = never. Offline when > 120. */
  heartbeatAgeS: number | null;
  cert_fingerprint: string | null;
  created_at: string;
}

export interface PartFault {
  health: 'Warning' | 'Critical';
  /** Value of the state metric (Redfish health 1 / 2, link 0, ...). */
  value: number;
  state: string;
  since: number;
}

export interface DemoFirmware {
  component: string;
  component_key: string;
  component_type: string;
  version: string;
}

export interface DemoServer {
  id: number;
  name: string;
  hostname: string | null;
  bmc_host: string;
  vendor: string;
  model: string;
  serial: string;
  asset_tag: string | null;
  status: 'active' | 'maintenance' | 'decommissioned';
  site_id: number;
  room_id: number;
  rack_id: number;
  position_u: number;
  height_u: number;
  collector_id: number | null;
  bmc_mac: string;
  bmc_model: string;
  host_ips: string[];
  system_path: string;
  notes: string | null;
  discovered_at: string;
  created_at: string;
  updated_at: string;
  seed: number;
  /** Power draw at idle / full load (W) and PSU capacity. */
  idleW: number;
  maxW: number;
  capacityW: number;
  components: ServerComponent[];
  firmware: DemoFirmware[];
  /** Unhealthy parts by `${metric}|${component}`. */
  faults: Record<string, PartFault>;
  /** Extra gauge behaviour. */
  inletBoost: number;
  slowFan: string | null;
  failedPsu: string | null;
  /** BMC stopped answering at this time (no readings after it). */
  unreachableSince: number | null;
  poweredOff: boolean;
  events: ServerEvent[];
}

export interface DemoMaintenance {
  id: number;
  scope: 'site' | 'rack' | 'server';
  site_id: number | null;
  rack_id: number | null;
  server_id: number | null;
  starts_at: string;
  ends_at: string;
  reason: string;
  created_by: string | null;
  created_at: string;
}

export interface DemoDashboard {
  slug: string;
  title: string;
  embedded_uuid: string;
  refresh_s: number;
}

export interface DemoDb {
  builtAt: number;
  sites: DemoSite[];
  rooms: DemoRoom[];
  racks: DemoRack[];
  collectors: DemoCollector[];
  servers: DemoServer[];
  metrics: Metric[];
  rules: AlertRule[];
  thresholds: Threshold[];
  routes: AlertRoute[];
  routeTargets: Record<number, string>;
  maintenance: DemoMaintenance[];
  baselines: Baseline[];
  alerts: AlertDetail[];
  users: User[];
  audit: AuditEntry[];
  dashboards: DemoDashboard[];
  nextId: () => number;
}

// ---------------------------------------------------------------------------------------------- reference data

/** The 27 metric definitions (same codes as the backend's reference data). */
const METRIC_ROWS: [number, string, string, string, number, string, number, string, string][] = [
  [
    1,
    'inlet_temp_c',
    'Inlet temperature',
    '°C',
    60,
    'gauge',
    1,
    'thermal',
    'Ambient air entering the server (ThermalMetrics / Thermal.Temperatures).',
  ],
  [2, 'exhaust_temp_c', 'Exhaust temperature', '°C', 60, 'gauge', 2, 'thermal', 'Air leaving the server.'],
  [3, 'cpu_temp_c', 'CPU temperature', '°C', 60, 'gauge', 3, 'thermal', 'Per CPU package.'],
  [4, 'dimm_temp_c', 'Memory temperature', '°C', 60, 'gauge', 4, 'thermal', 'Per DIMM or memory zone.'],
  [5, 'fan_rpm', 'Fan speed', 'RPM', 60, 'gauge', 5, 'cooling', 'Per fan, when the BMC reports RPM.'],
  [
    6,
    'fan_pct',
    'Fan speed (percent)',
    '%',
    60,
    'gauge',
    5,
    'cooling',
    'Per fan, when the BMC reports percent of maximum.',
  ],
  [7, 'fan_health', 'Fan health', '', 300, 'state', 6, 'cooling', 'Fan Status.Health.'],
  [8, 'fan_redundancy', 'Fan redundancy', '', 300, 'state', 6, 'cooling', 'Thermal.Redundancy status.'],
  [
    9,
    'power_w',
    'Power draw',
    'W',
    60,
    'gauge',
    7,
    'power',
    'Chassis power consumption (EnvironmentMetrics or Power.PowerControl).',
  ],
  [
    10,
    'power_capacity_w',
    'Power capacity',
    'W',
    300,
    'gauge',
    7,
    'power',
    'Available power capacity reported by the chassis.',
  ],
  [11, 'power_limit_w', 'Power cap', 'W', 300, 'gauge', 7, 'power', 'Configured power limit, if any.'],
  [12, 'psu_health', 'Power supply health', '', 300, 'state', 8, 'power', 'Per power supply Status.Health.'],
  [
    13,
    'psu_input_v',
    'Power supply input voltage',
    'V',
    60,
    'gauge',
    9,
    'power',
    'Line input voltage per power supply.',
  ],
  [
    14,
    'psu_redundancy',
    'Power supply redundancy',
    '',
    300,
    'state',
    10,
    'power',
    'Power.Redundancy or PowerSubsystem redundancy status.',
  ],
  [15, 'power_state', 'Power state', '', 60, 'state', 11, 'power', 'Systems PowerState: 1 = On, 0 = Off.'],
  [
    16,
    'system_health',
    'Overall system health',
    '',
    60,
    'state',
    12,
    'health',
    'Systems Status.HealthRollup.',
  ],
  [17, 'cpu_health', 'CPU health', '', 300, 'state', 13, 'health', 'Per processor Status.Health.'],
  [18, 'memory_health', 'Memory health', '', 300, 'state', 14, 'health', 'Per DIMM Status.Health.'],
  [19, 'drive_health', 'Drive health', '', 300, 'state', 15, 'storage', 'Per drive Status.Health.'],
  [
    20,
    'drive_life_pct',
    'Drive life left',
    '%',
    300,
    'gauge',
    15,
    'storage',
    'PredictedMediaLifeLeftPercent per drive.',
  ],
  [
    21,
    'storage_health',
    'RAID controller health',
    '',
    300,
    'state',
    16,
    'storage',
    'Storage controller Status.Health.',
  ],
  [22, 'volume_health', 'Volume health', '', 300, 'state', 16, 'storage', 'Per volume Status.Health.'],
  [
    23,
    'nic_link',
    'NIC link status',
    '',
    300,
    'state',
    17,
    'network',
    'EthernetInterfaces LinkStatus: 1 = Up, 0 = Down.',
  ],
  [24, 'bmc_health', 'BMC health', '', 60, 'state', 18, 'bmc', 'Managers Status.Health.'],
  [
    25,
    'bmc_reachable',
    'BMC reachable',
    '',
    60,
    'state',
    18,
    'bmc',
    '1 when the poll succeeded, 0 when the BMC did not answer.',
  ],
  [26, 'sel_event', 'System event log', '', 300, 'event', 19, 'events', 'New LogServices entries.'],
  [
    27,
    'firmware_version',
    'Firmware version',
    '',
    86400,
    'version',
    20,
    'firmware',
    'UpdateService/FirmwareInventory versions (BIOS, BMC, drives and more).',
  ],
];

/** Built-in alert rules (same as the backend's defaults). */
const RULE_ROWS: [
  number,
  string,
  string,
  string,
  string | null,
  Record<string, unknown>,
  number,
  string,
  string,
][] = [
  [
    1,
    'Inlet temperature high',
    'Inlet above the warning or critical limit for 3 minutes.',
    'threshold',
    'inlet_temp_c',
    {},
    180,
    'Warning',
    'facilities',
  ],
  [
    2,
    'Exhaust temperature high',
    "Exhaust above the BMC's limits (or an admin override) for 3 minutes.",
    'threshold',
    'exhaust_temp_c',
    { bmc_limits: 'upper' },
    180,
    'Warning',
    'hardware',
  ],
  [
    3,
    'CPU temperature high',
    "CPU above the BMC's limits for 3 minutes.",
    'threshold',
    'cpu_temp_c',
    { bmc_limits: 'upper' },
    180,
    'Warning',
    'hardware',
  ],
  [
    4,
    'Memory temperature high',
    "DIMM above the BMC's limits for 3 minutes.",
    'threshold',
    'dimm_temp_c',
    { bmc_limits: 'upper' },
    180,
    'Warning',
    'hardware',
  ],
  [
    5,
    'Fan speed low',
    "Fan below the BMC's lower threshold for 2 minutes.",
    'threshold',
    'fan_rpm',
    { bmc_limits: 'lower' },
    120,
    'Warning',
    'hardware',
  ],
  [
    6,
    'Fan failed',
    'A fan reports Warning or Critical.',
    'state',
    'fan_health',
    { match: 'health', levels: ['Warning', 'Critical'] },
    0,
    'Warning',
    'hardware',
  ],
  [
    7,
    'Fan redundancy lost',
    'Fan redundancy is not OK.',
    'state',
    'fan_redundancy',
    { match: 'health', levels: ['Warning', 'Critical'] },
    0,
    'Warning',
    'hardware',
  ],
  [
    8,
    'Power draw near capacity',
    'Power draw above 90 % of capacity or power cap for 5 minutes.',
    'threshold',
    'power_w',
    {},
    300,
    'Warning',
    'facilities',
  ],
  [
    9,
    'Power supply unhealthy',
    'A power supply reports Warning or Critical.',
    'state',
    'psu_health',
    { match: 'health', levels: ['Warning', 'Critical'] },
    0,
    'Warning',
    'hardware',
  ],
  [
    10,
    'Power supply voltage out of range',
    'Input voltage more than 10 % from nominal for 3 minutes.',
    'threshold',
    'psu_input_v',
    {},
    180,
    'Warning',
    'facilities',
  ],
  [
    11,
    'Power supply redundancy lost',
    'Power supply redundancy is not OK.',
    'state',
    'psu_redundancy',
    { match: 'health', levels: ['Warning', 'Critical'] },
    0,
    'Warning',
    'hardware',
  ],
  [
    12,
    'Server powered off',
    'Power state is Off outside a maintenance window.',
    'state',
    'power_state',
    { match: 'value', equals: 0, outside_maintenance_only: true },
    120,
    'Critical',
    'hardware',
  ],
  [
    13,
    'System health degraded',
    'Systems HealthRollup is Warning or Critical for 2 minutes.',
    'state',
    'system_health',
    { match: 'health', levels: ['Warning', 'Critical'] },
    120,
    'Warning',
    'hardware',
  ],
  [
    14,
    'CPU unhealthy',
    'A processor reports Warning or Critical.',
    'state',
    'cpu_health',
    { match: 'health', levels: ['Warning', 'Critical'] },
    0,
    'Warning',
    'hardware',
  ],
  [
    15,
    'Memory module unhealthy',
    'A DIMM reports Warning or Critical.',
    'state',
    'memory_health',
    { match: 'health', levels: ['Warning', 'Critical'] },
    0,
    'Warning',
    'hardware',
  ],
  [
    16,
    'Drive unhealthy',
    'A drive reports Warning or Critical.',
    'state',
    'drive_health',
    { match: 'health', levels: ['Warning', 'Critical'] },
    0,
    'Warning',
    'hardware',
  ],
  [
    17,
    'Drive wear-out',
    'Predicted media life left under 10 %.',
    'threshold',
    'drive_life_pct',
    {},
    0,
    'Warning',
    'hardware',
  ],
  [
    18,
    'RAID controller degraded',
    'A storage controller is degraded.',
    'state',
    'storage_health',
    { match: 'health', levels: ['Warning', 'Critical'] },
    0,
    'Warning',
    'hardware',
  ],
  [
    19,
    'Volume degraded',
    'A RAID volume is degraded.',
    'state',
    'volume_health',
    { match: 'health', levels: ['Warning', 'Critical'] },
    0,
    'Warning',
    'hardware',
  ],
  [
    20,
    'NIC link down',
    'A NIC port that is expected to be up reports link down.',
    'state',
    'nic_link',
    { match: 'value', equals: 0, expected_only: true },
    0,
    'Warning',
    'hardware',
  ],
  [
    21,
    'BMC unreachable',
    'Three failed polls in a row.',
    'state',
    'bmc_reachable',
    { match: 'value', equals: 0, consecutive: 3 },
    0,
    'Critical',
    'platform',
  ],
  [
    22,
    'BMC unhealthy',
    'Managers Status is not OK.',
    'state',
    'bmc_health',
    { match: 'health', levels: ['Warning', 'Critical'] },
    300,
    'Warning',
    'platform',
  ],
  [
    23,
    'Critical system event',
    'A new Critical entry in the system event log.',
    'event',
    'sel_event',
    { severities: ['Critical'] },
    0,
    'Critical',
    'hardware',
  ],
  [
    24,
    'Server not reporting',
    'No readings from a server for 3 polls.',
    'missing_data',
    null,
    { polls: 3, target: 'server' },
    180,
    'Critical',
    'platform',
  ],
  [
    25,
    'Collector heartbeat missing',
    'No collector heartbeat for 2 minutes.',
    'missing_data',
    null,
    { target: 'collector', after_s: 120 },
    120,
    'Critical',
    'platform',
  ],
  [
    26,
    'Firmware off baseline',
    'Installed firmware differs from the approved baseline (checked daily).',
    'compliance',
    'firmware_version',
    {},
    0,
    'Warning',
    'hardware',
  ],
];

interface ModelSpec {
  vendor: 'Dell' | 'HPE' | 'Lenovo';
  model: string;
  heightU: number;
  bmcModel: string;
  cpu: string;
  cores: number;
  dimm: string;
  dimmGiB: number;
  drive: string;
  driveGB: number;
  psuW: number;
  controller: string;
  nic: string;
  idleW: [number, number];
  maxW: [number, number];
  firmware: {
    BIOS: string;
    BMC: string;
    CPLD: string;
    NIC: string;
    PSU: string;
    RAID: string;
    DRIVE: string;
  };
}

const MODELS: ModelSpec[] = [
  {
    vendor: 'Dell',
    model: 'PowerEdge R750',
    heightU: 2,
    bmcModel: 'iDRAC9',
    cpu: 'Intel(R) Xeon(R) Gold 6338 CPU @ 2.00GHz',
    cores: 32,
    dimm: 'HMA84GR7DJR4N-XN',
    dimmGiB: 32,
    drive: 'MZ7L3960HCJR0D3',
    driveGB: 960.2,
    psuW: 1400,
    controller: 'PERC H755 Front',
    nic: 'Broadcom Adv. Dual 25Gb Ethernet',
    idleW: [230, 280],
    maxW: [720, 860],
    firmware: {
      BIOS: '1.15.2',
      BMC: '7.10.70.00',
      CPLD: '1.1.1',
      NIC: '22.31.6',
      PSU: '00.1D.79',
      RAID: '52.26.0-5179',
      DRIVE: 'DSG8',
    },
  },
  {
    vendor: 'Dell',
    model: 'PowerEdge R650',
    heightU: 1,
    bmcModel: 'iDRAC9',
    cpu: 'Intel(R) Xeon(R) Silver 4314 CPU @ 2.40GHz',
    cores: 16,
    dimm: 'M393A4K40EB3-CWE',
    dimmGiB: 32,
    drive: 'MZ7L3480HCHQ0D3',
    driveGB: 480.1,
    psuW: 1100,
    controller: 'PERC H345 Front',
    nic: 'Intel(R) Ethernet 25G 2P E810-XXV',
    idleW: [160, 200],
    maxW: [480, 560],
    firmware: {
      BIOS: '1.13.2',
      BMC: '7.10.70.00',
      CPLD: '1.0.6',
      NIC: '22.0.9',
      PSU: '00.24.7A',
      RAID: '51.16.0-4076',
      DRIVE: 'DSG5',
    },
  },
  {
    vendor: 'HPE',
    model: 'ProLiant DL380 Gen10',
    heightU: 2,
    bmcModel: 'iLO 5',
    cpu: 'Intel(R) Xeon(R) Gold 6230R CPU @ 2.10GHz',
    cores: 26,
    dimm: 'P06035-B21',
    dimmGiB: 64,
    drive: 'MZ7KH960HAJR0D3',
    driveGB: 960.1,
    psuW: 800,
    controller: 'HPE Smart Array P816i-a SR Gen10',
    nic: 'HPE Ethernet 10/25Gb 2-port 640SFP28',
    idleW: [210, 250],
    maxW: [620, 700],
    firmware: {
      BIOS: 'U30 v2.90',
      BMC: '2.81',
      CPLD: '0x2A',
      NIC: '20.20.0',
      PSU: '1.00',
      RAID: '5.32',
      DRIVE: 'HPG5',
    },
  },
  {
    vendor: 'HPE',
    model: 'ProLiant DL360 Gen10 Plus',
    heightU: 1,
    bmcModel: 'iLO 5',
    cpu: 'Intel(R) Xeon(R) Gold 5318Y CPU @ 2.10GHz',
    cores: 24,
    dimm: 'P28217-B21',
    dimmGiB: 32,
    drive: 'VK000960GXAUN',
    driveGB: 960.0,
    psuW: 800,
    controller: 'HPE Smart Array P408i-a SR Gen10',
    nic: 'HPE Ethernet 10/25Gb 2-port SFP28 MCX562A',
    idleW: [170, 210],
    maxW: [500, 580],
    firmware: {
      BIOS: 'U46 v1.68',
      BMC: '2.81',
      CPLD: '0x15',
      NIC: '16.35.2000',
      PSU: '1.00',
      RAID: '5.32',
      DRIVE: 'HPG2',
    },
  },
  {
    vendor: 'Lenovo',
    model: 'ThinkSystem SR650',
    heightU: 2,
    bmcModel: 'XClarity Controller',
    cpu: 'Intel(R) Xeon(R) Gold 6248 CPU @ 2.50GHz',
    cores: 20,
    dimm: 'M393A4K40CB2-CVF',
    dimmGiB: 32,
    drive: 'MTFDDAK960TDT',
    driveGB: 960.2,
    psuW: 1100,
    controller: 'ThinkSystem RAID 930-8i',
    nic: 'ThinkSystem Mellanox ConnectX-4 Lx 25Gb',
    idleW: [220, 260],
    maxW: [640, 760],
    firmware: {
      BIOS: 'IVE172H',
      BMC: 'CDI372O',
      CPLD: '4.2.0',
      NIC: '14.32.1010',
      PSU: '6.51',
      RAID: '51.20.0-4475',
      DRIVE: 'J004',
    },
  },
  {
    vendor: 'Lenovo',
    model: 'ThinkSystem SR630 V2',
    heightU: 1,
    bmcModel: 'XClarity Controller 2',
    cpu: 'Intel(R) Xeon(R) Gold 5320 CPU @ 2.20GHz',
    cores: 26,
    dimm: 'HMA84GR7CJR4N-XN',
    dimmGiB: 32,
    drive: 'MZ7L3480HBLT0B7',
    driveGB: 480.1,
    psuW: 750,
    controller: 'ThinkSystem RAID 540-8i',
    nic: 'Broadcom 57414 10/25GbE SFP28 2-port',
    idleW: [170, 200],
    maxW: [470, 540],
    firmware: {
      BIOS: 'U8E128F',
      BMC: 'TGBT40A',
      CPLD: '1.3.2',
      NIC: '222.1.68.0',
      PSU: '7.41',
      RAID: '52.20.0-5224',
      DRIVE: 'GDC5',
    },
  },
];

/** Older versions for servers that are off baseline. */
const OLD_FIRMWARE: Record<string, Partial<Record<'BIOS' | 'BMC', string>>> = {
  'PowerEdge R750': { BIOS: '1.12.1', BMC: '6.10.30.00' },
  'PowerEdge R650': { BIOS: '1.10.2' },
  'ProLiant DL380 Gen10': { BIOS: 'U30 v2.76', BMC: '2.72' },
  'ProLiant DL360 Gen10 Plus': { BMC: '2.65' },
  'ThinkSystem SR650': { BIOS: 'IVE168F' },
};

// ---------------------------------------------------------------------------------------------- parts

function partNames(vendor: ModelSpec['vendor']) {
  switch (vendor) {
    case 'Dell':
      return {
        cpu: (i: number) => `CPU${i}`,
        dimm: (cpu: number, slot: number) => `DIMM ${cpu === 1 ? 'A' : 'B'}${slot}`,
        drive: (i: number) => `Disk ${i}`,
        fan: (i: number) => `Fan ${i}`,
        psu: (i: number) => `PSU ${i}`,
        nic: (i: number) => `NIC ${i}`,
        controller: 'RAID.SL.3-1',
        volume: 'Volume 0',
      };
    case 'HPE':
      return {
        cpu: (i: number) => `Proc ${i}`,
        dimm: (cpu: number, slot: number) => `PROC ${cpu} DIMM ${slot * 3 - 2}`,
        drive: (i: number) => `Drive 1I:1:${i + 1}`,
        fan: (i: number) => `Fan ${i}`,
        psu: (i: number) => `Power Supply ${i}`,
        nic: (i: number) => `Port ${i}`,
        controller: 'Smart Array 0',
        volume: 'Logical Drive 1',
      };
    default:
      return {
        cpu: (i: number) => `CPU ${i}`,
        dimm: (cpu: number, slot: number) => `DIMM ${(cpu - 1) * 12 + slot * 2 - 1}`,
        drive: (i: number) => `Drive ${i}`,
        fan: (i: number) => `Fan ${i}`,
        psu: (i: number) => `PSU${i}`,
        nic: (i: number) => `NIC ${i}`,
        controller: 'RAID Slot 1',
        volume: 'Volume 1',
      };
  }
}

export const FAN_COUNT = 6;
export const DRIVE_COUNT = 4;
export const DIMMS_PER_CPU = 4;

function buildComponents(
  spec: ModelSpec,
  serverId: number,
  macBase: number,
  firstSeen: string,
  lastSeen: string,
  nextId: () => number,
  rand: () => number,
): ServerComponent[] {
  const n = partNames(spec.vendor);
  const out: ServerComponent[] = [];
  const add = (
    c: Omit<ServerComponent, 'id' | 'server_id' | 'first_seen_at' | 'last_seen_at' | 'removed_at'>,
  ) =>
    out.push({
      id: nextId(),
      server_id: serverId,
      first_seen_at: firstSeen,
      last_seen_at: lastSeen,
      removed_at: null,
      ...c,
    });
  const base = {
    manufacturer: null,
    serial: null,
    capacity: null,
    capacity_unit: null,
    firmware_version: null,
    expected_link_up: null,
    extra: {},
  };
  for (let c = 1; c <= 2; c++)
    add({
      ...base,
      type: 'cpu',
      name: n.cpu(c),
      model: spec.cpu,
      manufacturer: 'Intel(R) Corporation',
      capacity: spec.cores,
      capacity_unit: 'cores',
      location: `CPU.Socket.${c}`,
      extra: { threads: spec.cores * 2, max_speed_mhz: 2100 },
    });
  for (let c = 1; c <= 2; c++)
    for (let s = 1; s <= DIMMS_PER_CPU; s++)
      add({
        ...base,
        type: 'dimm',
        name: n.dimm(c, s),
        model: spec.dimm,
        manufacturer: spec.dimm.startsWith('HMA') ? 'SK Hynix' : 'Samsung',
        serial: (0x30000000 + Math.floor(rand() * 0xfffffff)).toString(16).toUpperCase(),
        capacity: spec.dimmGiB,
        capacity_unit: 'GiB',
        location: `DIMM.Socket.${c === 1 ? 'A' : 'B'}${s}`,
        extra: { type: 'DDR4', speed_mhz: 3200 },
      });
  for (let d = 0; d < DRIVE_COUNT; d++)
    add({
      ...base,
      type: 'drive',
      name: n.drive(d),
      model: spec.drive,
      manufacturer: spec.drive.startsWith('MTF') ? 'Micron' : 'Samsung',
      serial: `S${Math.floor(rand() * 1e9)
        .toString(36)
        .toUpperCase()
        .padStart(6, '0')}`,
      capacity: spec.driveGB,
      capacity_unit: 'GB',
      firmware_version: spec.firmware.DRIVE,
      location: `Bay ${d}`,
      extra: { media: 'SSD', protocol: 'SATA', controller: n.controller },
    });
  for (let f = 1; f <= FAN_COUNT; f++)
    add({ ...base, type: 'fan', name: n.fan(f), model: null, location: `Fan.Embedded.${f}A` });
  for (let p = 1; p <= 2; p++)
    add({
      ...base,
      type: 'psu',
      name: n.psu(p),
      model: `PWR SPLY,${spec.psuW}W,RDNT`,
      manufacturer: spec.vendor,
      capacity: spec.psuW,
      capacity_unit: 'W',
      firmware_version: spec.firmware.PSU,
      location: `Bay ${p}`,
    });
  for (let i = 1; i <= 4; i++) {
    const mac = (macBase + i).toString(16).toUpperCase().padStart(12, '0');
    add({
      ...base,
      type: 'nic',
      name: n.nic(i),
      model: i <= 2 ? `${spec.nic} Port ${i}` : `NIC in Slot 3 Port ${i - 2}`,
      capacity: i <= 2 ? 25000 : null,
      capacity_unit: 'Mbps',
      firmware_version: spec.firmware.NIC,
      expected_link_up: i <= 2,
      location: `NIC.${i <= 2 ? 'Integrated.1' : 'Slot.3'}-${((i - 1) % 2) + 1}-1`,
      extra: { mac: mac.match(/.{2}/g)!.join(':') },
    });
  }
  add({
    ...base,
    type: 'storage_controller',
    name: n.controller,
    model: spec.controller,
    manufacturer: spec.vendor,
    firmware_version: spec.firmware.RAID,
    location: n.controller,
  });
  add({
    ...base,
    type: 'volume',
    name: n.volume,
    model: 'Virtual Disk 0',
    capacity: Math.round(spec.driveGB * 2 * 10) / 10,
    capacity_unit: 'GB',
    location: `Disk.Virtual.0-${n.controller}`,
    extra: { raid: 'RAID10', controller: n.controller },
  });
  return out;
}

function buildFirmware(
  spec: ModelSpec,
  offBaseline: Partial<Record<'BIOS' | 'BMC', string>>,
): DemoFirmware[] {
  const bmcName = {
    Dell: 'Integrated Dell Remote Access Controller',
    HPE: 'iLO 5',
    Lenovo: 'XClarity Controller',
  }[spec.vendor];
  const names = partNames(spec.vendor);
  const fw: DemoFirmware[] = [
    {
      component: spec.vendor === 'HPE' ? 'System ROM' : 'BIOS',
      component_key: 'BIOS',
      component_type: 'bios',
      version: offBaseline.BIOS ?? spec.firmware.BIOS,
    },
    {
      component: bmcName,
      component_key: 'BMC',
      component_type: 'bmc',
      version: offBaseline.BMC ?? spec.firmware.BMC,
    },
    { component: 'System CPLD', component_key: 'CPLD', component_type: 'cpld', version: spec.firmware.CPLD },
  ];
  for (let d = 0; d < DRIVE_COUNT; d++)
    fw.push({
      component: names.drive(d),
      component_key: `DRIVE:${spec.drive}`,
      component_type: 'drive',
      version: spec.firmware.DRIVE,
    });
  fw.push(
    { component: spec.nic, component_key: 'NIC', component_type: 'nic', version: spec.firmware.NIC },
    {
      component: `PWR SPLY,${spec.psuW}W,RDNT`,
      component_key: 'PSU',
      component_type: 'psu',
      version: spec.firmware.PSU,
    },
    {
      component: spec.controller,
      component_key: 'RAID',
      component_type: 'storage_controller',
      version: spec.firmware.RAID,
    },
  );
  return fw;
}

// ---------------------------------------------------------------------------------------------- sensor model

/** 0..1 daily cycle (peaks mid-afternoon at the site). */
function diurnal(site: DemoSite, t: number): number {
  return 0.5 + 0.5 * Math.sin(2 * Math.PI * (t / DAY + site.phase) - Math.PI / 2);
}

/** Smooth noise in [-1, 1] for a key, changing every `periodMs`. */
function noise(key: number, t: number, periodMs = 5 * MIN): number {
  const k = Math.floor(t / periodMs);
  const f = (t % periodMs) / periodMs;
  const a = hash01(key, k) * 2 - 1;
  const b = hash01(key, k + 1) * 2 - 1;
  return a + (b - a) * (f * f * (3 - 2 * f));
}

/** CPU load of a server at time t, 0..1. */
function load(s: DemoServer, site: DemoSite, t: number): number {
  const base = 0.25 + (s.seed % 37) / 100;
  return Math.min(0.97, Math.max(0.05, base + 0.25 * diurnal(site, t) + 0.08 * noise(s.seed, t, 15 * MIN)));
}

const r1 = (v: number) => Math.round(v * 10) / 10;

/**
 * Value of a gauge (or state) metric for one part at time t. Null when the server can't report it at t
 * (BMC unreachable, powered off for temperatures/fans).
 */
export function sensorValue(
  db: DemoDb,
  s: DemoServer,
  metric: string,
  component: string,
  t: number,
): number | null {
  if (s.unreachableSince !== null && t >= s.unreachableSince && metric !== 'bmc_reachable') return null;
  const site = db.sites.find((x) => x.id === s.site_id)!;
  const rack = db.racks.find((x) => x.id === s.rack_id);
  const ck = strHash(component);
  const L = s.poweredOff ? 0 : load(s, site, t);
  const inlet =
    21 +
    (rack?.inletOffset ?? 0) +
    s.inletBoost +
    (s.seed % 15) / 10 +
    1.4 * diurnal(site, t) +
    0.25 * noise(s.seed + 1, t);
  const fault = s.faults[`${metric}|${component}`];
  switch (metric) {
    case 'inlet_temp_c':
      return r1(inlet);
    case 'exhaust_temp_c':
      return s.poweredOff ? r1(inlet + 1) : r1(inlet + 11 + 10 * L + 0.4 * noise(s.seed + 2, t));
    case 'cpu_temp_c':
      return s.poweredOff ? null : r1(inlet + 28 + 26 * L + (ck % 5) + 0.8 * noise(s.seed + ck, t, 2 * MIN));
    case 'dimm_temp_c':
      return s.poweredOff
        ? null
        : r1(inlet + 14 + 9 * L + (Math.abs(ck) % 4) * 0.5 + 0.3 * noise(s.seed + ck, t));
    case 'fan_rpm': {
      if (s.poweredOff) return 0;
      if (s.slowFan === component) return Math.round(1700 + 150 * noise(s.seed + ck, t, MIN));
      return Math.round(5600 + 5200 * L + (Math.abs(ck) % 7) * 60 + 120 * noise(s.seed + ck, t, 2 * MIN));
    }
    case 'power_w':
      return s.poweredOff ? 12 : Math.round(s.idleW + (s.maxW - s.idleW) * L + 6 * noise(s.seed + 3, t, MIN));
    case 'power_capacity_w':
      return s.capacityW;
    case 'psu_input_v':
      if (s.failedPsu === component) return 0;
      return r1(229.5 + 1.2 * noise(s.seed + 4 + (ck % 3), t, 10 * MIN));
    case 'drive_life_pct':
      return fault ? 7 : 70 + (Math.abs(s.seed * 7 + ck) % 30);
    case 'power_state':
      return s.poweredOff ? 0 : 1;
    case 'nic_link': {
      const nic = s.components.find((c) => c.type === 'nic' && c.name === component);
      if (fault) return 0;
      return nic?.expected_link_up ? 1 : 0;
    }
    case 'bmc_reachable':
      return s.unreachableSince !== null && t >= s.unreachableSince ? 0 : 1;
    default:
      // Health states: 0 OK, 1 Warning, 2 Critical.
      return fault ? fault.value : 0;
  }
}

/** Redfish-style status word for a reading. */
export function sensorStatus(
  s: DemoServer,
  metric: string,
  component: string,
  value: number | null,
): string | null {
  if (value === null) return null;
  const fault = s.faults[`${metric}|${component}`];
  switch (metric) {
    case 'power_state':
      return value ? 'On' : 'Off';
    case 'nic_link':
      return value ? 'Up' : 'Down';
    case 'bmc_reachable':
      return value ? 'Reachable' : 'Unreachable';
    case 'power_capacity_w':
    case 'drive_life_pct':
      return null;
    case 'inlet_temp_c':
      return value >= 35 ? 'Critical' : value >= 27 ? 'Warning' : 'OK';
    case 'fan_rpm':
      return value < 2500 && !s.poweredOff ? 'Warning' : 'OK';
    case 'psu_input_v':
      return value === 0 ? 'Critical' : 'OK';
    default:
      return fault ? fault.health : 'OK';
  }
}

// ---------------------------------------------------------------------------------------------- build

export function buildDemoDb(now = Date.now()): DemoDb {
  const rand = rng(20261028);
  let idCounter = 1000;
  const nextId = () => ++idCounter;
  const pick = <T>(xs: readonly T[]) => xs[Math.floor(rand() * xs.length)]!;
  const created = iso(now - 120 * DAY);

  const sites: DemoSite[] = [
    {
      id: 1,
      code: 'PNQ1',
      name: 'Pune DC1',
      city: 'Pune',
      country: 'India',
      timezone: 'Asia/Kolkata',
      phase: 0.02,
      created_at: created,
      updated_at: created,
    },
    {
      id: 2,
      code: 'HYD1',
      name: 'Hyderabad DC2',
      city: 'Hyderabad',
      country: 'India',
      timezone: 'Asia/Kolkata',
      phase: 0.0,
      created_at: created,
      updated_at: created,
    },
    {
      id: 3,
      code: 'BLR1',
      name: 'Bengaluru DC3',
      city: 'Bengaluru',
      country: 'India',
      timezone: 'Asia/Kolkata',
      phase: 0.05,
      created_at: iso(now - 60 * DAY),
      updated_at: iso(now - 60 * DAY),
    },
  ];
  const rooms: DemoRoom[] = [
    { id: 1, site_id: 1, name: 'Hall A', floor: '1' },
    { id: 2, site_id: 1, name: 'Hall B', floor: '1' },
    { id: 3, site_id: 2, name: 'Hall 1', floor: 'G' },
    { id: 4, site_id: 3, name: 'Data Hall 1', floor: '2' },
    { id: 5, site_id: 3, name: 'Data Hall 2', floor: '2' },
  ];
  // [room, names, row, capacity W, inlet offset]
  const rackPlan: [number, string[], string, number, number][] = [
    [1, ['A01', 'A02', 'A03', 'A04'], 'A', 12000, 0],
    [2, ['B01', 'B02'], 'B', 8000, 0.6],
    [3, ['C01', 'C02', 'C03'], 'C', 10000, 0.3],
    [4, ['D01', 'D02', 'D03'], 'D', 12000, 0],
    [5, ['E01', 'E02', 'E03'], 'E', 10000, 2.8], // warmer hall; E02 runs hot (containment door left open)
  ];
  const racks: DemoRack[] = [];
  for (const [room_id, names, row, cap, off] of rackPlan)
    for (const name of names)
      racks.push({
        id: racks.length + 1,
        room_id,
        name,
        row,
        height_u: 42,
        power_capacity_w: cap,
        inletOffset: name === 'E02' ? off + 4.6 : off,
      });

  const collectors: DemoCollector[] = [
    {
      id: 1,
      site_id: 1,
      name: 'pnq1-col-a',
      version: '1.0.0',
      hostname: 'collector-pnq1-a',
      enabled: true,
      heartbeatAgeS: 8,
      cert_fingerprint: 'sha256:3f9a1c2be0d74a51c8e27f0b9d6a4e13b5c7d9e0f1a2b3c4d5e6f708192a3b4c',
      created_at: created,
    },
    {
      id: 2,
      site_id: 1,
      name: 'pnq1-col-b',
      version: '1.0.0',
      hostname: 'collector-pnq1-b',
      enabled: true,
      heartbeatAgeS: 21,
      cert_fingerprint: 'sha256:8c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f',
      created_at: created,
    },
    {
      id: 3,
      site_id: 2,
      name: 'hyd1-col-a',
      version: '1.0.0',
      hostname: 'collector-hyd1-a',
      enabled: true,
      heartbeatAgeS: 14,
      cert_fingerprint: null,
      created_at: created,
    },
    {
      id: 4,
      site_id: 3,
      name: 'blr1-col-a',
      version: '1.0.1',
      hostname: 'collector-blr1-a',
      enabled: true,
      heartbeatAgeS: 5,
      cert_fingerprint: null,
      created_at: iso(now - 60 * DAY),
    },
    {
      id: 5,
      site_id: 3,
      name: 'blr1-col-b',
      version: '0.9.4',
      hostname: 'collector-blr1-b',
      enabled: true,
      heartbeatAgeS: 47 * 60,
      cert_fingerprint: null,
      created_at: iso(now - 60 * DAY),
    },
  ];

  // ------------------------------------------------------------------ servers
  const roles = ['esx', 'esx', 'k8s', 'db', 'app', 'web', 'bkp', 'esx'];
  const servers: DemoServer[] = [];
  const perRack = [5, 4, 5, 4, 4, 3, 5, 4, 4, 4, 5, 4, 4, 3, 4];
  let tag = 1;
  for (const rack of racks) {
    const room = rooms.find((r) => r.id === rack.room_id)!;
    const site = sites.find((s) => s.id === room.site_id)!;
    const count = perRack[rack.id - 1] ?? 4;
    let u = 2;
    for (let i = 0; i < count; i++) {
      const id = servers.length + 1;
      const spec = MODELS[(id * 7 + rack.id) % MODELS.length]!;
      const role = roles[(id + rack.id) % roles.length]!;
      const name = `${site.code.toLowerCase()}-${role}${String(id).padStart(3, '0')}.demo.local`;
      const vendorPrefix = { Dell: 'D0:8E:79', HPE: '94:40:C9', Lenovo: '08:94:EF' }[spec.vendor];
      const macTail = (0x100000 + id * 16).toString(16).toUpperCase().padStart(6, '0').slice(-6);
      const macBase = parseInt(`${vendorPrefix.replace(/:/g, '')}${macTail}`, 16);
      const discovered = now - (90 - (id % 40)) * DAY;
      const seed = Math.floor(rand() * 1e6);
      const collector = collectors.filter((c) => c.site_id === site.id)[id % (site.id === 2 ? 1 : 2)] ?? null;
      const s: DemoServer = {
        id,
        name,
        hostname: name,
        bmc_host: `https://10.${20 + site.id}.${rack.id}.${10 + i}`,
        vendor: spec.vendor,
        model: spec.model,
        serial:
          spec.vendor === 'Dell'
            ? Math.floor(rand() * 36 ** 7)
                .toString(36)
                .toUpperCase()
                .padStart(7, '0')
            : `${spec.vendor === 'HPE' ? 'CZJ' : 'J30'}${Math.floor(rand() * 1e7)
                .toString()
                .padStart(7, '0')}`,
        asset_tag: `GCC-${String(tag++).padStart(5, '0')}`,
        status: 'active',
        site_id: site.id,
        room_id: room.id,
        rack_id: rack.id,
        position_u: u,
        height_u: spec.heightU,
        collector_id: collector?.id ?? null,
        bmc_mac: `${vendorPrefix}:${macTail.match(/.{2}/g)!.join(':')}`,
        bmc_model: spec.bmcModel,
        host_ips: [`10.${30 + site.id}.${rack.id}.${20 + i}`],
        system_path:
          spec.vendor === 'Dell'
            ? '/redfish/v1/Systems/System.Embedded.1'
            : spec.vendor === 'HPE'
              ? '/redfish/v1/Systems/1'
              : '/redfish/v1/Systems/1',
        notes: null,
        discovered_at: iso(discovered),
        created_at: iso(discovered - HOUR),
        updated_at: iso(now - (id % 9) * DAY - 3 * HOUR),
        seed,
        idleW: Math.round(spec.idleW[0] + rand() * (spec.idleW[1] - spec.idleW[0])),
        maxW: Math.round(spec.maxW[0] + rand() * (spec.maxW[1] - spec.maxW[0])),
        capacityW: spec.psuW,
        components: [],
        firmware: [],
        faults: {},
        inletBoost: 0,
        slowFan: null,
        failedPsu: null,
        unreachableSince: null,
        poweredOff: false,
        events: [],
      };
      s.components = buildComponents(spec, id, macBase, iso(discovered), iso(now - 4 * MIN), nextId, rand);
      const off = id % 9 === 4 ? (OLD_FIRMWARE[spec.model] ?? {}) : {};
      s.firmware = buildFirmware(spec, off);
      servers.push(s);
      u += spec.heightU + (rand() < 0.3 ? 1 : 0);
    }
  }
  // Rack E01 is mostly empty (being decommissioned).
  const decommissioned = servers.find((s) => s.rack_id === 13 && s.position_u > 6);
  if (decommissioned) decommissioned.status = 'decommissioned';

  // ------------------------------------------------------------------ faults
  const byIdx = (i: number) => servers[i % servers.length]!;
  const comp = (s: DemoServer, type: string, idx = 0) =>
    s.components.filter((c) => c.type === type)[idx]!.name;
  const fault = (
    s: DemoServer,
    metric: string,
    component: string,
    health: 'Warning' | 'Critical',
    value: number,
    state: string,
    agoMs: number,
  ) => {
    s.faults[`${metric}|${component}`] = { health, value, state, since: now - agoMs };
  };
  const scenario: {
    s: DemoServer;
    rule: number;
    metric: string | null;
    component: string;
    severity: 'Warning' | 'Critical';
    title: string;
    message: string;
    value: number | null;
    threshold: number | null;
    ago: number;
    acked?: { by: string; ago: number; note: string };
  }[] = [];

  {
    const s = byIdx(2);
    const psu = comp(s, 'psu', 1);
    s.failedPsu = psu;
    fault(s, 'psu_health', psu, 'Critical', 2, 'Critical', 5 * HOUR);
    fault(s, 'psu_redundancy', '', 'Warning', 1, 'Warning', 5 * HOUR);
    fault(s, 'system_health', '', 'Warning', 1, 'Warning', 5 * HOUR);
    scenario.push({
      s,
      rule: 9,
      metric: 'psu_health',
      component: psu,
      severity: 'Critical',
      title: `Power supply unhealthy: ${s.name} (${psu})`,
      message: `${psu} reports Critical. Input voltage 0 V: the feed or the supply has failed.`,
      value: 2,
      threshold: null,
      ago: 5 * HOUR,
      acked: { by: 'Neha NOC', ago: 4 * HOUR, note: 'Facilities checking PDU B feed in A02.' },
    });
    scenario.push({
      s,
      rule: 11,
      metric: 'psu_redundancy',
      component: '',
      severity: 'Warning',
      title: `Power supply redundancy lost: ${s.name}`,
      message: 'Redundancy is Warning: the server runs on one supply.',
      value: 1,
      threshold: null,
      ago: 5 * HOUR,
    });
  }
  {
    const s = byIdx(9);
    const fan = comp(s, 'fan', 2);
    s.slowFan = fan;
    fault(s, 'fan_health', fan, 'Warning', 1, 'Warning', 95 * MIN);
    fault(s, 'fan_redundancy', '', 'Warning', 1, 'Warning', 95 * MIN);
    scenario.push({
      s,
      rule: 6,
      metric: 'fan_health',
      component: fan,
      severity: 'Warning',
      title: `Fan failed: ${s.name} (${fan})`,
      message: `${fan} reports Warning, running at about 1,700 RPM.`,
      value: 1,
      threshold: null,
      ago: 95 * MIN,
    });
    scenario.push({
      s,
      rule: 5,
      metric: 'fan_rpm',
      component: fan,
      severity: 'Warning',
      title: `Fan speed low: ${s.name} (${fan})`,
      message: `${fan} below the BMC's lower threshold (2,500 RPM) for 2 minutes.`,
      value: 1712,
      threshold: 2500,
      ago: 93 * MIN,
    });
  }
  // Hot aisle in BLR1 Data Hall 2: every server in rack E02 runs warm.
  for (const s of servers.filter((x) => x.rack_id === 14 && x.status === 'active')) {
    fault(s, 'inlet_temp_c', '', 'Warning', 1, 'Warning', 70 * MIN);
    scenario.push({
      s,
      rule: 1,
      metric: 'inlet_temp_c',
      component: '',
      severity: 'Warning',
      title: `Inlet temperature high: ${s.name}`,
      message: 'Inlet above the warning limit (27 °C) for 3 minutes.',
      value: 29.6,
      threshold: 27,
      ago: 70 * MIN,
    });
  }
  {
    const s = byIdx(17);
    const d = comp(s, 'drive', 2);
    fault(s, 'drive_life_pct', d, 'Warning', 7, 'Warning', 3 * DAY);
    scenario.push({
      s,
      rule: 17,
      metric: 'drive_life_pct',
      component: d,
      severity: 'Warning',
      title: `Drive wear-out: ${s.name} (${d})`,
      message: `${d} has 7 % predicted media life left.`,
      value: 7,
      threshold: 10,
      ago: 3 * DAY,
      acked: { by: 'Rohan Engineer', ago: 2 * DAY, note: 'Replacement SSD ordered, RMA 44871.' },
    });
  }
  {
    const s = byIdx(23);
    const dimm = comp(s, 'dimm', 5);
    fault(s, 'memory_health', dimm, 'Critical', 2, 'Critical', 40 * MIN);
    fault(s, 'system_health', '', 'Critical', 2, 'Critical', 40 * MIN);
    s.events.push({
      id: nextId(),
      server_id: s.id,
      time: iso(now - 41 * MIN),
      severity: 'Critical',
      message: `Multi-bit memory errors detected on a memory device at location(s) ${dimm}.`,
      message_id: 'MEM0001',
      entry_id: 'Sel/41',
    });
    scenario.push({
      s,
      rule: 15,
      metric: 'memory_health',
      component: dimm,
      severity: 'Critical',
      title: `Memory module unhealthy: ${s.name} (${dimm})`,
      message: `${dimm} reports Critical (uncorrectable ECC errors).`,
      value: 2,
      threshold: null,
      ago: 40 * MIN,
    });
    scenario.push({
      s,
      rule: 23,
      metric: 'sel_event',
      component: '',
      severity: 'Critical',
      title: `Critical system event: ${s.name}`,
      message: `MEM0001: Multi-bit memory errors detected on a memory device at location(s) ${dimm}.`,
      value: null,
      threshold: null,
      ago: 41 * MIN,
    });
  }
  {
    const s = byIdx(30);
    const nic = comp(s, 'nic', 1);
    fault(s, 'nic_link', nic, 'Warning', 0, 'Down', 25 * MIN);
    scenario.push({
      s,
      rule: 20,
      metric: 'nic_link',
      component: nic,
      severity: 'Warning',
      title: `NIC link down: ${s.name} (${nic})`,
      message: `${nic} is expected up but reports link down.`,
      value: 0,
      threshold: null,
      ago: 25 * MIN,
    });
  }
  {
    const s = byIdx(36);
    s.unreachableSince = now - 18 * MIN;
    fault(s, 'bmc_reachable', '', 'Critical', 0, 'Unreachable', 18 * MIN);
    scenario.push({
      s,
      rule: 21,
      metric: 'bmc_reachable',
      component: '',
      severity: 'Critical',
      title: `BMC unreachable: ${s.name}`,
      message: 'The BMC did not answer three polls in a row (connect timeout).',
      value: 0,
      threshold: null,
      ago: 18 * MIN,
    });
  }
  {
    const s = byIdx(44);
    const vol = comp(s, 'volume');
    const d = comp(s, 'drive', 1);
    fault(s, 'volume_health', vol, 'Warning', 1, 'Warning', 9 * HOUR);
    fault(s, 'drive_health', d, 'Critical', 2, 'Critical', 9 * HOUR);
    fault(s, 'storage_health', comp(s, 'storage_controller'), 'Warning', 1, 'Warning', 9 * HOUR);
    scenario.push({
      s,
      rule: 16,
      metric: 'drive_health',
      component: d,
      severity: 'Warning',
      title: `Drive unhealthy: ${s.name} (${d})`,
      message: `${d} reports Critical; the RAID set is rebuilding onto the hot spare.`,
      value: 2,
      threshold: null,
      ago: 9 * HOUR,
      acked: { by: 'Rohan Engineer', ago: 8 * HOUR, note: 'Swap scheduled for tonight.' },
    });
    scenario.push({
      s,
      rule: 19,
      metric: 'volume_health',
      component: vol,
      severity: 'Warning',
      title: `Volume degraded: ${s.name} (${vol})`,
      message: `${vol} is degraded (RAID10, one member missing).`,
      value: 1,
      threshold: null,
      ago: 9 * HOUR,
    });
  }
  {
    const s = byIdx(51);
    fault(s, 'cpu_health', comp(s, 'cpu', 1), 'Warning', 1, 'Warning', 2 * HOUR);
    scenario.push({
      s,
      rule: 14,
      metric: 'cpu_health',
      component: comp(s, 'cpu', 1),
      severity: 'Warning',
      title: `CPU unhealthy: ${s.name} (${comp(s, 'cpu', 1)})`,
      message: 'Processor reports Warning (thermal trip counter increasing).',
      value: 1,
      threshold: null,
      ago: 2 * HOUR,
    });
  }
  // A server switched off for planned work (muted by the active maintenance window).
  const maintServer = byIdx(6);
  maintServer.poweredOff = true;
  maintServer.status = 'maintenance';
  fault(maintServer, 'power_state', '', 'Critical', 0, 'Off', 50 * MIN);

  // Firmware compliance alerts for servers off baseline.
  for (const s of servers.filter(
    (x) => x.id % 9 === 4 && OLD_FIRMWARE[x.model] && x.status !== 'decommissioned',
  )) {
    for (const key of Object.keys(OLD_FIRMWARE[s.model]!) as ('BIOS' | 'BMC')[])
      scenario.push({
        s,
        rule: 26,
        metric: 'firmware_version',
        component: key,
        severity: 'Warning',
        title: `Firmware off baseline: ${s.name} (${key})`,
        message: `${key} ${OLD_FIRMWARE[s.model]![key]} installed, ${MODELS.find((m) => m.model === s.model)!.firmware[key]} approved.`,
        value: null,
        threshold: null,
        ago: (10 + (s.id % 5)) * HOUR,
      });
  }

  // ------------------------------------------------------------------ events
  const okEvents = [
    ['SYS1003', 'The system inventory was updated successfully.'],
    ['USR0030', 'Successfully logged in using root, from 10.20.0.15 and REDFISH.'],
    ['PSU0800', 'Power supply redundancy is ok.'],
    ['LOG007', 'The previous log entry was repeated 3 times.'],
    ['RAC0182', 'The iDRAC firmware was rebooted with the following reason: user initiated.'],
  ] as const;
  for (const s of servers) {
    const r = rng(s.seed);
    const n = 3 + Math.floor(r() * 4);
    for (let i = 0; i < n; i++) {
      const [mid, msg] = okEvents[Math.floor(r() * okEvents.length)]!;
      s.events.push({
        id: nextId(),
        server_id: s.id,
        time: iso(now - Math.floor(r() * 20 * DAY)),
        severity: 'OK',
        message: msg,
        message_id: mid,
        entry_id: `Sel/${i + 1}`,
      });
    }
    if (r() < 0.25)
      s.events.push({
        id: nextId(),
        server_id: s.id,
        time: iso(now - Math.floor(r() * 6 * DAY)),
        severity: 'Warning',
        message: 'The system board inlet temperature is greater than the upper warning threshold.',
        message_id: 'TMP0118',
        entry_id: `Sel/${n + 1}`,
      });
    s.events.sort((a, b) => Date.parse(b.time) - Date.parse(a.time));
  }

  // ------------------------------------------------------------------ users, rules, thresholds, routes
  const users: User[] = [
    ['Aditi Admin', 'admin@gcc.example', ['platform_admin'], null, 1 * HOUR],
    ['Neha NOC', 'noc@gcc.example', ['noc_operator'], null, 20 * MIN],
    ['Rohan Engineer', 'engineer@gcc.example', ['dc_engineer'], null, 3 * HOUR],
    ['Vikram Viewer', 'viewer@gcc.example', ['viewer'], null, 2 * DAY],
    ['Anita Analyst', 'analyst@gcc.example', ['analyst'], null, 5 * HOUR],
    ['Pooja NOC (Pune)', 'noc-pune@gcc.example', ['noc_operator'], ['PNQ1'], 40 * MIN],
    ['Imran Engineer (Hyderabad)', 'engineer-hyd@gcc.example', ['dc_engineer'], ['HYD1'], 6 * HOUR],
    ['Karthik Engineer (Bengaluru)', 'engineer-blr@gcc.example', ['dc_engineer'], ['BLR1'], 26 * HOUR],
    ['Sara Night Shift', 'sara.nightshift@gcc.example', ['noc_operator'], null, 9 * HOUR],
    ['Platform Bot', null, ['viewer'], null, null],
  ].map(([name, email, r, siteCodes, ago], i) => ({
    id: i + 1,
    sub: `demo-${String(i + 1).padStart(4, '0')}-${(strHash(String(name)) >>> 0).toString(16)}`,
    email: email as string | null,
    name: name as string,
    roles: r as string[],
    sites: siteCodes as string[] | null,
    last_login_at: ago === null ? null : iso(now - (ago as number)),
    created_at: iso(now - (100 - i * 5) * DAY),
  }));

  const metrics: Metric[] = METRIC_ROWS.map(
    ([id, code, name, unit, interval_s, type, parameter_no, category, description]) => ({
      id,
      code,
      name,
      unit,
      interval_s,
      type,
      parameter_no,
      category,
      description,
    }),
  );
  const rules: AlertRule[] = RULE_ROWS.map(
    ([id, name, description, rule_type, metric, condition, duration_s, severity, route]) => ({
      id,
      name,
      description,
      rule_type,
      metric,
      condition,
      duration_s,
      severity,
      route,
      enabled: true,
      builtin: true,
      updated_by: 'system',
      updated_at: created,
    }),
  );
  rules.push({
    id: 27,
    name: 'BLR1 inlet early warning',
    description: 'Custom: warn the facilities team earlier in the new Bengaluru halls.',
    rule_type: 'threshold',
    metric: 'inlet_temp_c',
    condition: { site: 'BLR1', above: 26 },
    duration_s: 300,
    severity: 'Info',
    route: 'facilities',
    enabled: false,
    builtin: false,
    updated_by: 'Aditi Admin',
    updated_at: iso(now - 12 * DAY),
  });

  const metricName = (code: string) => metrics.find((m) => m.code === code)!;
  const th = (
    id: number,
    metric: string,
    scope: string,
    extra: Partial<Threshold>,
    direction: string,
    warning: number | null,
    critical: number | null,
    by = 'system',
    ago = 120 * DAY,
  ): Threshold => ({
    id,
    metric,
    metric_name: metricName(metric).name,
    unit: metricName(metric).unit,
    scope,
    site_id: null,
    server_id: null,
    vendor: null,
    model: null,
    direction,
    warning,
    critical,
    nominal: null,
    updated_by: by,
    updated_at: iso(now - ago),
    ...extra,
  });
  const thresholds: Threshold[] = [
    th(1, 'inlet_temp_c', 'global', {}, 'above', 27, 35),
    th(2, 'power_w', 'global', {}, 'pct_of_capacity', 90, 100),
    th(3, 'psu_input_v', 'global', {}, 'deviation_pct', 10, null),
    th(4, 'drive_life_pct', 'global', {}, 'below', 10, null),
    th(5, 'inlet_temp_c', 'site', { site_id: 3 }, 'above', 27, 32, 'Aditi Admin', 30 * DAY),
    th(
      6,
      'exhaust_temp_c',
      'model',
      { vendor: 'HPE', model: 'ProLiant DL380 Gen10' },
      'above',
      48,
      55,
      'Rohan Engineer',
      14 * DAY,
    ),
    th(7, 'cpu_temp_c', 'server', { server_id: servers[11]!.id }, 'above', 82, 92, 'Rohan Engineer', 5 * DAY),
  ];
  thresholds[2]!.nominal = 230;

  const routeTargets: Record<number, string> = {};
  const route = (
    id: number,
    name: string,
    r: string,
    site_id: number | null,
    min_severity: string,
    escalation_level: number,
    channel: string,
    target: string,
    hint: string,
    enabled = true,
  ): AlertRoute => {
    routeTargets[id] = target;
    return {
      id,
      name,
      route: r,
      site_id,
      min_severity,
      escalation_level,
      channel,
      target_hint: hint,
      enabled,
      created_at: iso(now - 90 * DAY),
      updated_at: iso(now - id * 3 * DAY),
    };
  };
  const routes: AlertRoute[] = [
    route(
      1,
      'NOC email — all sites',
      '*',
      null,
      'Warning',
      0,
      'email',
      'noc@gcc.example',
      'n***@gcc.example',
    ),
    route(
      2,
      'NOC Teams channel',
      '*',
      null,
      'Critical',
      0,
      'teams',
      'https://gcc.webhook.office.com/webhookb2/demo-noc',
      'https://gcc.webhook.office.com/…/demo-noc',
    ),
    route(
      3,
      'Pune facilities',
      'facilities',
      1,
      'Warning',
      0,
      'email',
      'facilities-pnq@gcc.example',
      'f***@gcc.example',
    ),
    route(
      4,
      'Bengaluru facilities',
      'facilities',
      3,
      'Warning',
      0,
      'email',
      'facilities-blr@gcc.example, blr-hvac@gcc.example',
      'f***@gcc.example +1',
    ),
    route(
      5,
      'Platform on-call escalation',
      'platform',
      null,
      'Critical',
      1,
      'teams',
      'https://gcc.webhook.office.com/webhookb2/demo-oncall',
      'https://gcc.webhook.office.com/…/demo-oncall',
    ),
    route(
      6,
      'Duty manager (2nd escalation)',
      '*',
      null,
      'Critical',
      2,
      'email',
      'duty-manager@gcc.example',
      'd***@gcc.example',
    ),
    route(
      7,
      'Hyderabad hardware team',
      'hardware',
      2,
      'Warning',
      0,
      'email',
      'hw-hyd@gcc.example',
      'h***@gcc.example',
      false,
    ),
  ];

  // ------------------------------------------------------------------ maintenance
  const maintRack = racks[12]!;
  const maintenance: DemoMaintenance[] = [
    {
      id: 1,
      scope: 'server',
      site_id: null,
      rack_id: null,
      server_id: maintServer.id,
      starts_at: iso(now - 55 * MIN),
      ends_at: iso(now + 2 * HOUR + 5 * MIN),
      reason: 'Motherboard replacement (vendor case 7731-22). Server powered off.',
      created_by: 'Rohan Engineer',
      created_at: iso(now - 26 * HOUR),
    },
    {
      id: 2,
      scope: 'rack',
      site_id: null,
      rack_id: maintRack.id,
      server_id: null,
      starts_at: iso(now + 2 * DAY + 4 * HOUR),
      ends_at: iso(now + 2 * DAY + 8 * HOUR),
      reason: 'PDU firmware upgrade on both feeds.',
      created_by: 'Karthik Engineer (Bengaluru)',
      created_at: iso(now - 3 * DAY),
    },
    {
      id: 3,
      scope: 'site',
      site_id: 2,
      rack_id: null,
      server_id: null,
      starts_at: iso(now - 6 * DAY - 2 * HOUR),
      ends_at: iso(now - 6 * DAY + 2 * HOUR),
      reason: 'Quarterly UPS load test.',
      created_by: 'Imran Engineer (Hyderabad)',
      created_at: iso(now - 10 * DAY),
    },
    {
      id: 4,
      scope: 'server',
      site_id: null,
      rack_id: null,
      server_id: servers[20]!.id,
      starts_at: iso(now + 5 * HOUR),
      ends_at: iso(now + 7 * HOUR),
      reason: 'BIOS and iDRAC update to baseline.',
      created_by: 'Rohan Engineer',
      created_at: iso(now - 4 * HOUR),
    },
  ];

  // ------------------------------------------------------------------ baselines
  const baselines: Baseline[] = [];
  for (const m of MODELS) {
    if (m.model === 'ThinkSystem SR630 V2') continue; // new model, no baseline yet
    for (const key of ['BIOS', 'BMC', 'RAID'] as const)
      baselines.push({
        id: baselines.length + 1,
        vendor: m.vendor,
        model: m.model,
        component: key,
        version: m.firmware[key],
        notes: key === 'BIOS' ? 'Approved by change board CAB-2026-114.' : null,
        updated_by: 'Rohan Engineer',
        updated_at: iso(now - (20 + baselines.length) * DAY),
      });
  }
  baselines.push({
    id: baselines.length + 1,
    vendor: 'Dell',
    model: 'PowerEdge R750',
    component: `DRIVE:${MODELS[0]!.drive}`,
    version: MODELS[0]!.firmware.DRIVE,
    notes: 'Fixes SMART reporting on early lots.',
    updated_by: 'Rohan Engineer',
    updated_at: iso(now - 9 * DAY),
  });

  // ------------------------------------------------------------------ alerts
  const siteRef = (id: number) => {
    const s = sites.find((x) => x.id === id)!;
    return { id: s.id, code: s.code, name: s.name };
  };
  const collectorBrief = (id: number | null) => {
    const c = collectors.find((x) => x.id === id);
    return c ? { id: c.id, name: c.name } : null;
  };
  const ruleRef = (id: number) => {
    const r = rules.find((x) => x.id === id)!;
    return { id: r.id, name: r.name, rule_type: r.rule_type };
  };
  const activity = (items: Omit<AlertActivity, 'id'>[]): AlertActivity[] =>
    items.map((a) => ({ id: nextId(), ...a })).sort((a, b) => Date.parse(b.time) - Date.parse(a.time));

  let alertId = 500;
  const alerts: AlertDetail[] = [];
  for (const sc of scenario) {
    const opened = now - sc.ago;
    const acked = sc.acked ? now - sc.acked.ago : null;
    const act: Omit<AlertActivity, 'id'>[] = [
      {
        time: iso(opened),
        actor: 'system',
        action: 'opened',
        from_state: null,
        to_state: 'open',
        note: null,
        details: { value: sc.value },
      },
      {
        time: iso(opened + 20_000),
        actor: 'system',
        action: 'notified',
        from_state: null,
        to_state: null,
        note: null,
        details: { channels: sc.severity === 'Critical' ? ['email', 'teams'] : ['email'] },
      },
    ];
    if (sc.acked)
      act.push({
        time: iso(acked!),
        actor: sc.acked.by,
        action: 'acknowledged',
        from_state: 'open',
        to_state: 'acknowledged',
        note: sc.acked.note,
        details: {},
      });
    const escalated = sc.severity === 'Critical' && !sc.acked && sc.ago > 15 * MIN ? opened + 15 * MIN : null;
    if (escalated)
      act.push({
        time: iso(escalated),
        actor: 'system',
        action: 'escalated',
        from_state: null,
        to_state: null,
        note: null,
        details: { level: 1 },
      });
    alerts.push({
      id: ++alertId,
      rule: ruleRef(sc.rule),
      server: { id: sc.s.id, name: sc.s.name, bmc_host: sc.s.bmc_host },
      site: siteRef(sc.s.site_id),
      collector: collectorBrief(sc.s.collector_id),
      metric: sc.metric,
      component: sc.component,
      state: sc.acked ? 'acknowledged' : 'open',
      severity: sc.severity,
      title: sc.title,
      message: sc.message,
      value: sc.value,
      threshold: sc.threshold,
      muted: false,
      occurrences: sc.rule === 1 ? 4 : 1,
      opened_at: iso(opened),
      last_seen_at: iso(now - 40_000),
      acked_at: acked ? iso(acked) : null,
      acked_by: sc.acked?.by ?? null,
      resolved_at: null,
      resolved_by: null,
      notified_at: iso(opened + 20_000),
      escalated_at: escalated ? iso(escalated) : null,
      manually_resolvable: ['event', 'compliance'].includes(ruleRef(sc.rule).rule_type),
      activity: activity(act),
    });
  }
  // Muted: the powered-off server in maintenance.
  alerts.push({
    id: ++alertId,
    rule: ruleRef(12),
    server: { id: maintServer.id, name: maintServer.name, bmc_host: maintServer.bmc_host },
    site: siteRef(maintServer.site_id),
    collector: collectorBrief(maintServer.collector_id),
    metric: 'power_state',
    component: '',
    state: 'open',
    severity: 'Critical',
    title: `Server powered off: ${maintServer.name}`,
    message: 'Power state is Off. Muted: maintenance window active.',
    value: 0,
    threshold: null,
    muted: true,
    occurrences: 1,
    opened_at: iso(now - 48 * MIN),
    last_seen_at: iso(now - 40_000),
    acked_at: null,
    acked_by: null,
    resolved_at: null,
    resolved_by: null,
    notified_at: null,
    escalated_at: null,
    manually_resolvable: false,
    activity: activity([
      {
        time: iso(now - 48 * MIN),
        actor: 'system',
        action: 'opened',
        from_state: null,
        to_state: 'open',
        note: 'Muted by maintenance window #1.',
        details: {},
      },
    ]),
  });
  // Collector offline.
  {
    const c = collectors[4]!;
    alerts.push({
      id: ++alertId,
      rule: ruleRef(25),
      server: null,
      site: siteRef(c.site_id),
      collector: { id: c.id, name: c.name },
      metric: null,
      component: '',
      state: 'open',
      severity: 'Critical',
      title: `Collector heartbeat missing: ${c.name}`,
      message: `No heartbeat from ${c.name} for 47 minutes. Its servers failed over to blr1-col-a.`,
      value: null,
      threshold: null,
      muted: false,
      occurrences: 1,
      opened_at: iso(now - 45 * MIN),
      last_seen_at: iso(now - 30_000),
      acked_at: null,
      acked_by: null,
      resolved_at: null,
      resolved_by: null,
      notified_at: iso(now - 45 * MIN + 15_000),
      escalated_at: iso(now - 30 * MIN),
      manually_resolvable: false,
      activity: activity([
        {
          time: iso(now - 45 * MIN),
          actor: 'system',
          action: 'opened',
          from_state: null,
          to_state: 'open',
          note: null,
          details: {},
        },
        {
          time: iso(now - 45 * MIN + 15_000),
          actor: 'system',
          action: 'notified',
          from_state: null,
          to_state: null,
          note: null,
          details: { channels: ['email', 'teams'] },
        },
        {
          time: iso(now - 30 * MIN),
          actor: 'system',
          action: 'escalated',
          from_state: null,
          to_state: null,
          note: null,
          details: { level: 1 },
        },
      ]),
    });
  }
  // Resolved history over the last 30 days (for the alert list and analytics).
  const historyKinds: [number, string | null, string, 'Warning' | 'Critical', (s: DemoServer) => string][] = [
    [1, 'inlet_temp_c', 'Inlet temperature high', 'Warning', () => ''],
    [6, 'fan_health', 'Fan failed', 'Warning', (s) => comp(s, 'fan', 3)],
    [8, 'power_w', 'Power draw near capacity', 'Warning', () => ''],
    [20, 'nic_link', 'NIC link down', 'Warning', (s) => comp(s, 'nic', 0)],
    [21, 'bmc_reachable', 'BMC unreachable', 'Critical', () => ''],
    [24, null, 'Server not reporting', 'Critical', () => ''],
    [9, 'psu_health', 'Power supply unhealthy', 'Warning', (s) => comp(s, 'psu', 0)],
    [16, 'drive_health', 'Drive unhealthy', 'Warning', (s) => comp(s, 'drive', 0)],
    [23, 'sel_event', 'Critical system event', 'Critical', () => ''],
  ];
  const resolvers = ['system', 'system', 'system', 'Neha NOC', 'Rohan Engineer', 'Sara Night Shift'];
  for (let i = 0; i < 70; i++) {
    const s = pick(servers.filter((x) => x.status !== 'decommissioned'));
    const [ruleId, metric, label, severity, compFn] = pick(historyKinds);
    const opened = now - (1 + rand() * 29) * DAY;
    const dur = (5 + rand() * 300) * MIN;
    const resolvedBy = pick(resolvers);
    const component = compFn(s);
    const ackedAt = rand() < 0.6 ? opened + Math.min(dur * 0.4, 20 * MIN) : null;
    const ackBy = ackedAt ? pick(['Neha NOC', 'Sara Night Shift', 'Pooja NOC (Pune)']) : null;
    const act: Omit<AlertActivity, 'id'>[] = [
      {
        time: iso(opened),
        actor: 'system',
        action: 'opened',
        from_state: null,
        to_state: 'open',
        note: null,
        details: {},
      },
    ];
    if (ackedAt)
      act.push({
        time: iso(ackedAt),
        actor: ackBy!,
        action: 'acknowledged',
        from_state: 'open',
        to_state: 'acknowledged',
        note: null,
        details: {},
      });
    act.push({
      time: iso(opened + dur),
      actor: resolvedBy,
      action: 'resolved',
      from_state: ackedAt ? 'acknowledged' : 'open',
      to_state: 'resolved',
      note: resolvedBy === 'system' ? 'Back to normal for the full duration.' : 'Fixed on site.',
      details: {},
    });
    alerts.push({
      id: ++alertId,
      rule: ruleRef(ruleId),
      server: { id: s.id, name: s.name, bmc_host: s.bmc_host },
      site: siteRef(s.site_id),
      collector: collectorBrief(s.collector_id),
      metric,
      component,
      state: 'resolved',
      severity,
      title: `${label}: ${s.name}${component ? ` (${component})` : ''}`,
      message: `${label}. Resolved after ${Math.round(dur / MIN)} minutes.`,
      value: null,
      threshold: null,
      muted: false,
      occurrences: 1 + Math.floor(rand() * 3),
      opened_at: iso(opened),
      last_seen_at: iso(opened + dur - MIN),
      acked_at: ackedAt ? iso(ackedAt) : null,
      acked_by: ackBy,
      resolved_at: iso(opened + dur),
      resolved_by: resolvedBy,
      notified_at: iso(opened + 20_000),
      escalated_at: null,
      manually_resolvable: false,
      activity: activity(act),
    });
  }
  alerts.sort((a, b) => Date.parse(b.opened_at) - Date.parse(a.opened_at));

  // ------------------------------------------------------------------ audit
  const audit: AuditEntry[] = [];
  const auditRow = (
    ago: number,
    user: User,
    action: string,
    object_type: string,
    object_id: string | null,
    before: Record<string, unknown> | null,
    after: Record<string, unknown> | null,
  ) =>
    audit.push({
      id: audit.length + 1,
      time: iso(now - ago),
      user_sub: user.sub,
      user_name: user.name,
      action,
      object_type,
      object_id,
      before,
      after,
      ip: `10.10.${4 + (user.id % 3)}.${20 + user.id}`,
      request_id: (strHash(`${action}${ago}`) >>> 0).toString(16).padStart(8, '0') + 'a3c1e5f7b9d24680',
    });
  const [uAdmin, uNoc, uEng, , , uNocPune, uEngHyd, uEngBlr, uSara] = users as [
    User,
    User,
    User,
    User,
    User,
    User,
    User,
    User,
    User,
  ];
  for (const a of alerts.filter((x) => x.acked_by && x.state !== 'resolved')) {
    const u = users.find((x) => x.name === a.acked_by) ?? uNoc;
    auditRow(
      now - Date.parse(a.acked_at!),
      u,
      'alert.ack',
      'alert',
      String(a.id),
      { state: 'open' },
      { state: 'acknowledged', note: a.activity.find((x) => x.action === 'acknowledged')?.note ?? null },
    );
  }
  auditRow(20 * MIN, uNoc, 'user.login', 'user', uNoc.sub, null, { roles: uNoc.roles, sites: null });
  auditRow(40 * MIN, uNocPune, 'user.login', 'user', uNocPune.sub, null, {
    roles: uNocPune.roles,
    sites: ['PNQ1'],
  });
  auditRow(60 * MIN, uAdmin, 'user.login', 'user', uAdmin.sub, null, { roles: uAdmin.roles, sites: null });
  auditRow(4 * HOUR, uEng, 'maintenance.create', 'maintenance_window', '4', null, {
    scope: 'server',
    server_id: servers[20]!.id,
    reason: 'BIOS and iDRAC update to baseline.',
  });
  auditRow(26 * HOUR, uEng, 'maintenance.create', 'maintenance_window', '1', null, {
    scope: 'server',
    server_id: maintServer.id,
    reason: maintenance[0]!.reason,
  });
  auditRow(3 * DAY, uEngBlr, 'maintenance.create', 'maintenance_window', '2', null, {
    scope: 'rack',
    rack_id: maintRack.id,
  });
  auditRow(5 * DAY, uEng, 'threshold.create', 'threshold', '7', null, {
    metric: 'cpu_temp_c',
    scope: 'server',
    warning: 82,
    critical: 92,
  });
  auditRow(
    9 * HOUR,
    uSara,
    'alert.comment',
    'alert',
    String(alerts.find((a) => a.state !== 'resolved')!.id),
    null,
    { note: 'Handed over to day shift.' },
  );
  auditRow(9 * DAY, uEng, 'baseline.create', 'firmware_baseline', String(baselines.length), null, {
    vendor: 'Dell',
    model: 'PowerEdge R750',
    component: `DRIVE:${MODELS[0]!.drive}`,
    version: MODELS[0]!.firmware.DRIVE,
  });
  auditRow(12 * DAY, uAdmin, 'alert_rule.create', 'alert_rule', '27', null, {
    name: 'BLR1 inlet early warning',
    enabled: false,
  });
  auditRow(14 * DAY, uEng, 'threshold.create', 'threshold', '6', null, {
    metric: 'exhaust_temp_c',
    scope: 'model',
    model: 'ProLiant DL380 Gen10',
    warning: 48,
    critical: 55,
  });
  auditRow(18 * DAY, uAdmin, 'alert_route.update', 'alert_route', '7', { enabled: true }, { enabled: false });
  auditRow(
    21 * DAY,
    uEngHyd,
    'server.update',
    'server',
    String(servers.find((s) => s.site_id === 2)!.id),
    { position_u: 12 },
    { position_u: 14 },
  );
  auditRow(30 * DAY, uAdmin, 'threshold.create', 'threshold', '5', null, {
    metric: 'inlet_temp_c',
    scope: 'site',
    site: 'BLR1',
    warning: 27,
    critical: 32,
  });
  auditRow(45 * DAY, uAdmin, 'collector.create', 'collector', '5', null, {
    name: 'blr1-col-b',
    site: 'BLR1',
  });
  auditRow(46 * DAY, uAdmin, 'collector.create', 'collector', '4', null, {
    name: 'blr1-col-a',
    site: 'BLR1',
  });
  auditRow(60 * DAY, uAdmin, 'site.create', 'site', '3', null, {
    code: 'BLR1',
    name: 'Bengaluru DC3',
    city: 'Bengaluru',
  });
  for (const s of servers.filter((x) => x.site_id === 3).slice(0, 6))
    auditRow(now - Date.parse(s.created_at), uEngBlr, 'server.create', 'server', String(s.id), null, {
      name: s.name,
      bmc_host: s.bmc_host,
      rack_id: s.rack_id,
      position_u: s.position_u,
    });
  audit.sort((a, b) => Date.parse(b.time) - Date.parse(a.time));
  audit.forEach((a, i) => (a.id = audit.length - i));

  const dashboards: DemoDashboard[] = [
    { slug: 'dc-overview', title: 'Data center overview', embedded_uuid: 'demo-dc-overview', refresh_s: 300 },
    { slug: 'thermal', title: 'Thermal', embedded_uuid: 'demo-thermal', refresh_s: 300 },
    {
      slug: 'power-capacity',
      title: 'Power and capacity',
      embedded_uuid: 'demo-power-capacity',
      refresh_s: 900,
    },
    {
      slug: 'hardware-health',
      title: 'Hardware health',
      embedded_uuid: 'demo-hardware-health',
      refresh_s: 900,
    },
    { slug: 'alerts', title: 'Alerts', embedded_uuid: 'demo-alerts', refresh_s: 900 },
    {
      slug: 'inventory-firmware',
      title: 'Inventory and firmware',
      embedded_uuid: 'demo-inventory-firmware',
      refresh_s: 86400,
    },
  ];

  return {
    builtAt: now,
    sites,
    rooms,
    racks,
    collectors,
    servers,
    metrics,
    rules,
    thresholds,
    routes,
    routeTargets,
    maintenance,
    baselines,
    alerts,
    users,
    audit,
    dashboards,
    nextId,
  };
}

export type { Health };
