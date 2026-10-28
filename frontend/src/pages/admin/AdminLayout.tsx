import { Outlet } from 'react-router-dom';

import { useAuth } from '@/auth/AuthProvider';
import { PageHeader } from '@/components/PageHeader';
import { NavTabs } from '@/components/Tabs';

import { ADMIN_SECTIONS } from './sections';

export default function AdminLayout() {
  const { hasRole } = useAuth();
  const sections = ADMIN_SECTIONS.filter((s) => hasRole(s.minRole));
  return (
    <>
      <PageHeader title="Admin" subtitle="Assets, collectors, alerting and access" />
      <NavTabs
        label="Admin sections"
        items={sections.map((s) => ({ to: `/admin/${s.path}`, label: s.label }))}
        className="mb-6"
      />
      <Outlet />
    </>
  );
}
