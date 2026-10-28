import { Link } from 'react-router-dom';

import { useLiveStatus } from '@/api/LiveProvider';
import type { LiveStatus } from '@/api/live';
import { useAuth } from '@/auth/AuthProvider';
import { ROLE_LABELS } from '@/auth/roles';
import { useDemoMode } from '@/demo/demoMode';
import { cn } from '@/lib/cn';
import { useTheme } from '@/theme/ThemeProvider';

import { IconButton } from '../Button';
import { Switch } from '../FormField';
import { Icon } from '../Icon';
import { MenuItem, Popover } from '../Popover';
import { GlobalSearch } from './GlobalSearch';
import { useShell, useSiteFilter } from './ShellContext';

export function TopBar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const { search } = useShell();
  return (
    <header className="glass sticky top-0 z-topbar flex h-16 items-center gap-3 rounded-none border-x-0 border-t-0 px-4 sm:px-6">
      <IconButton icon="menu" label="Open navigation" className="lg:hidden" onClick={onOpenMenu} />
      <GlobalSearch search={search} className="flex-1" />
      <div className="ml-auto flex items-center gap-1.5">
        <DemoBadge />
        <SiteFilter />
        <LiveIndicator />
        <AlertsBell />
        <ThemeToggle />
        <UserMenu />
      </div>
    </header>
  );
}

/** Global site filter (empty = all sites). Native select keeps it simple and accessible. */
export function SiteFilter({ className }: { className?: string }) {
  const { siteIds, setSiteIds, sites } = useSiteFilter();
  if (sites.length < 2) return null;
  const value = siteIds.length === 1 ? String(siteIds[0]) : '';
  return (
    <label className={cn('relative hidden items-center md:flex', className)}>
      <span className="sr-only">Site filter</span>
      <Icon name="building" size={14} className="pointer-events-none absolute left-2.5 text-text-subtle" />
      <select
        value={value}
        onChange={(e) => setSiteIds(e.target.value ? [Number(e.target.value)] : [])}
        className="h-9 appearance-none rounded-lg border border-text/10 bg-text/5 pl-8 pr-8 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
      >
        <option value="">All sites</option>
        {sites.map((s) => (
          <option key={s.id} value={s.id}>
            {s.code} · {s.name}
          </option>
        ))}
      </select>
      <Icon
        name="chevron-down"
        size={14}
        className="pointer-events-none absolute right-2.5 text-text-subtle"
      />
    </label>
  );
}

const liveText: Record<LiveStatus, { word: string; cls: string }> = {
  open: { word: 'Live', cls: 'bg-health-ok' },
  connecting: { word: 'Connecting', cls: 'bg-health-warning' },
  authenticating: { word: 'Connecting', cls: 'bg-health-warning' },
  reconnecting: { word: 'Reconnecting', cls: 'bg-health-warning' },
  closed: { word: 'Offline', cls: 'bg-health-unknown' },
  idle: { word: 'Offline', cls: 'bg-health-unknown' },
};

/** Shown while demo mode is on; links to the switch in Settings. */
export function DemoBadge({ className }: { className?: string }) {
  const demo = useDemoMode();
  if (!demo) return null;
  return (
    <Link
      to="/settings"
      title="Demo mode is on: the app shows sample data. Click to change."
      className={cn(
        'inline-flex shrink-0 items-center gap-1.5 rounded-full bg-health-warning/15 px-2.5 py-1 text-xs font-semibold text-health-warning ring-1 ring-inset ring-health-warning/40 hover:bg-health-warning/25',
        className,
      )}
    >
      <Icon name="flask" size={14} />
      <span>
        Demo data<span className="sr-only">: demo mode is on, open settings</span>
      </span>
    </Link>
  );
}

