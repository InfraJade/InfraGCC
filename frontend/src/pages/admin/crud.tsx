/**
 * The admin CRUD pattern: a titled list (toolbar + DataTable + load more), a create/edit Dialog with a typed
 * form, and a delete confirmation. Every admin section is built from it.
 *
 * - Client-side `validate` runs first; then the request goes out. A 422 puts each `ApiError.fieldErrors()`
 *   message next to its field (keys match the form's value keys, which mirror the API body names); errors
 *   for other locations, 409 conflicts and every other failure show as one form-level message.
 * - Success toasts "<Noun> created / saved / deleted" and invalidates the listed resources.
 * - Users who may view but not edit see the list read-only (no create button, no row actions).
 */
import { useCallback, useId, useState, type ReactNode } from 'react';

import { ApiError, errorMessage } from '@/api/errors';
import { send, useApiMutation } from '@/api/hooks';
import { Button } from '@/components/Button';
import { DataTable, type Column } from '@/components/DataTable';
import { ConfirmDialog, Dialog } from '@/components/Dialog';
import { FormField, Select, type SelectOption } from '@/components/FormField';
import { Icon } from '@/components/Icon';
import { cn } from '@/lib/cn';

export type FormMode = 'create' | 'edit';
export type FormErrors = Record<string, string>;

export interface SaveRequest {
  method: 'POST' | 'PUT' | 'PATCH';
  path: string;
  body: unknown;
}

export interface FormApi<F> {
  values: F;
  /** Set one value (clears that field's error). */
  set: <K extends keyof F>(key: K, value: F[K]) => void;
  /** Set several values at once (e.g. a site change resets room and rack). */
  patch: (p: Partial<F>) => void;
  errors: FormErrors;
  mode: FormMode;
}

export interface CrudForm<T, F, R = unknown> {
  /** Values of a new item. */
  empty: () => F;
  /** Values when editing `row`. */
  fromRow: (row: T) => F;
  render: (form: FormApi<F>, row: T | null) => ReactNode;
  /** Client-side checks; return messages keyed like the values. */
  validate?: (values: F, mode: FormMode, row: T | null) => FormErrors;
  /** Present → "Add" button. */
  create?: (values: F) => SaveRequest;
  /** Present → edit button per row. */
  update?: (values: F, row: T) => SaveRequest;
  /** Hide the edit button for rows this user can't change (default: all editable). */
  editable?: (row: T) => boolean;
  size?: 'sm' | 'md' | 'lg';
  description?: (mode: FormMode, row: T | null) => ReactNode;
  onSaved?: (result: R, mode: FormMode) => void;
}

export interface CrudRemove<T> {
  path: (row: T) => string;
  /** Hide the button for rows that can't be removed (e.g. built-in rules). */
  allowed?: (row: T) => boolean;
  /** Button / confirm word, default "Delete". */
  verb?: string;
  /** Past tense for the toast, default "deleted". */
  done?: string;
  description?: (row: T) => ReactNode;
}

/** The subset of `useCursorList().tableProps` the table needs. */
export interface ListTableProps<T> {
  rows: readonly T[];
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  hasMore?: boolean;
  onLoadMore?: () => void;
  loadingMore?: boolean;
}

export interface CrudListProps<T, F, R = unknown> {
  title: string;
  /** Lower-case singular, e.g. "rack". */
  noun: string;
  caption: string;
  columns: Column<T>[];
  table: ListTableProps<T>;
  getRowId: (row: T) => number;
  /** Name used in button labels and confirmations. */
  rowName: (row: T) => string;
  /** Resources to refresh after a write, e.g. ['racks', 'sites']. */
  invalidate: string[];
  canEdit: boolean;
  /** Shown to read-only users, e.g. "Changing sites needs the Platform admin role." */
  readOnlyReason?: ReactNode;
  intro?: ReactNode;
  toolbar?: ReactNode;
  summary?: ReactNode;
  emptyTitle?: string;
  emptyDescription?: ReactNode;
  form?: CrudForm<T, F, R>;
  remove?: CrudRemove<T>;
  /** Extra per-row actions (shown to every user; check permissions inside). */
  rowActions?: (row: T) => ReactNode;
  createLabel?: string;
  persistKey?: string;
  /** Content between the header and the table (banners, notices). */
  children?: ReactNode;
}

const capitalize = (s: string) => (s ? s[0]!.toUpperCase() + s.slice(1) : s);

type DialogState<T> = { mode: 'create'; row: null } | { mode: 'edit'; row: T } | null;

