/**
 * /dev/gallery — every component with sample data, in both themes. Dev builds only (not routed in prod).
 * This is how components are reviewed before the data-driven screens exist.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react';

import { ApiError } from '@/api/errors';
import { AuthContext, createStaticAuth } from '@/auth/AuthProvider';
import { Button, IconButton } from '@/components/Button';
import { Combobox } from '@/components/Combobox';
import { DataTable, type Column, type SortState } from '@/components/DataTable';
import { ConfirmDialog } from '@/components/Dialog';
import { Drawer } from '@/components/Drawer';
import { EmptyState } from '@/components/EmptyState';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import {
  Checkbox,
  FormField,
  NumberInput,
  Select,
  Switch,
  TextArea,
  TextInput,
} from '@/components/FormField';
import { GlassCard } from '@/components/GlassCard';
import { HealthBadge } from '@/components/HealthBadge';
import { Icon, iconNames } from '@/components/Icon';
import { PageHeader } from '@/components/PageHeader';
import { RackView, type RackServer } from '@/components/RackView';
import { Reading } from '@/components/Reading';
import { SensorChart } from '@/components/SensorChart';
import { Sidebar } from '@/components/shell/Sidebar';
import { ShellProvider } from '@/components/shell/ShellContext';
import { GlobalSearch } from '@/components/shell/GlobalSearch';
import { AlertsBell, LiveIndicator, SiteFilter, ThemeToggle, UserMenu } from '@/components/shell/TopBar';
import { Skeleton, SkeletonCard } from '@/components/Skeleton';
import { Spinner } from '@/components/Spinner';
import { StatTile } from '@/components/StatTile';
import { Tabs } from '@/components/Tabs';
import { useToast } from '@/components/Toast';
import { cn } from '@/lib/cn';
import { ThemeScope } from '@/theme/ThemeProvider';
import { brand, chartPalette, health, healthStates, type ThemeName } from '@/theme/tokens';

import {
  appendPoint,
  fanSeries,
  inletSeries,
  makeServers,
  rackServers,
  sampleSearch,
  sampleSites,
  sampleUser,
  type SampleServer,
} from './sampleData';

type Mode = 'both' | ThemeName;

export default function GalleryPage() {
  const [mode, setMode] = useState<Mode>('both');
  const auth = useMemo(() => createStaticAuth(sampleUser), []);
  const shellData = useMemo(
    () => ({ sites: sampleSites, search: sampleSearch, openAlerts: { count: 7, critical: 2 } }),
    [],
  );
  const themesToShow: ThemeName[] = mode === 'both' ? ['dark', 'light'] : [mode];

  return (
    <AuthContext.Provider value={auth}>
      <ShellProvider data={shellData}>
        <div className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6">
          <PageHeader
            title="Component gallery"
            subtitle="Dev only. Every component with sample data, in both themes."
            breadcrumbs={[{ label: 'Dev' }, { label: 'Gallery' }]}
            actions={
              <Tabs
                label="Theme"
                value={mode}
                onChange={(v) => setMode(v as Mode)}
                tabs={[
                  { id: 'both', label: 'Both' },
                  { id: 'dark', label: 'Dark' },
                  { id: 'light', label: 'Light' },
                ]}
              />
            }
          />
          <div className="flex flex-col gap-8">
            {themesToShow.map((t) => (
              <ThemeScope key={t} theme={t} className="rounded-2xl p-4 sm:p-6">
                <h2 className="mb-6 text-lg font-semibold capitalize text-text">{t} theme</h2>
                <GallerySections />
              </ThemeScope>
            ))}
          </div>
        </div>
      </ShellProvider>
    </AuthContext.Provider>
  );
}

function Section({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn('mb-10', className)}>
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.12em] text-text-subtle">{title}</h3>
      {children}
    </section>
  );
}

function GallerySections() {
  return (
    <>
      <TokensSection />
      <Section title="HealthBadge — word + color + icon">
        <div className="flex flex-col gap-3">
          {(['soft', 'solid', 'plain'] as const).map((v) => (
            <div key={v} className="flex flex-wrap items-center gap-3">
              <span className="w-12 text-xs text-text-subtle">{v}</span>
              {healthStates.map((h) => (
                <HealthBadge key={h} health={h} variant={v} />
              ))}
              <HealthBadge health="Critical" size="sm" variant={v} />
              <HealthBadge health="OK" size="lg" variant={v} />
            </div>
          ))}
        </div>
      </Section>

      <Section title="Reading — value, unit, ticking age">
        <GlassCard className="flex flex-wrap gap-x-8 gap-y-3">
          <Reading value={41.2} unit="°C" time={Date.now() - 3000} />
          <Reading value={2140} unit="RPM" time={Date.now() - 30_000} />
          <Reading value={612} unit="W" time={Date.now() - 5 * 60_000} />
          <Reading value={231.4} unit="V" time={Date.now() - 3 * 3600_000} />
          <Reading value={null} unit="%" time={Date.now() - 10_000} />
          <Reading value={88} unit="%" />
          <Reading value={24.6} unit="°C" time={Date.now() - 12_000} layout="stacked" />
        </GlassCard>
      </Section>

      <Section title="StatTile">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile
            label="Servers reporting"
            value={498}
            unit="servers"
            time={Date.now() - 20_000}
            icon="server"
            footnote="of 500 onboarded"
          />
          <StatTile
            label="Total power"
            value={182_450}
            unit="W"
            time={Date.now() - 45_000}
            icon="zap"
            delta={{ value: 3.2, unit: '%', label: 'vs 24 h', goodWhen: 'down' }}
          />
          <StatTile
            label="Avg inlet"
            value={27.8}
            unit="°C"
            time={Date.now() - 70_000}
            icon="thermometer"
            health="Warning"
          />
          <StatTile label="Open alerts" value={null} unit="alerts" loading />
        </div>
      </Section>

      <Section title="GlassCard">
        <div className="grid gap-4 md:grid-cols-3">
          <GlassCard tone="subtle" title="Subtle">
            Nested surfaces.
          </GlassCard>
          <GlassCard title="Base" actions={<IconButton icon="more-horizontal" label="More" size="sm" />}>
            Default card with a header row.
          </GlassCard>
          <GlassCard tone="strong" title="Strong" interactive tabIndex={0}>
            Popovers, dialogs; interactive hover.
          </GlassCard>
        </div>
      </Section>

      <Section title="Buttons">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" icon="check">
            Acknowledge
          </Button>
          <Button>Secondary</Button>
          <Button variant="ghost" icon="refresh">
            Ghost
          </Button>
          <Button variant="danger" icon="x">
            Danger
          </Button>
          <Button variant="primary" loading>
            Saving
          </Button>
          <Button size="sm" iconRight="chevron-down">
            Small
          </Button>
          <Button size="lg" variant="primary">
            Large
          </Button>
          <IconButton icon="bell" label="Alerts" />
          <IconButton icon="sliders" label="Settings" variant="secondary" />
        </div>
      </Section>

      <FormsSection />

      <Section title="Tabs">
        <TabsDemo />
      </Section>

      <TableSection />
      <ChartsSection />
      <RackSection />
      <OverlaysSection />
      <ShellSection />

      <Section title="States: Skeleton, Spinner, EmptyState, ErrorBoundary">
        <div className="grid gap-4 md:grid-cols-3">
          <SkeletonCard />
          <GlassCard>
            <Skeleton lines={4} label="Loading text" />
            <div className="mt-4 text-accent">
              <Spinner label="Loading…" />
            </div>
          </GlassCard>
          <GlassCard padding="none">
            <EmptyState
              title="No servers match"
              description="Try another filter."
              action={<Button size="sm">Clear filters</Button>}
            />
          </GlassCard>
          <ErrorBoundaryDemo />
        </div>
      </Section>

      <Section title="Icons">
        <div className="flex flex-wrap gap-3 text-text-muted">
          {iconNames.map((n) => (
            <span
              key={n}
              title={n}
              className="glass-subtle inline-flex h-9 w-9 items-center justify-center rounded-md"
            >
              <Icon name={n} size={18} />
            </span>
          ))}
        </div>
      </Section>
    </>
  );
}

function TokensSection() {
  return (
    <Section title="Tokens">
      <div className="grid gap-4 lg:grid-cols-3">
        <GlassCard title="Brand (jade)">
          <div className="flex overflow-hidden rounded-lg">
            {Object.entries(brand).map(([k, v]) => (
              <div key={k} className="h-10 flex-1" style={{ backgroundColor: v }} title={`${k} ${v}`} />
            ))}
          </div>
          <div className="mt-1 flex justify-between font-mono text-[10px] text-text-subtle">
            <span>50</span>
            <span>500</span>
            <span>950</span>
          </div>
        </GlassCard>
        <GlassCard title="Health (reserved)">
          <div className="flex flex-col gap-2">
            {healthStates.map((h) => (
              <div key={h} className="flex items-center justify-between">
                <HealthBadge health={h} />
                <span className="font-mono text-[11px] text-text-subtle">
                  {health[h].dark} / {health[h].light}
                </span>
              </div>
            ))}
          </div>
        </GlassCard>
        <GlassCard title="Chart palette (fixed order)">
          {(['dark', 'light'] as const).map((t) => (
            <div key={t} className="mb-2 flex items-center gap-2">
              <span className="w-10 text-xs text-text-subtle">{t}</span>
              <div className="flex flex-1 gap-1">
                {chartPalette[t].map((c, i) => (
                  <div
                    key={c}
                    className="h-6 flex-1 rounded"
                    style={{ backgroundColor: c }}
                    title={`${i + 1}: ${c}`}
                  />
                ))}
              </div>
            </div>
          ))}
        </GlassCard>
      </div>
    </Section>
  );
}

function FormsSection() {
  const [model, setModel] = useState<string | null>('r750');
  const [notify, setNotify] = useState(true);
  return (
    <Section title="Forms: FormField, inputs, Select, Combobox, Switch">
      <GlassCard className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <FormField label="BMC address" hint="Host, host:port or https:// URL" required>
          <TextInput placeholder="10.20.1.15" />
        </FormField>
        <FormField label="Rack position" error="Position 41 overlaps pnq1-srv-001 (U40–U41)">
          <NumberInput defaultValue={41} unit="U" />
        </FormField>
        <FormField label="Inlet warning threshold">
          <NumberInput defaultValue={27} unit="°C" step={0.5} />
        </FormField>
        <FormField label="Collector">
          <Select
            placeholder="Choose a collector"
            options={[
              { value: 'pnq1-col-a', label: 'pnq1-col-a' },
              { value: 'pnq1-col-b', label: 'pnq1-col-b' },
              { value: 'hyd1-col-a', label: 'hyd1-col-a' },
            ]}
          />
        </FormField>
        <FormField label="Model">
          <Combobox
            value={model}
            onChange={setModel}
            options={[
              { value: 'r750', label: 'PowerEdge R750', description: 'Dell' },
              { value: 'dl380', label: 'ProLiant DL380 Gen10', description: 'HPE' },
              { value: 'sr650', label: 'ThinkSystem SR650 V3', description: 'Lenovo' },
            ]}
          />
        </FormField>
        <FormField label="Reason">
          <TextArea placeholder="Planned PSU replacement" />
        </FormField>
        <div className="flex flex-col gap-3">
          <Checkbox label="Mute alerts during the window" defaultChecked />
          <Switch
            checked={notify}
            onChange={setNotify}
            label="Notify on-call"
            description="Email and Teams"
          />
        </div>
      </GlassCard>
    </Section>
  );
}

function TabsDemo() {
  const [tab, setTab] = useState('sensors');
  return (
    <Tabs
      label="Server detail"
      value={tab}
      onChange={setTab}
      tabs={[
        { id: 'sensors', label: 'Sensors' },
        { id: 'health', label: 'Health', badge: <HealthBadge health="Warning" size="sm" /> },
        { id: 'inventory', label: 'Inventory' },
        { id: 'firmware', label: 'Firmware' },
        { id: 'events', label: 'Events', disabled: true },
      ]}
    >
      {(active) => <GlassCard tone="subtle">Panel: {active}</GlassCard>}
    </Tabs>
  );
}

function TableSection() {
  const [rows, setRows] = useState<SampleServer[]>(() => makeServers(8));
  const [sort, setSort] = useState<SortState | null>({ id: 'name', direction: 'asc' });
  const [loadingMore, setLoadingMore] = useState(false);
  const [state, setState] = useState<'data' | 'loading' | 'empty' | 'error'>('data');
  const toast = useToast();

  // The real table is server-sorted; the gallery fakes it client-side.
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const key = sort.id as keyof SampleServer;
    const dir = sort.direction === 'asc' ? 1 : -1;
    return [...rows].sort((a, b) => (a[key] > b[key] ? dir : a[key] < b[key] ? -dir : 0));
  }, [rows, sort]);

  const columns: Column<SampleServer>[] = [
    {
      id: 'name',
      header: 'Server',
      sortable: true,
      cell: (r) => <span className="font-medium text-text">{r.name}</span>,
      hideable: false,
    },
    {
      id: 'health',
      header: 'Health',
      sortable: true,
      cell: (r) => <HealthBadge health={r.health} size="sm" />,
    },
    { id: 'site', header: 'Site', sortable: true, cell: (r) => r.site },
    { id: 'rack', header: 'Rack', cell: (r) => r.rack },
    { id: 'model', header: 'Model', cell: (r) => `${r.vendor} ${r.model}`, defaultHidden: true },
    {
      id: 'inlet',
      header: 'Inlet',
      align: 'right',
      sortable: true,
      cell: (r) => <Reading value={r.inlet} unit="°C" time={r.seen} layout="stacked" />,
    },
    {
      id: 'power',
      header: 'Power',
      align: 'right',
      sortable: true,
      cell: (r) => <Reading value={r.power} unit="W" time={r.seen} layout="value" />,
    },
  ];

  return (
    <Section title="DataTable — server sort, load more, column picker, states">
      <div className="mb-3 flex flex-wrap gap-2">
        {(['data', 'loading', 'empty', 'error'] as const).map((s) => (
          <Button
            key={s}
            size="sm"
            variant={state === s ? 'primary' : 'secondary'}
            onClick={() => setState(s)}
          >
            {s}
          </Button>
        ))}
      </div>
      <DataTable
        caption="Sample servers"
        columns={columns}
        rows={state === 'data' ? sorted : []}
        getRowId={(r) => r.id}
        sort={sort}
        onSortChange={setSort}
        loading={state === 'loading'}
        error={
          state === 'error'
            ? new ApiError({
                type: 'about:blank',
                title: 'Service unavailable',
                status: 503,
                detail: 'The app API is not reachable.',
              })
            : undefined
        }
        onRetry={() => setState('data')}
        hasMore={state === 'data' && rows.length < 30}
        loadingMore={loadingMore}
        onLoadMore={() => {
          setLoadingMore(true);
          setTimeout(() => {
            setRows((r) => [...r, ...makeServers(8, r.length)]);
            setLoadingMore(false);
          }, 600);
        }}
        onRowClick={(r) => toast.toast({ title: `Open ${r.name}`, tone: 'info' })}
        rowLabel={(r) => `Open ${r.name}`}
        emptyTitle="No servers match these filters"
        summary={state === 'data' ? `${rows.length} of 30` : undefined}
        maxHeight="24rem"
        toolbar={<span className="text-sm text-text-muted">Inventory (sample)</span>}
      />
    </Section>
  );
}

function ChartsSection() {
  const [inlet, setInlet] = useState(inletSeries);
  const [fans, setFans] = useState(fanSeries);
  const [live, setLive] = useState(true);
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => {
      setInlet((s) => appendPoint(s, 0.8));
      setFans((s) => appendPoint(s, 120));
    }, 3000);
    return () => clearInterval(t);
  }, [live]);

  return (
    <Section title="SensorChart — multi-series, unit axis, thresholds, live update">
      <div className="mb-3">
        <Switch checked={live} onChange={setLive} label="Append a point every 3 s" />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <GlassCard>
          <SensorChart
            title="Temperatures (24 h)"
            unit="°C"
            series={inlet}
            thresholds={[
              { value: 27, severity: 'warning', label: 'Inlet warning' },
              { value: 35, severity: 'critical', label: 'Inlet critical' },
            ]}
          />
        </GlassCard>
        <GlassCard>
          <SensorChart
            title="Fan speed"
            unit="RPM"
            series={fans}
            thresholds={[{ value: 3000, severity: 'critical', label: 'Lower critical' }]}
            yMin={0}
          />
        </GlassCard>
        <GlassCard>
          <SensorChart title="Loading" unit="W" series={[]} loading />
        </GlassCard>
        <GlassCard>
          <SensorChart title="No data" unit="W" series={[{ id: 'p', name: 'Power', points: [] }]} />
        </GlassCard>
      </div>
    </Section>
  );
}

function RackSection() {
  const [selected, setSelected] = useState<RackServer | null>(null);
  return (
    <Section title="RackView — SVG elevation">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,420px)_1fr]">
        <GlassCard title="PNQ1 · Hall A · R03 (42 U)">
          <RackView
            name="R03"
            heightU={42}
            servers={rackServers}
            onServerClick={setSelected}
            selectedId={selected?.id ?? null}
          />
        </GlassCard>
        <GlassCard title="Selected">
          {selected ? (
            <div className="flex flex-col gap-2 text-sm">
              <span className="font-semibold text-text">{selected.name}</span>
              <HealthBadge health={selected.health} />
              <Reading value={selected.inletTempC ?? null} unit="°C" time={selected.inletTime ?? null} />
            </div>
          ) : (
            <EmptyState
              icon="rack"
              title="Click a server"
              description="Or focus one with Tab and press Enter."
            />
          )}
        </GlassCard>
      </div>
    </Section>
  );
}

function OverlaysSection() {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const { toast } = useToast();
  return (
    <Section title="ConfirmDialog, Drawer, Toasts (portaled: use the page theme)">
      <div className="flex flex-wrap gap-3">
        <Button variant="danger" onClick={() => setConfirm(true)}>
          Resolve alert…
        </Button>
        <Button onClick={() => setDrawer(true)} icon="chevron-left">
          Open drawer
        </Button>
        <Button
          onClick={() =>
            toast({
              title: 'Alert acknowledged',
              description: 'Inlet temperature on pnq1-srv-005',
              tone: 'success',
            })
          }
        >
          Success toast
        </Button>
        <Button
          onClick={() =>
            toast({
              title: 'Couldn’t save threshold',
              description: 'Warning must be below critical.',
              tone: 'error',
            })
          }
        >
          Error toast
        </Button>
        <Button
          onClick={() =>
            toast({
              title: 'Collector pnq1-col-b is back',
              tone: 'info',
              action: { label: 'View', onClick: () => undefined },
            })
          }
        >
          Info toast
        </Button>
        <Button onClick={() => toast({ title: 'Maintenance window starts in 10 min', tone: 'warning' })}>
          Warning toast
        </Button>
      </div>
      <ConfirmDialog
        open={confirm}
        title="Resolve this alert?"
        description="It will close for everyone and re-open if the reading is still bad."
        confirmLabel="Resolve"
        tone="danger"
        busy={busy}
        onCancel={() => setConfirm(false)}
        onConfirm={() => {
          setBusy(true);
          setTimeout(() => {
            setBusy(false);
            setConfirm(false);
            toast({ title: 'Alert resolved', tone: 'success' });
          }, 800);
        }}
      />
      <Drawer
        open={drawer}
        onClose={() => setDrawer(false)}
        title="Edit server"
        description="pnq1-srv-003"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDrawer(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={() => setDrawer(false)}>
              Save
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <FormField label="Rack position">
            <NumberInput defaultValue={36} unit="U" />
          </FormField>
          <FormField label="Status">
            <Select
              options={[
                { value: 'active', label: 'Active' },
                { value: 'maintenance', label: 'Maintenance' },
              ]}
            />
          </FormField>
        </div>
      </Drawer>
    </Section>
  );
}

function ShellSection() {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <Section title="Shell: sidebar, search, site filter, live, alerts bell, theme, user menu">
      <div className="flex flex-col gap-4 lg:flex-row">
        <Sidebar embedded collapsed={collapsed} onToggleCollapsed={() => setCollapsed((c) => !c)} />
        <div className="flex flex-1 flex-col gap-4">
          <GlassCard className="flex flex-wrap items-center gap-2">
            <GlobalSearch search={sampleSearch} className="flex-1" />
            <SiteFilter className="flex" />
            <LiveIndicator status="open" />
            <AlertsBell />
            <ThemeToggle />
            <UserMenu />
          </GlassCard>
          <GlassCard className="flex flex-wrap items-center gap-4">
            <LiveIndicator status="open" />
            <LiveIndicator status="reconnecting" />
            <LiveIndicator status="closed" />
            <AlertsBell count={0} />
            <AlertsBell count={3} critical={0} />
            <AlertsBell count={120} critical={4} />
          </GlassCard>
          <GlassCard>
            <PageHeader
              title="pnq1-srv-005"
              subtitle="Dell PowerEdge R650 · PNQ1 · Hall A · R03 · U32"
              badge={<HealthBadge health="Critical" />}
              breadcrumbs={[
                { label: 'Overview', to: '/' },
                { label: 'PNQ1', to: '/sites/1' },
                { label: 'R03', to: '/racks/3' },
                { label: 'pnq1-srv-005' },
              ]}
              actions={
                <>
                  <Button icon="refresh">Refresh</Button>
                  <Button variant="primary" icon="external-link">
                    Open BMC
                  </Button>
                </>
              }
              className="mb-0"
            />
          </GlassCard>
          <p className="text-sm text-text-muted">
            Wall mode (full-screen NOC overview) is at <code className="font-mono">/wall</code> (signed in).
          </p>
        </div>
      </div>
    </Section>
  );
}

function Boom(): ReactNode {
  throw new Error('Sample render error from the gallery');
}

function ErrorBoundaryDemo() {
  const [boom, setBoom] = useState(false);
  return (
    <div className="md:col-span-2">
      <ErrorBoundary resetKeys={[boom]}>
        {boom ? (
          <Boom />
        ) : (
          <GlassCard className="flex items-center justify-between">
            <span className="text-sm text-text-muted">ErrorBoundary around a widget</span>
            <Button size="sm" variant="danger" onClick={() => setBoom(true)}>
              Throw
            </Button>
          </GlassCard>
        )}
      </ErrorBoundary>
      {boom ? (
        <Button size="sm" className="mt-2" onClick={() => setBoom(false)}>
          Reset demo
        </Button>
      ) : null}
    </div>
  );
}
