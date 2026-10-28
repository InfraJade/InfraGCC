import { motion } from 'framer-motion';
import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { NavLink } from 'react-router-dom';

import { cn } from '@/lib/cn';

export interface TabItem {
  id: string;
  label: ReactNode;
  badge?: ReactNode;
  disabled?: boolean;
}

export interface TabsProps {
  tabs: TabItem[];
  value: string;
  onChange: (id: string) => void;
  /** Accessible name of the tab list. */
  label: string;
  /** Render the active panel; receives the active id. */
  children?: (active: string) => ReactNode;
  className?: string;
}

/** Controlled tabs (WAI-ARIA tabs pattern: roving tabindex, arrows/Home/End, automatic activation). */
export function Tabs({ tabs, value, onChange, label, children, className }: TabsProps) {
  const base = useId();
  const listRef = useRef<HTMLDivElement>(null);
  const enabled = tabs.filter((t) => !t.disabled);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = enabled.findIndex((t) => t.id === value);
    let next: TabItem | undefined;
    if (e.key === 'ArrowRight') next = enabled[(i + 1) % enabled.length];
    else if (e.key === 'ArrowLeft') next = enabled[(i - 1 + enabled.length) % enabled.length];
    else if (e.key === 'Home') next = enabled[0];
    else if (e.key === 'End') next = enabled[enabled.length - 1];
    if (!next) return;
    e.preventDefault();
    onChange(next.id);
    listRef.current?.querySelector<HTMLElement>(`[data-tab-id="${CSS.escape(next.id)}"]`)?.focus();
  };

  return (
    <div className={className}>
      <div
        ref={listRef}
        role="tablist"
        aria-label={label}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className="glass-subtle inline-flex max-w-full gap-1 overflow-x-auto rounded-lg p-1"
      >
        {tabs.map((t) => {
          const selected = t.id === value;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`${base}-tab-${t.id}`}
              data-tab-id={t.id}
              aria-selected={selected}
              aria-controls={`${base}-panel-${t.id}`}
              tabIndex={selected ? 0 : -1}
              disabled={t.disabled}
              onClick={() => onChange(t.id)}
              className={cn(
                'relative inline-flex items-center gap-2 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors duration-fast disabled:opacity-40',
                selected ? 'text-text' : 'text-text-muted hover:text-text',
              )}
            >
              {selected ? (
                <motion.span
                  layoutId={`${base}-pill`}
                  className="absolute inset-0 rounded-md bg-text/10 shadow-sm"
                  transition={{ type: 'spring', bounce: 0.15, duration: 0.35 }}
                />
              ) : null}
              <span className="relative">{t.label}</span>
              {t.badge !== undefined ? <span className="relative">{t.badge}</span> : null}
            </button>
          );
        })}
      </div>
      {children ? (
        <div
          role="tabpanel"
          id={`${base}-panel-${value}`}
          aria-labelledby={`${base}-tab-${value}`}
          tabIndex={0}
          className="mt-4 outline-none"
        >
          {children(value)}
        </div>
      ) : null}
    </div>
  );
}

export interface NavTabItem {
  to: string;
  label: ReactNode;
  end?: boolean;
}

/** Route-driven sub-navigation styled like tabs (Admin sub-pages). Uses links, so it is a nav, not a tablist. */
export function NavTabs({
  items,
  label,
  className,
}: {
  items: NavTabItem[];
  label: string;
  className?: string;
}) {
  return (
    <nav
      aria-label={label}
      className={cn('glass-subtle inline-flex max-w-full gap-1 overflow-x-auto rounded-lg p-1', className)}
    >
      {items.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end={it.end}
          className={({ isActive }) =>
            cn(
              'whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors duration-fast',
              isActive ? 'bg-text/10 text-text shadow-sm' : 'text-text-muted hover:text-text',
            )
          }
        >
          {it.label}
        </NavLink>
      ))}
    </nav>
  );
}