/** Live-updates connection state (word + color). */
export function LiveIndicator({ status: forced }: { status?: LiveStatus }) {
  const actual = useLiveStatus();
  const status = forced ?? actual;
  const t = liveText[status];
  return (
    <span
      role="status"
      className="hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium text-text-muted sm:inline-flex"
      title="Live updates connection"
    >
      <span className="relative flex h-2 w-2">
        {status === 'open' ? (
          <span className={cn('absolute inline-flex h-full w-full animate-pulse-ring rounded-full', t.cls)} />
        ) : null}
        <span className={cn('relative inline-flex h-2 w-2 rounded-full', t.cls)} />
      </span>
      {t.word}
    </span>
  );
}

export function AlertsBell({
  count: forcedCount,
  critical: forcedCritical,
}: {
  count?: number;
  critical?: number;
}) {
  const { openAlerts } = useShell();
  const count = forcedCount ?? openAlerts?.count ?? null;
  const critical = forcedCritical ?? openAlerts?.critical ?? 0;
  const label =
    count === null ? 'Alerts' : `Alerts: ${count} open${critical ? `, ${critical} critical` : ''}`;
  return (
    <Link
      to="/alerts"
      aria-label={label}
      title={label}
      className="relative inline-flex h-9 w-9 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-text/5 hover:text-text"
    >
      <Icon name="bell" size={18} />
      {count ? (
        <span
          aria-hidden="true"
          className={cn(
            'tabular absolute -right-0.5 -top-0.5 min-w-[1.125rem] rounded-full px-1 text-center text-[10px] font-bold leading-[1.125rem]',
            critical ? 'bg-health-critical text-canvas' : 'bg-health-warning text-canvas',
          )}
        >
          {count > 99 ? '99+' : count}
        </span>
      ) : null}
    </Link>
  );
}

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const next = theme === 'dark' ? 'light' : 'dark';
  return (
    <IconButton
      icon={theme === 'dark' ? 'sun' : 'moon'}
      label={`Switch to ${next} theme`}
      onClick={toggleTheme}
    />
  );
}

export function UserMenu() {
  const { user, signOut } = useAuth();
  const { reduceTransparency, setReduceTransparency } = useTheme();
  if (!user) return null;
  const initials = user.name
    .split(/\s+/)
    .map((p) => p[0] ?? '')
    .join('')
    .slice(0, 2)
    .toUpperCase();
  return (
    <Popover
      kind="dialog"
      label="Account"
      className="w-72 p-0"
      trigger={(p) => (
        <button
          {...p}
          type="button"
          aria-label={`Account: ${user.name}`}
          className="ml-1 inline-flex h-9 w-9 items-center justify-center rounded-full bg-accent/20 text-xs font-semibold text-accent ring-1 ring-accent/40 hover:bg-accent/30"
        >
          {initials || <Icon name="user" size={16} />}
        </button>
      )}
    >
      {(close) => (
        <div>
          <div className="border-b hairline p-4">
            <p className="truncate text-sm font-semibold text-text">{user.name}</p>
            <p className="truncate text-xs text-text-muted">{user.email ?? user.username}</p>
            <div className="mt-2 flex flex-wrap gap-1">
              {user.roles.length ? (
                user.roles.map((r) => (
                  <span
                    key={r}
                    className="rounded-full bg-accent/15 px-2 py-0.5 text-[11px] font-medium text-accent"
                  >
                    {ROLE_LABELS[r]}
                  </span>
                ))
              ) : (
                <span className="text-xs text-health-warning">No app role assigned</span>
              )}
            </div>
            <p className="mt-2 text-xs text-text-subtle">
              Sites: {user.sites.length ? user.sites.join(', ') : 'all sites'}
            </p>
          </div>
          <div className="border-b hairline p-4">
            <Switch
              checked={reduceTransparency}
              onChange={setReduceTransparency}
              label="Reduce transparency"
              description="Solid surfaces instead of glass."
            />
          </div>
          <div className="p-1.5" role="menu" aria-label="Account actions">
            <MenuItem
              danger
              icon={<Icon name="log-out" size={16} />}
              onSelect={() => {
                close();
                void signOut();
              }}
            >
              Sign out
            </MenuItem>
          </div>
        </div>
      )}
    </Popover>
  );
}
