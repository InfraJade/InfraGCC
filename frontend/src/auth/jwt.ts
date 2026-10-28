/** Decode (not verify) a JWT payload. The API verifies tokens; the UI only reads claims for display/gating. */
export function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const part = token.split('.')[1];
  if (!part) return null;
  try {
    const b64 = part
      .replace(/-/g, '+')
      .replace(/_/g, '/')
      .padEnd(Math.ceil(part.length / 4) * 4, '=');
    const bin = atob(b64);
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
    const json = new TextDecoder().decode(bytes);
    const parsed: unknown = JSON.parse(json);
    return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

export function stringArrayClaim(claims: Record<string, unknown> | null | undefined, name: string): string[] {
  const v = claims?.[name];
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
}
