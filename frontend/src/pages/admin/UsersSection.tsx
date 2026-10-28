import { useCursorList } from '@/api/hooks';
import type { User } from '@/api/types';
import { Pill } from '@/components/Badges';
import { type Column } from '@/components/DataTable';
import { FormField, TextInput } from '@/components/FormField';
import { Age } from '@/components/Reading';
import { formatTimestamp } from '@/lib/format';
import { useDebouncedValue } from '@/lib/useDebouncedValue';
import { useUrlState } from '@/lib/useUrlState';

import { CrudList, FilterSelect, Hint } from './crud';

const ROLE_LABEL: Record<string, string> = {
  platform_admin: 'Platform admin',
  dc_engineer: 'DC engineer',
  noc_operator: 'NOC operator',
  analyst: 'Analyst',
  viewer: 'Viewer',
};
const ROLE_OPTIONS = Object.entries(ROLE_LABEL).map(([value, label]) => ({ value, label }));
const NEUTRAL = 'text-text-muted bg-text/5 ring-1 ring-inset ring-text/15';
const ACCENT = 'text-accent bg-accent/10 ring-1 ring-inset ring-accent/30';

const columns: Column<User>[] = [
  {
    id: 'name',
    header: 'Name',
    cell: (u) => (
      <span className="flex flex-col">
        <span className="font-medium">{u.name}</span>
        <span className="text-xs text-text-subtle">{u.email ?? u.sub}</span>
      </span>
    ),
  },
  {
    id: 'roles',
    header: 'Roles',
    cell: (u) =>
      u.roles.length ? (
        <span className="flex flex-wrap gap-1">
          {u.roles.map((r) => (
            <Pill key={r} className={r === 'platform_admin' ? ACCENT : NEUTRAL}>
              {ROLE_LABEL[r] ?? r}
            </Pill>
          ))}
        </span>
      ) : (
        <span className="text-text-subtle">None</span>
      ),
  },
  {
    id: 'sites',
    header: 'Sites',
    cell: (u) => (u.sites && u.sites.length ? u.sites.join(', ') : 'All sites'),
  },
  {
    id: 'last_login',
    header: 'Last sign-in',
    cell: (u) =>
      u.last_login_at ? (
        <span title={formatTimestamp(u.last_login_at)}>
          <Age time={u.last_login_at} />
        </span>
      ) : (
        <span className="text-text-subtle">Never</span>
      ),
  },
  {
    id: 'created',
    header: 'First seen',
    cell: (u) => <span className="tabular whitespace-nowrap">{formatTimestamp(u.created_at)}</span>,
  },
];

/** Read-only: people, roles and sites come from SSO groups and are refreshed at each sign-in. */
export default function UsersSection() {
  const [f, setF] = useUrlState({ q: '', role: '' });
  const q = useDebouncedValue(f.q.trim(), 300);
  const list = useCursorList<User>('/api/v1/users', { q: q || undefined, role: f.role || undefined });

  return (
    <CrudList<User, never>
      title="Users"
      noun="user"
      caption="Users"
      intro="Everyone who has signed in, with the roles and sites from their SSO groups at their last sign-in."
      columns={columns}
      table={list.tableProps}
      getRowId={(u) => u.id}
      rowName={(u) => u.name}
      invalidate={['users']}
      canEdit={false}
      toolbar={
        <>
          <FormField label="Search users" hideLabel className="w-56">
            <TextInput
              type="search"
              placeholder="Name, email or ID…"
              value={f.q}
              onChange={(e) => setF({ q: e.target.value })}
            />
          </FormField>
          <FilterSelect
            label="Role"
            value={f.role}
            onChange={(v) => setF({ role: v })}
            options={ROLE_OPTIONS}
            placeholder="All roles"
          />
        </>
      }
      emptyTitle="No users"
      emptyDescription={q || f.role ? 'No one matches the filters.' : 'Nobody has signed in yet.'}
      persistKey="admin-users"
    >
      <Hint>
        Roles and site limits are managed in SSO: add people to the{' '}
        <span className="font-mono">gcc-&lt;role&gt;</span> and{' '}
        <span className="font-mono">gcc-site-&lt;CODE&gt;</span> groups. Changes apply at their next sign-in.
      </Hint>
    </CrudList>
  );
}
