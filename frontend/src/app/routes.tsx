import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from 'react';
import { Outlet, Route, Routes } from 'react-router-dom';

import { RequireAuth, RequireRole } from '@/auth/guards';
import { AppShell } from '@/components/shell/AppShell';
import { ShellProvider } from '@/components/shell/ShellContext';
import { FullPageSpinner, Spinner } from '@/components/Spinner';
import { ADMIN_SECTIONS, AdminIndex } from '@/pages/admin/sections';

import { useShellData } from './useShellData';

const LoginPage = lazy(() => import('@/pages/LoginPage'));
const AuthCallbackPage = lazy(() => import('@/pages/AuthCallbackPage'));
const OverviewPage = lazy(() => import('@/pages/OverviewPage'));
const WallPage = lazy(() => import('@/pages/WallPage'));
const SitePage = lazy(() => import('@/pages/SitePage'));
const RackPage = lazy(() => import('@/pages/RackPage'));
const ServerPage = lazy(() => import('@/pages/ServerPage'));
const AlertsPage = lazy(() => import('@/pages/AlertsPage'));
const InventoryPage = lazy(() => import('@/pages/InventoryPage'));
const FirmwarePage = lazy(() => import('@/pages/FirmwarePage'));
const AnalyticsPage = lazy(() => import('@/pages/AnalyticsPage'));
const AdminLayout = lazy(() => import('@/pages/admin/AdminLayout'));
const AdminSectionPage = lazy(() => import('@/pages/admin/AdminSectionPage'));
const AuditPage = lazy(() => import('@/pages/AuditPage'));
const SettingsPage = lazy(() => import('@/pages/SettingsPage'));
const NotFoundPage = lazy(() => import('@/pages/NotFoundPage'));

// Dev-only component gallery: the import is dropped from production builds.
const GalleryPage: LazyExoticComponent<ComponentType> | null = import.meta.env.DEV
  ? lazy(() => import('@/pages/dev/GalleryPage'))
  : null;

function PageFallback() {
  return (
    <div className="flex justify-center py-16 text-accent">
      <Spinner size={22} label="Loading…" />
    </div>
  );
}

/** Signed-in area: shell data (sites, search, alert count) shared by the shell and wall mode. */
function AuthedRoot() {
  const data = useShellData();
  return (
    <ShellProvider data={data}>
      <Outlet />
    </ShellProvider>
  );
}

function ShellRoute() {
  return <AppShell />;
}

/**
 * Route table (PLAN Phase 6 screens):
 *   /login, /auth/callback, /wall, /, /sites/:siteId, /racks/:rackId, /servers/:serverId, /alerts,
 *   /inventory, /firmware, /analytics[/:slug], /admin/<section> (DC engineer+, some admin only),
 *   /audit (platform admin), /settings (everyone: demo mode, appearance), /dev/gallery (dev builds only).
 */
export function AppRoutes() {
  return (
    <Suspense fallback={<FullPageSpinner />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/auth/callback" element={<AuthCallbackPage />} />
        {GalleryPage ? <Route path="/dev/gallery" element={<GalleryPage />} /> : null}

        <Route element={<RequireAuth />}>
          <Route element={<AuthedRoot />}>
            <Route path="/wall" element={<WallPage />} />
            <Route element={<ShellRoute />}>
              <Route
                element={
                  <Suspense fallback={<PageFallback />}>
                    <Outlet />
                  </Suspense>
                }
              >
                <Route index element={<OverviewPage />} />
                <Route path="sites/:siteId" element={<SitePage />} />
                <Route path="racks/:rackId" element={<RackPage />} />
                <Route path="servers/:serverId" element={<ServerPage />} />
                <Route path="alerts" element={<AlertsPage />} />
                <Route path="inventory" element={<InventoryPage />} />
                <Route path="firmware" element={<FirmwarePage />} />
                <Route path="analytics" element={<AnalyticsPage />} />
                <Route path="analytics/:slug" element={<AnalyticsPage />} />
                <Route
                  path="admin"
                  element={
                    <RequireRole role="dc_engineer">
                      <AdminLayout />
                    </RequireRole>
                  }
                >
                  <Route index element={<AdminIndex />} />
                  {ADMIN_SECTIONS.map((s) => (
                    <Route
                      key={s.path}
                      path={s.path}
                      element={
                        <RequireRole role={s.minRole}>
                          <AdminSectionPage section={s} />
                        </RequireRole>
                      }
                    />
                  ))}
                </Route>
                <Route
                  path="audit"
                  element={
                    <RequireRole role="platform_admin">
                      <AuditPage />
                    </RequireRole>
                  }
                />
                <Route path="settings" element={<SettingsPage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Route>
            </Route>
          </Route>
        </Route>
      </Routes>
    </Suspense>
  );
}
