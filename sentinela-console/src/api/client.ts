// Cliente HTTP da API do Sentinela. Base `/api/v1`, JSON em snake_case.
// A autenticação é injetada por `configureClient` (cabeçalho X-Sentinela-User no modo
// dev, Bearer do OIDC no modo oidc).

export const API_BASE = '/api/v1';

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly errors: string[];

  constructor(status: number, detail: string, errors: string[] = []) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.errors = errors;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

export type QueryValue = string | number | boolean | null | undefined | string[];
export type Query = Record<string, QueryValue>;

export interface RequestOptions {
  query?: Query;
  body?: unknown;
  signal?: AbortSignal;
  /** Rota pública (ex.: GET /config): não envia credencial nem trata 401. */
  anonymous?: boolean;
}

type HeaderProvider = () => Promise<Record<string, string>>;

let headerProvider: HeaderProvider = async () => ({});
let unauthorizedHandler: (() => void) | null = null;

export function configureClient(opts: { headers?: HeaderProvider; onUnauthorized?: () => void }): void {
  if (opts.headers) headerProvider = opts.headers;
  if (opts.onUnauthorized) unauthorizedHandler = opts.onUnauthorized;
}

export async function authHeaders(): Promise<Record<string, string>> {
  return headerProvider();
}

export function notifyUnauthorized(): void {
  unauthorizedHandler?.();
}

export function toSearchParams(query?: Query): URLSearchParams {
  const params = new URLSearchParams();
  if (!query) return params;
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) {
      for (const v of value) params.append(key, v);
    } else {
      params.set(key, String(value));
    }
  }
  return params;
}

export function buildUrl(path: string, query?: Query): string {
  const qs = toSearchParams(query).toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ''}`;
}

const STATUS_MESSAGES: Record<number, string> = {
  400: 'Requisição inválida.',
  401: 'Sua sessão expirou. Entre novamente.',
  403: 'Você não tem permissão para esta ação.',
  404: 'Recurso não encontrado.',
  409: 'Conflito com o estado atual do recurso.',
  422: 'Dados inválidos.',
  429: 'Muitas requisições. Aguarde um instante.',
  500: 'Erro interno da API.',
  502: 'O provedor (GitHub/GitLab) não respondeu como esperado.',
  503: 'A API está indisponível no momento.',
  504: 'A API demorou demais para responder.',
};

async function toApiError(res: Response): Promise<ApiError> {
  const fallback = STATUS_MESSAGES[res.status] ?? `Erro ${res.status}.`;
  let payload: unknown = null;
  try {
    const text = await res.text();
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = null;
  }
  if (payload && typeof payload === 'object') {
    const body = payload as { detail?: unknown; errors?: unknown };
    const errors = Array.isArray(body.errors) ? body.errors.map(String) : [];
    if (typeof body.detail === 'string') return new ApiError(res.status, body.detail, errors);
    return new ApiError(res.status, fallback, errors);
  }
  return new ApiError(res.status, fallback);
}

export async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (!opts.anonymous) Object.assign(headers, await headerProvider());
  let body: BodyInit | undefined;
  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), { method, headers, body, signal: opts.signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(0, 'Não foi possível conectar à API. Verifique a rede e tente de novo.');
  }
  if (res.status === 401 && !opts.anonymous) unauthorizedHandler?.();
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  const type = res.headers.get('content-type') ?? '';
  if (type.includes('json')) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>('GET', path, { query, signal }),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, { body: body ?? {} }),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, { body }),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, { body }),
  delete: <T = void>(path: string) => request<T>('DELETE', path),
};

/** Baixa um arquivo autenticado (export YAML) com o nome sugerido pela API. */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const headers = await headerProvider();
  let res: Response;
  try {
    res = await fetch(buildUrl(path), { headers });
  } catch {
    throw new ApiError(0, 'Não foi possível conectar à API.');
  }
  if (res.status === 401) unauthorizedHandler?.();
  if (!res.ok) throw await toApiError(res);
  const blob = await res.blob();
  const match = res.headers.get('content-disposition')?.match(/filename="?([^";]+)"?/i);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = match?.[1] ?? fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
