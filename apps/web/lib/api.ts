import type {
  CoveredDestination,
  HealthReady,
  PlaceSuggestion,
  Trip,
  TripRequest,
  TripSummary,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8811").replace(/\/+$/, "");

/** Why a request failed — the UI picks a different state for each. */
export type ApiErrorKind = "unreachable" | "timeout" | "not_found" | "rate_limited" | "bad_request" | "server";

export class ApiError extends Error {
  constructor(
    public kind: ApiErrorKind,
    message: string,
    public status?: number,
    public retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
  /** The API is asleep (free-tier cold start) or down — show "waking the agents", not an error. */
  get isOffline() {
    return this.kind === "unreachable" || this.kind === "timeout" || this.status === 502 || this.status === 503;
  }
}

interface RequestOpts {
  method?: "GET" | "POST";
  body?: unknown;
  timeoutMs?: number;
  signal?: AbortSignal;
}

async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort("timeout"), opts.timeoutMs ?? 20_000);
  const onAbort = () => ctrl.abort(opts.signal?.reason);
  opts.signal?.addEventListener("abort", onAbort);
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: opts.method ?? "GET",
      headers: opts.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: ctrl.signal,
      cache: "no-store",
    });
  } catch (err) {
    if (opts.signal?.aborted) throw err;
    if (ctrl.signal.aborted) throw new ApiError("timeout", "The planner took too long to answer.");
    throw new ApiError("unreachable", "Can't reach the planner right now.");
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", onAbort);
  }

  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail.map((d: { msg?: string }) => d.msg ?? "").join("; ");
    } catch {
      /* non-JSON error body */
    }
    const kind: ApiErrorKind =
      res.status === 404 ? "not_found" : res.status === 429 ? "rate_limited" : res.status < 500 ? "bad_request" : "server";
    const retry = Number(res.headers.get("Retry-After"));
    throw new ApiError(kind, detail, res.status, Number.isFinite(retry) && retry > 0 ? retry : undefined);
  }
  return (await res.json()) as T;
}

export const api = {
  health: (signal?: AbortSignal) => request<{ status: string }>("/health", { timeoutMs: 8_000, signal }),
  ready: () => request<HealthReady>("/health/ready", { timeoutMs: 8_000 }),
  parseTrip: (text: string) =>
    request<TripRequest>("/api/trips/parse", { method: "POST", body: { text }, timeoutMs: 45_000 }),
  createTrip: (req: TripRequest) => request<{ trip_id: string }>("/api/trips", { method: "POST", body: req }),
  getTrip: (id: string, signal?: AbortSignal) => request<Trip>(`/api/trips/${encodeURIComponent(id)}`, { signal }),
  refine: (id: string, message: string) =>
    request<{ trip_id: string; revision: number }>(`/api/trips/${encodeURIComponent(id)}/refine`, {
      method: "POST",
      body: { message },
    }),
  listTrips: (clientId: string) =>
    request<TripSummary[]>(`/api/trips?client_id=${encodeURIComponent(clientId)}`, { timeoutMs: 12_000 }),
  destinations: () => request<CoveredDestination[]>("/api/destinations", { timeoutMs: 8_000 }),
  suggest: (q: string, signal?: AbortSignal) =>
    request<PlaceSuggestion[]>(`/api/places/suggest?q=${encodeURIComponent(q)}`, { timeoutMs: 8_000, signal }),
  streamUrl: (id: string) => `${API_URL}/api/trips/${encodeURIComponent(id)}/stream`,
};

/** Poll /health until the free-tier instance has woken up (Render cold start is ~30–60 s). */
export async function waitForApi(opts: { signal?: AbortSignal; maxMs?: number; onTick?: (elapsedMs: number) => void } = {}) {
  const start = Date.now();
  const max = opts.maxMs ?? 90_000;
  while (Date.now() - start < max) {
    if (opts.signal?.aborted) return false;
    try {
      await api.health(opts.signal);
      return true;
    } catch {
      opts.onTick?.(Date.now() - start);
      await new Promise((r) => setTimeout(r, 3_000));
    }
  }
  return false;
}
