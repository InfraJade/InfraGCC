import { useState, type FormEvent } from 'react';

import { ApiError, errorMessage } from '@/api/errors';
import { send, useApiMutation } from '@/api/hooks';
import type { ServerDetail, ServerStatus, ServerUpdate } from '@/api/types';
import { Button } from '@/components/Button';
import { Dialog } from '@/components/Dialog';
import { FormField, Select, TextArea, TextInput } from '@/components/FormField';

const STATUSES: { value: ServerStatus; label: string }[] = [
  { value: 'active', label: 'Active' },
  { value: 'maintenance', label: 'Maintenance' },
  { value: 'decommissioned', label: 'Decommissioned' },
];

interface FormValues {
  name: string;
  asset_tag: string;
  status: ServerStatus;
  notes: string;
}

function initial(s: ServerDetail): FormValues {
  const status = STATUSES.some((o) => o.value === s.status) ? (s.status as ServerStatus) : 'active';
  return { name: s.name, asset_tag: s.asset_tag ?? '', status, notes: s.notes ?? '' };
}

/** Edit name, asset tag, status and notes (DC engineers). 422 field errors show under their fields. */
export function EditServerDialog({
  server,
  open,
  onClose,
}: {
  server: ServerDetail;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Dialog open={open} onClose={onClose} title={`Edit ${server.name}`} description="Changes are audited.">
      {/* Mounted per opening, so the form starts from the server's current values every time. */}
      {open ? <EditForm server={server} onClose={onClose} /> : null}
    </Dialog>
  );
}

function EditForm({ server, onClose }: { server: ServerDetail; onClose: () => void }) {
  const [values, setValues] = useState<FormValues>(() => initial(server));
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  const mutation = useApiMutation(
    (api, body: ServerUpdate) => api.json<ServerDetail>(`/api/v1/servers/${server.id}`, send('PATCH', body)),
    {
      invalidate: ['servers', 'racks', 'sites'],
      success: (s) => `${s.name} updated`,
      toastErrors: false,
      onSuccess: onClose,
    },
  );

  const set = <K extends keyof FormValues>(key: K, value: FormValues[K]) =>
    setValues((v) => ({ ...v, [key]: value }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setFieldErrors({});
    setFormError(null);
    if (!values.name.trim()) {
      setFieldErrors({ name: 'Enter a name.' });
      return;
    }
    const body: ServerUpdate = {
      name: values.name.trim(),
      asset_tag: values.asset_tag.trim() || null,
      status: values.status,
      notes: values.notes.trim() || null,
    };
    mutation.mutate(body, {
      onError: (err) => {
        if (err instanceof ApiError && err.isValidation) {
          const fields = err.fieldErrors();
          setFieldErrors(fields);
          const known = ['name', 'asset_tag', 'status', 'notes'];
          if (!Object.keys(fields).some((k) => known.includes(k))) setFormError(errorMessage(err));
        } else {
          setFormError(errorMessage(err));
        }
      },
    });
  };

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <FormField label="Name" required error={fieldErrors.name}>
        <TextInput value={values.name} onChange={(e) => set('name', e.target.value)} maxLength={128} />
      </FormField>
      <FormField label="Asset tag" error={fieldErrors.asset_tag}>
        <TextInput
          value={values.asset_tag}
          onChange={(e) => set('asset_tag', e.target.value)}
          maxLength={64}
        />
      </FormField>
      <FormField
        label="Status"
        error={fieldErrors.status}
        hint="Decommissioned servers are hidden from server lists by default."
      >
        <Select
          value={values.status}
          onChange={(e) => set('status', e.target.value as ServerStatus)}
          options={STATUSES}
        />
      </FormField>
      <FormField label="Notes" error={fieldErrors.notes}>
        <TextArea
          value={values.notes}
          onChange={(e) => set('notes', e.target.value)}
          rows={4}
          maxLength={4000}
        />
      </FormField>
      {formError ? (
        <p role="alert" className="text-sm text-health-critical">
          {formError}
        </p>
      ) : null}
      <div className="mt-2 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" loading={mutation.isPending}>
          Save changes
        </Button>
      </div>
    </form>
  );
}