export function CrudList<T, F, R = unknown>(props: CrudListProps<T, F, R>) {
  const {
    title,
    noun,
    caption,
    columns,
    table,
    getRowId,
    rowName,
    invalidate,
    canEdit,
    readOnlyReason,
    intro,
    toolbar,
    summary,
    emptyTitle,
    emptyDescription,
    form,
    remove,
    rowActions,
    createLabel,
    persistKey,
    children,
  } = props;
  const headingId = useId();
  const [dialog, setDialog] = useState<DialogState<T>>(null);
  const [deleting, setDeleting] = useState<T | null>(null);

  const canUpdate = canEdit && Boolean(form?.update);
  const canRemove = canEdit && Boolean(remove);
  const withActions = canUpdate || canRemove || Boolean(rowActions);
  const allColumns: Column<T>[] = withActions
    ? [
        ...columns,
        {
          id: 'actions',
          header: <span className="sr-only">Actions</span>,
          label: 'Actions',
          hideable: false,
          align: 'right',
          width: '1%',
          cell: (row) => (
            <div className="flex items-center justify-end gap-1">
              {rowActions?.(row)}
              {canUpdate && (form?.editable?.(row) ?? true) ? (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Edit ${rowName(row)}`}
                  onClick={() => setDialog({ mode: 'edit', row })}
                >
                  Edit
                </Button>
              ) : null}
              {canRemove && remove && (remove.allowed?.(row) ?? true) ? (
                <Button
                  size="sm"
                  variant="ghost"
                  className="hover:text-health-critical"
                  aria-label={`${remove.verb ?? 'Delete'} ${rowName(row)}`}
                  onClick={() => setDeleting(row)}
                >
                  {remove.verb ?? 'Delete'}
                </Button>
              ) : null}
            </div>
          ),
        },
      ]
    : columns;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 id={headingId} className="text-base font-semibold text-text">
            {title}
          </h2>
          {intro ? <p className="mt-0.5 text-sm text-text-muted">{intro}</p> : null}
        </div>
        {canEdit && form?.create ? (
          <Button variant="primary" icon="plus" onClick={() => setDialog({ mode: 'create', row: null })}>
            {createLabel ?? `Add ${noun}`}
          </Button>
        ) : null}
      </div>
      {!canEdit && readOnlyReason ? <ReadOnlyNote>{readOnlyReason}</ReadOnlyNote> : null}
      {children}
      <DataTable<T>
        columns={allColumns}
        getRowId={getRowId}
        caption={caption}
        toolbar={toolbar}
        summary={summary}
        emptyTitle={emptyTitle}
        emptyDescription={emptyDescription}
        persistKey={persistKey}
        {...table}
      />
      {dialog && form ? (
        <CrudFormDialog<T, F, R>
          key={dialog.mode === 'edit' ? `edit-${getRowId(dialog.row)}` : 'create'}
          noun={noun}
          title={dialog.mode === 'edit' ? `Edit ${rowName(dialog.row)}` : (createLabel ?? `Add ${noun}`)}
          mode={dialog.mode}
          row={dialog.row}
          form={form}
          invalidate={invalidate}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {deleting !== null && remove ? (
        <DeleteDialog<T>
          row={deleting}
          noun={noun}
          name={rowName(deleting)}
          remove={remove}
          invalidate={invalidate}
          onClose={() => setDeleting(null)}
        />
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------------------------- form dialog

const GENERIC_422 = 'The request did not pass validation.';

/** Pydantic prefixes model-level messages with "Value error, ". */
function cleanMessage(msg: string): string {
  return msg.replace(/^Value error, /, '');
}

/** Split an API error into inline field messages (for `fields`) and one form-level message. */
export function splitSaveError(
  err: unknown,
  fields: readonly string[],
): { fieldErrors: FormErrors; formError: string | null } {
  if (!(err instanceof ApiError)) return { fieldErrors: {}, formError: errorMessage(err) };
  const fieldErrors: FormErrors = {};
  const other: string[] = [];
  const byField = err.fieldErrors();
  for (const [key, msg] of Object.entries(byField)) {
    if (fields.includes(key)) fieldErrors[key] = cleanMessage(msg);
  }
  for (const issue of err.problem.errors ?? []) {
    const key = issue.loc[issue.loc.length - 1] ?? '';
    if (!fields.includes(key)) other.push(cleanMessage(issue.msg));
  }
  const detail = err.problem.detail ?? err.problem.title;
  const hasInline = Object.keys(fieldErrors).length > 0;
  let formError: string | null;
  if (other.length) formError = detail === GENERIC_422 ? other.join(' ') : `${detail} ${other.join(' ')}`;
  else if (hasInline) formError = detail === GENERIC_422 ? 'Check the highlighted fields.' : detail;
  else formError = detail;
  return { fieldErrors, formError };
}

function withoutKeys(errors: FormErrors, keys: string[]): FormErrors {
  if (!keys.some((k) => k in errors)) return errors;
  const next = { ...errors };
  for (const k of keys) delete next[k];
  return next;
}

function CrudFormDialog<T, F, R>({
  noun,
  title,
  mode,
  row,
  form,
  invalidate,
  onClose,
}: {
  noun: string;
  title: string;
  mode: FormMode;
  row: T | null;
  form: CrudForm<T, F, R>;
  invalidate: string[];
  onClose: () => void;
}) {
  const formId = useId();
  const [values, setValues] = useState<F>(() =>
    mode === 'edit' && row !== null ? form.fromRow(row) : form.empty(),
  );
  const [errors, setErrors] = useState<FormErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const mutation = useApiMutation<SaveRequest, R>(
    (api, req) => api.json<R>(req.path, send(req.method, req.body)),
    {
      invalidate,
      toastErrors: false,
      success: `${capitalize(noun)} ${mode === 'create' ? 'created' : 'saved'}`,
    },
  );

  // Stable setters, so field components can use them in effects.
  const set = useCallback(<K extends keyof F>(key: K, value: F[K]) => {
    setValues((v) => ({ ...v, [key]: value }));
    setErrors((prev) => withoutKeys(prev, [String(key)]));
  }, []);
  const patch = useCallback((p: Partial<F>) => {
    setValues((v) => ({ ...v, ...p }));
    setErrors((prev) => withoutKeys(prev, Object.keys(p)));
  }, []);
  const api: FormApi<F> = { values, mode, errors, set, patch };

  const submit = () => {
    setFormError(null);
    const local = form.validate?.(values, mode, row) ?? {};
    if (Object.keys(local).length > 0) {
      setErrors(local);
      setFormError('Check the highlighted fields.');
      return;
    }
    const req = mode === 'edit' && row !== null ? form.update?.(values, row) : form.create?.(values);
    if (!req) return;
    mutation.mutate(req, {
      onSuccess: (result) => {
        form.onSaved?.(result, mode);
        onClose();
      },
      onError: (err) => {
        const split = splitSaveError(err, Object.keys(values as object));
        setErrors(split.fieldErrors);
        setFormError(split.formError);
      },
    });
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title={title}
      description={form.description?.(mode, row)}
      size={form.size ?? 'md'}
      dismissible={!mutation.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form={formId} loading={mutation.isPending}>
            {mode === 'create' ? 'Create' : 'Save'}
          </Button>
        </>
      }
    >
      <form
        id={formId}
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="flex max-h-[65vh] flex-col gap-4 overflow-y-auto px-0.5 pb-1"
      >
        {formError ? <FormError>{formError}</FormError> : null}
        {form.render(api, row)}
      </form>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------------------------- delete dialog

function DeleteDialog<T>({
  row,
  noun,
  name,
  remove,
  invalidate,
  onClose,
}: {
  row: T;
  noun: string;
  name: string;
  remove: CrudRemove<T>;
  invalidate: string[];
  onClose: () => void;
}) {
  const verb = remove.verb ?? 'Delete';
  const mutation = useApiMutation<string, unknown>((api, path) => api.json(path, send('DELETE')), {
    invalidate,
    toastErrors: false,
    success: `${capitalize(noun)} ${remove.done ?? 'deleted'}`,
  });
  return (
    <ConfirmDialog
      open
      title={`${verb} ${name}?`}
      description={remove.description?.(row) ?? 'This cannot be undone.'}
      confirmLabel={verb}
      tone="danger"
      busy={mutation.isPending}
      onConfirm={() => mutation.mutate(remove.path(row), { onSuccess: onClose })}
      onCancel={onClose}
    >
      {mutation.error ? <FormError>{errorMessage(mutation.error)}</FormError> : null}
    </ConfirmDialog>
  );
}

// ---------------------------------------------------------------------------------------------- small parts

export function FormError({ children }: { children: ReactNode }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-md bg-health-critical/10 px-3 py-2 text-sm text-health-critical ring-1 ring-inset ring-health-critical/30"
    >
      <Icon name="triangle-alert" size={16} className="mt-0.5 shrink-0" />
      <span>{children}</span>
    </div>
  );
}

export function ReadOnlyNote({ children }: { children: ReactNode }) {
  return (
    <p className="glass-subtle flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-text-muted">
      <Icon name="eye" size={16} className="shrink-0 text-text-subtle" />
      <span>
        <span className="font-medium text-text">Read-only.</span> {children}
      </span>
    </p>
  );
}

export function Hint({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p className={cn('flex items-start gap-2 text-xs text-text-muted', className)}>
      <Icon name="info" size={14} className="mt-px shrink-0 text-info" />
      <span>{children}</span>
    </p>
  );
}

/** A labelled select for list toolbars (label visually hidden). */
export function FilterSelect({
  label,
  value,
  onChange,
  options,
  placeholder,
  className,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: SelectOption[];
  placeholder?: string;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <FormField label={label} hideLabel className={cn('w-44', className)}>
      <Select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        options={options}
        placeholder={placeholder}
        disabled={disabled}
      />
    </FormField>
  );
}

/** Compact on/off switch for a table row: visible word + accessible name naming the row. */
export function RowSwitch({
  checked,
  label,
  onChange,
  disabled,
  busy,
}: {
  checked: boolean;
  /** e.g. "Enabled: collector-pnq1-a" */
  label: string;
  onChange?: (v: boolean) => void;
  disabled?: boolean;
  busy?: boolean;
}) {
  const word = checked ? 'Enabled' : 'Disabled';
  if (!onChange)
    return <span className={checked ? 'text-sm text-text' : 'text-sm text-text-subtle'}>{word}</span>;
  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        aria-busy={busy || undefined}
        disabled={disabled || busy}
        onClick={() => onChange(!checked)}
        className={cn(
          'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-fast disabled:opacity-50',
          checked ? 'bg-accent' : 'bg-text/20',
        )}
      >
        <span
          className={cn(
            'inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-fast ease-standard',
            checked ? 'translate-x-[18px]' : 'translate-x-0.5',
          )}
        />
      </button>
      <span className={checked ? 'text-sm text-text' : 'text-sm text-text-subtle'}>{word}</span>
    </span>
  );
}

// ---------------------------------------------------------------------------------------------- value helpers

/** '' / whitespace → null, otherwise the trimmed text. */
export function optText(v: string): string | null {
  const t = v.trim();
  return t === '' ? null : t;
}

/** '' → null; otherwise the number (NaN when not numeric: validate first). */
export function optNumber(v: string): number | null {
  const t = v.trim();
  return t === '' ? null : Number(t);
}

export function isInt(v: string, min?: number, max?: number): boolean {
  const t = v.trim();
  if (!/^-?\d+$/.test(t)) return false;
  const n = Number(t);
  return (min === undefined || n >= min) && (max === undefined || n <= max);
}

export function isNumber(v: string): boolean {
  return v.trim() !== '' && Number.isFinite(Number(v));
}

export const numText = (n: number | null | undefined) => (n === null || n === undefined ? '' : String(n));

const pad = (n: number) => String(n).padStart(2, '0');

/** Date → value for <input type="datetime-local"> in the browser's time zone. */
export function toLocalInput(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(
    date.getMinutes(),
  )}`;
}

/** ISO timestamp → datetime-local value (browser time zone). */
export function isoToLocalInput(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : toLocalInput(d);
}

/**
 * datetime-local value ("2026-10-27T09:00", browser time zone) → ISO 8601 with the local UTC offset,
 * e.g. "2026-10-27T09:00:00+05:30". Returns null for an empty or invalid value.
 */
export function localInputToIso(value: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value.trim());
  if (!m) return null;
  const [, y, mo, d, h, mi, s] = m;
  const date = new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s ?? '0'));
  if (Number.isNaN(date.getTime())) return null;
  const offset = -date.getTimezoneOffset();
  const sign = offset >= 0 ? '+' : '-';
  const abs = Math.abs(offset);
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(
    date.getMinutes(),
  )}:${pad(date.getSeconds())}${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

/** "300" → "5 min"; 0 → "Immediately". */
export function formatDuration(seconds: number): string {
  if (seconds <= 0) return 'Immediately';
  if (seconds < 60) return `${seconds} s`;
  if (seconds < 3600)
    return seconds % 60 === 0 ? `${seconds / 60} min` : `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return m ? `${h} h ${m} min` : `${h} h`;
}
