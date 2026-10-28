/**
 * RFC 9457 problem details (`application/problem+json`) as typed errors.
 * Mirrors `backend/app/core/problems.py`: {type, title, status, detail?, instance?, ...extensions};
 * validation errors (422) carry `errors: [{loc, msg, type}]`.
 */

export interface ValidationIssue {
  loc: string[];
  msg: string;
  type: string;
}

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  errors?: ValidationIssue[];
  [extension: string]: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail ?? problem.title);
    this.name = 'ApiError';
    this.status = problem.status;
    this.problem = problem;
  }

  get isUnauthorized() {
    return this.status === 401;
  }
  get isForbidden() {
    return this.status === 403;
  }
  get isNotFound() {
    return this.status === 404;
  }
  get isValidation() {
    return this.status === 422;
  }
  get isRateLimited() {
    return this.status === 429;
  }

  /** Field-level messages keyed by the last `loc` segment (for forms). */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const e of this.problem.errors ?? []) {
      const key = e.loc[e.loc.length - 1] ?? '';
      out[key] ??= e.msg;
    }
    return out;
  }
}

/** The request never got an HTTP response (offline, DNS, CORS, aborted). */
export class NetworkError extends Error {
  constructor(message = 'Network error: the server could not be reached.', options?: { cause?: unknown }) {
    super(message, options);
    this.name = 'NetworkError';
  }
}

const DEFAULT_TITLES: Record<number, string> = {
  400: 'Bad request',
  401: 'Not authenticated',
  403: 'Forbidden',
  404: 'Not found',
  409: 'Conflict',
  422: 'Validation failed',
  429: 'Too many requests',
  500: 'Internal server error',
  502: 'Bad gateway',
  503: 'Service unavailable',
  504: 'Gateway timeout',
};

function isValidationIssue(v: unknown): v is ValidationIssue {
  if (typeof v !== 'object' || v === null) return false;
  const o = v as Record<string, unknown>;
  return Array.isArray(o.loc) && typeof o.msg === 'string';
}

/** Coerce any parsed body into a Problem, falling back to the HTTP status for missing fields. */
export function toProblem(body: unknown, status: number, statusText = ''): Problem {
  const fallbackTitle = DEFAULT_TITLES[status] ?? (statusText || 'Error');
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    const problem: Problem = { type: 'about:blank', title: fallbackTitle, status };
    if (typeof body === 'string' && body.trim() !== '' && body.length < 500) problem.detail = body.trim();
    return problem;
  }
  const o = body as Record<string, unknown>;
  const problem: Problem = {
    ...o,
    type: typeof o.type === 'string' ? o.type : 'about:blank',
    title: typeof o.title === 'string' ? o.title : fallbackTitle,
    status: typeof o.status === 'number' ? o.status : status,
  };
  if (typeof o.detail === 'string') problem.detail = o.detail;
  else if (typeof o.detail !== 'undefined') {
    // FastAPI's default `{"detail": ...}` shape (non-string detail) → keep it readable.
    delete problem.detail;
  }
  if (Array.isArray(o.errors))
    problem.errors = o.errors
      .filter(isValidationIssue)
      .map((e) => ({ ...e, loc: e.loc.map(String), type: String(e.type ?? '') }));
  return problem;
}

/** Read a failed Response into an ApiError (works for problem+json, plain JSON, text or empty bodies). */
export async function parseProblemResponse(response: Response): Promise<ApiError> {
  let body: unknown = undefined;
  try {
    const text = await response.text();
    const type = response.headers.get('content-type') ?? '';
    if (text) body = /json/i.test(type) || /^\s*[{[]/.test(text) ? (JSON.parse(text) as unknown) : text;
  } catch {
    body = undefined;
  }
  return new ApiError(toProblem(body, response.status, response.statusText));
}

/** Human-readable message for any thrown value (toasts, error states). */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const p = err.problem;
    if (p.errors?.length)
      return `${p.detail ?? p.title} ${p.errors.map((e) => `${e.loc.slice(1).join('.') || e.loc.join('.')}: ${e.msg}`).join('; ')}`;
    return p.detail ?? p.title;
  }
  if (err instanceof Error) return err.message;
  if (typeof err === 'string') return err;
  return 'Something went wrong.';
}
