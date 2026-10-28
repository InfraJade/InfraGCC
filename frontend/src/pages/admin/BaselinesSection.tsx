import { useCan, useCursorList } from '@/api/hooks';
import type { Baseline } from '@/api/types';
import { type Column } from '@/components/DataTable';
import { FormField, Select, TextArea, TextInput } from '@/components/FormField';
import { formatTimestamp } from '@/lib/format';
import { useUrlState } from '@/lib/useUrlState';

import { CrudList, FilterSelect, Hint, optText, type CrudForm, type FormErrors } from './crud';
import { useUnrestricted } from './pickers';

interface BaselineForm {
  vendor: string;
  model: string;
  /** One of COMPONENTS, or DRIVE (with drive_model). */
  component: string;
  drive_model: string;
  version: string;
  notes: string;
}

const VENDORS = ['Dell', 'HPE', 'Lenovo'];
const VENDOR_OPTIONS = VENDORS.map((v) => ({ value: v, label: v }));
const COMPONENTS = ['BIOS', 'BMC', 'CPLD', 'PSU', 'NIC', 'RAID'];
const COMPONENT_OPTIONS = [
  ...COMPONENTS.map((c) => ({ value: c, label: c })),
  { value: 'DRIVE', label: 'Drive (per drive model)' },
];

function splitComponent(component: string): { component: string; drive_model: string } {
  return component.startsWith('DRIVE:')
    ? { component: 'DRIVE', drive_model: component.slice('DRIVE:'.length) }
    : { component, drive_model: '' };
}

const joinComponent = (v: BaselineForm) =>
  v.component === 'DRIVE' ? `DRIVE:${v.drive_model.trim()}` : v.component;

function validate(v: BaselineForm, mode: 'create' | 'edit'): FormErrors {
  const e: FormErrors = {};
  if (mode === 'create') {
    if (!v.vendor) e.vendor = 'Choose a vendor.';
    if (!v.model.trim()) e.model = 'Enter the server model, as reported by the BMC.';
    if (!v.component) e.component = 'Choose a component.';
    if (v.component === 'DRIVE' && !v.drive_model.trim()) e.drive_model = 'Enter the drive model.';
  }
  if (!v.version.trim()) e.version = 'Enter the approved version.';
  return e;
}

const columns: Column<Baseline>[] = [
  { id: 'vendor', header: 'Vendor', cell: (b) => b.vendor },
  { id: 'model', header: 'Model', cell: (b) => <span className="font-medium">{b.model}</span> },
  {
    id: 'component',
    header: 'Component',
    cell: (b) =>
      b.component.startsWith('DRIVE:') ? (
        <>
          Drive <span className="font-mono text-xs text-text-muted">{b.component.slice(6)}</span>
        </>
      ) : (
        b.component
      ),
  },
  {
    id: 'version',
    header: 'Approved version',
    cell: (b) => <span className="font-mono text-xs">{b.version}</span>,
  },
  {
    id: 'notes',
    header: 'Notes',
    cell: (b) =>
      b.notes ? (
        <span className="line-clamp-2 max-w-xs" title={b.notes}>
          {b.notes}
        </span>
      ) : (
        <span className="text-text-subtle">—</span>
      ),
  },
  {
    id: 'updated_by',
    header: 'Updated by',
    cell: (b) => b.updated_by ?? <span className="text-text-subtle">—</span>,
  },
  {
    id: 'updated_at',
    header: 'Updated',
    cell: (b) => <span className="tabular whitespace-nowrap">{formatTimestamp(b.updated_at)}</span>,
  },
];

