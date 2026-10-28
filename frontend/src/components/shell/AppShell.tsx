import { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';

import { cn } from '@/lib/cn';
import { readJson, writeJson } from '@/lib/storage';

import { ErrorBoundary } from '../ErrorBoundary';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

const COLLAPSE_KEY = 'gcc.sidebar.collapsed';

/** Signed-in layout: glass sidebar + top bar + routed page. */
export function AppShell() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() =>
    readJson(COLLAPSE_KEY, false, (v): v is boolean => typeof v === 'boolean'),
  );
  const [mobileOpen, setMobileOpen] = useState(false);

  const toggle = () =>
    setCollapsed((c) => {
      writeJson(COLLAPSE_KEY, !c);
      return !c;
    });

  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only-focusable fixed left-3 top-3 z-toast rounded-md bg-accent px-3 py-2 text-sm font-medium text-on-accent"
      >
        Skip to content
      </a>
      <Sidebar
        collapsed={collapsed}
        onToggleCollapsed={toggle}
        mobileOpen={mobileOpen}
        onNavigate={() => setMobileOpen(false)}
      />
      {mobileOpen ? (
        <div
          aria-hidden="true"
          className="fixed inset-0 z-[29] bg-scrim/40 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      ) : null}
      <div
        className={cn(
          'flex min-h-screen flex-col transition-[padding] duration-base ease-standard',
          collapsed ? 'lg:pl-[4.25rem]' : 'lg:pl-60',
        )}
      >
        <TopBar onOpenMenu={() => setMobileOpen(true)} />
        <main
          id="main"
          tabIndex={-1}
          className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 outline-none sm:px-6 lg:px-8"
        >
          <ErrorBoundary resetKeys={[location.pathname]}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
