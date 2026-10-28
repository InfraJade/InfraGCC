/** Field-by-field comparison of an audit entry's `before` and `after` objects. */

export type ChangeKind = 'changed' | 'added' | 'removed' | 'unchanged';

export interface FieldChange {
  key: string;
  kind: ChangeKind;
  before: unknown;
  after: unknown;
}

type Obj = Record<string, unknown> | null | undefined;

/** Stable JSON (sorted object keys) so key order never counts as a change. */
export function stableJson(value: unknown): string {
  return JSON.stringify(value, (_k, v: unknown) =>
    v && typeof v === 'object' && !Array.isArray(v)
      ? Object.fromEntries(
          Object.entries(v as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)),
        )
      : v,
  );
}

/** Changed fields first, then added, removed and unchanged; alphabetical within each group. */
export function diffObjects(before: Obj, after: Obj): FieldChange[] {
  const b = before ?? {};
  const a = after ?? {};
  const keys = new Set([...Object.keys(b), ...Object.keys(a)]);
  const out: FieldChange[] = [];
  for (const key of keys) {
    const inB = Object.hasOwn(b, key);
    const inA = Object.hasOwn(a, key);
    let kind: ChangeKind;
    if (inB && !inA) kind = 'removed';
    else if (!inB && inA) kind = 'added';
    else kind = stableJson(b[key]) === stableJson(a[key]) ? 'unchanged' : 'changed';
    out.push({ key, kind, before: b[key], after: a[key] });
  }
  const order: Record<ChangeKind, number> = { changed: 0, added: 1, removed: 2, unchanged: 3 };
  return out.sort((x, y) => order[x.kind] - order[y.kind] || x.key.localeCompare(y.key));
}

/** Short readable value: strings as-is, null as "null", objects/arrays as compact JSON. */
export function formatDiffValue(value: unknown): string {
  if (value === undefined) return '';
  if (value === null) return 'null';
  if (typeof value === 'string') return value === '' ? '""' : value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return stableJson(value);
}