export default function BaselinesSection() {
  const can = useCan();
  const unrestricted = useUnrestricted();
  // Baselines apply to every site, so site-limited engineers see them read-only.
  const canEdit = can('edit_baselines') && unrestricted;
  const [f, setF] = useUrlState({ vendor: '', component: '' });
  const list = useCursorList<Baseline>('/api/v1/firmware/baselines', {
    vendor: f.vendor || undefined,
    component: f.component || undefined,
  });

  const form: CrudForm<Baseline, BaselineForm, Baseline> = {
    empty: () => ({
      vendor: f.vendor,
      model: '',
      component: f.component,
      drive_model: '',
      version: '',
      notes: '',
    }),
    fromRow: (b) => ({
      vendor: b.vendor,
      model: b.model,
      ...splitComponent(b.component),
      version: b.version,
      notes: b.notes ?? '',
    }),
    validate: (v, mode) => validate(v, mode),
    create: (v) => ({
      method: 'POST',
      path: '/api/v1/firmware/baselines',
      body: {
        vendor: v.vendor,
        model: v.model.trim(),
        component: joinComponent(v),
        version: v.version.trim(),
        notes: optText(v.notes),
      },
    }),
    update: (v, b) => ({
      method: 'PUT',
      path: `/api/v1/firmware/baselines/${b.id}`,
      body: { version: v.version.trim(), notes: optText(v.notes) },
    }),
    render: ({ values, set, patch, errors, mode }) => (
      <>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Vendor" required={mode === 'create'} error={errors.vendor}>
            <Select
              value={values.vendor}
              options={VENDOR_OPTIONS}
              placeholder="Choose a vendor"
              disabled={mode === 'edit'}
              onChange={(e) => set('vendor', e.target.value)}
            />
          </FormField>
          <FormField
            label="Model"
            required={mode === 'create'}
            error={errors.model}
            hint={mode === 'create' ? 'Exactly as the BMC reports it, e.g. PowerEdge R750.' : undefined}
          >
            <TextInput
              value={values.model}
              maxLength={128}
              disabled={mode === 'edit'}
              onChange={(e) => set('model', e.target.value)}
            />
          </FormField>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Component" required={mode === 'create'} error={errors.component}>
            <Select
              value={values.component}
              options={COMPONENT_OPTIONS}
              placeholder="Choose a component"
              disabled={mode === 'edit'}
              onChange={(e) => patch({ component: e.target.value, drive_model: '' })}
            />
          </FormField>
          {values.component === 'DRIVE' ? (
            <FormField label="Drive model" required={mode === 'create'} error={errors.drive_model}>
              <TextInput
                value={values.drive_model}
                maxLength={150}
                spellCheck={false}
                className="font-mono"
                disabled={mode === 'edit'}
                onChange={(e) => set('drive_model', e.target.value)}
              />
            </FormField>
          ) : null}
        </div>
        <FormField label="Approved version" required error={errors.version}>
          <TextInput
            value={values.version}
            maxLength={64}
            spellCheck={false}
            className="font-mono"
            onChange={(e) => set('version', e.target.value)}
          />
        </FormField>
        <FormField label="Notes" error={errors.notes}>
          <TextArea
            value={values.notes}
            maxLength={2000}
            rows={2}
            onChange={(e) => set('notes', e.target.value)}
          />
        </FormField>
        {mode === 'edit' ? (
          <Hint>To approve a different model or component, add a new baseline.</Hint>
        ) : (
          <Hint>Servers of this model whose firmware differs are flagged in the daily compliance check.</Hint>
        )}
      </>
    ),
  };

  return (
    <CrudList<Baseline, BaselineForm, Baseline>
      title="Firmware baselines"
      noun="baseline"
      caption="Firmware baselines"
      intro="The approved firmware version per vendor, model and component. Firmware compliance compares every server against these."
      columns={columns}
      table={list.tableProps}
      getRowId={(b) => b.id}
      rowName={(b) => `${b.model} ${b.component}`}
      invalidate={['firmware']}
      canEdit={canEdit}
      readOnlyReason={
        can('edit_baselines')
          ? 'Baselines apply to every site, so users limited to some sites cannot change them.'
          : 'Changing baselines needs the DC engineer role.'
      }
      createLabel="Add baseline"
      toolbar={
        <>
          <FilterSelect
            label="Vendor"
            value={f.vendor}
            onChange={(v) => setF({ vendor: v })}
            options={VENDOR_OPTIONS}
            placeholder="All vendors"
          />
          <FilterSelect
            label="Component"
            value={f.component}
            onChange={(v) => setF({ component: v })}
            options={COMPONENTS.map((c) => ({ value: c, label: c }))}
            placeholder="All components"
          />
        </>
      }
      emptyTitle="No baselines"
      emptyDescription="Add the approved versions so firmware compliance can flag servers that differ."
      form={form}
      remove={{
        path: (b) => `/api/v1/firmware/baselines/${b.id}`,
        description: () => 'Servers of this model are no longer checked for this component.',
      }}
      persistKey="admin-baselines"
    />
  );
}
