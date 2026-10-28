import { NavLink } from 'react-router-dom';

import { useAuth } from '@/auth/AuthProvider';
import { cn } from '@/lib/cn';
import { healthClasses, normalizeHealth } from '@/lib/health';

import { Icon } from '../Icon';
import { Logo } from './Logo';
import { visibleNav } from './nav';
import { useShell } from './ShellContext';

export interface SidebarProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  /** Mobile/tablet overlay mode. */
  mobileOpen?: boolean;
  onNavigate?: () => void;
  /** Render in normal flow (component gallery) instead of fixed to the viewport. */
  embedded?: boolean;
}

export function Sidebar({ collapsed, onToggleCollapsed, mobileOpen, onNavigate, embedded }: SidebarProps) {
  const { hasRole } = useAuth();
  const { sites } = useShell();
  const items = visibleNav(hasRole);
  const narrow = collapsed && !mobileOpen;

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-fast',
      narrow && 'justify-center px-0',
      isActive ? 'bg-accent/15 text-text' : 'text-text-muted hover:bg-text/5 hover:text-text',
    );

  return (
    <aside
      aria-label="Main"
      className={cn(
        'glass flex flex-col transition-[width,transform] duration-base ease-standard',
        embedded
          ? 'relative h-[30rem] rounded-xl'
          : 'fixed inset-y-0 left-0 z-sidebar rounded-none border-y-0 border-l-0',
        narrow ? 'w-[4.25rem]' : 'w-60',
        !embedded && (mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'),
      )}
    >
      <div className={cn('flex h-16 items-center px-4', narrow && 'justify-center px-0')}>
        <NavLink to="/" onClick={onNavigate} className="rounded-md" aria-label="Jade GCC home">
          <Logo compact={narrow} />
        </NavLink>
      </div>

      <nav aria-label="Primary" className="flex-1 overflow-y-auto px-3 pb-3">
        <ul className="flex flex-col gap-1">
          {items.map((it) => (
            <li key={it.to}>
              <NavLink
                to={it.to}
                end={it.end}
                onClick={onNavigate}
                className={linkClass}
                title={narrow ? it.label : undefined}
              >
                {({ isActive }) => (
                  <>
                    {isActive ? (
                      <span
                        aria-hidden="true"
                        className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-accent"
                      />
                    ) : null}
                    <Icon name={it.icon} size={18} className={isActive ? 'text-accent' : undefined} />
                    <span className={cn(narrow && 'sr-only')}>{it.label}</span>
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>

        {sites.length > 0 ? (
          <div className="mt-6">
            <p
              className={cn(
                'mb-2 px-3 text-[11px] font-semibold uppercase tracking-wider text-text-subtle',
                narrow && 'sr-only',
              )}
            >
              Sites
            </p>
            <ul className="flex flex-col gap-0.5">
              {sites.map((s) => {
                const h = normalizeHealth(s.health);
                return (
                  <li key={s.id}>
                    <NavLink
                      to={`/sites/${s.id}`}
                      onClick={onNavigate}
                      className={linkClass}
                      title={narrow ? `${s.code} · ${h}` : undefined}
                    >
                      <span
                        className={cn('h-2 w-2 shrink-0 rounded-full', healthClasses[h].dot)}
                        aria-hidden="true"
                      />
                      <span className={cn('flex-1 truncate', narrow && 'sr-only')}>
                        {s.code} <span className="text-text-subtle">· {s.name}</span>
                      </span>
                      {!narrow ? (
                        <span className={cn('text-[11px]', healthClasses[h].text)}>{h}</span>
                      ) : (
                        <span className="sr-only">{h}</span>
                      )}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </nav>

      <div className={cn('border-t hairline p-3', !embedded && 'hidden lg:block')}>
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
          className={cn(
            'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-text-muted hover:bg-text/5 hover:text-text',
            narrow && 'justify-center px-0',
          )}
        >
          <Icon name={collapsed ? 'chevrons-right' : 'chevrons-left'} size={18} />
          <span className={cn(narrow && 'sr-only')}>Collapse</span>
        </button>
      </div>
    </aside>
  );
}
