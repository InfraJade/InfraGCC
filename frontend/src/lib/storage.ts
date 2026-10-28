/**
 * localStorage access that never throws (private windows, blocked site data, SSR/tests).
 * Only for per-user conveniences (theme, sidebar state, column visibility) — never for anything important.
 */
export function readJson<T>(key: string, fallback: T, validate?: (v: unknown) => v is T): T {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === null) return fallback;
    const parsed: unknown = JSON.parse(raw);
    if (validate && !validate(parsed)) return fallback;
    return parsed as T;
  } catch {
    return fallback;
  }
}

export function writeJson(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable: preference just isn't remembered */
  }
}
