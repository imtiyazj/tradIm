const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Auth ──────────────────────────────────────────────────────────────────────
// The dashboard layout registers Clerk's getToken() here so every API call
// carries a verified session token. Registered during render (not in an
// effect) so child components' data fetches already have it.

let getAuthToken: (() => Promise<string | null>) | null = null;

export function setAuthTokenGetter(fn: () => Promise<string | null>) {
  getAuthToken = fn;
}

/** fetch() wrapper that attaches the Clerk bearer token. Use for any direct
 *  calls that don't go through the typed `api` client below. */
export async function authFetch(input: string, options?: RequestInit): Promise<Response> {
  const token = getAuthToken ? await getAuthToken().catch(() => null) : null;
  return fetch(input, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options?.headers || {}),
    },
  });
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await authFetch(`${API_URL}${path}`, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `API error ${res.status}`);
  }
  return res.json();
}

export interface HealthResponse { status: string; timestamp: string; alpaca_mode: string; }
export interface WatchlistItem { id: string; symbol: string; notes: string | null; added_at: string; }
export interface HalalScreenResult { symbol: string; zoya_status: string; final_status: string; sector: string; debt_ratio: number | null; interest_income_pct: number | null; haram_revenue_pct: number | null; ratio_pass: boolean | null; notes: string; from_cache: boolean; }
export interface Signal { id: string; symbol: string; type: string; confidence: number | null; reasoning: string; price_at: number | null; triggered_at: string; acted_on: boolean; }
export interface Position { symbol: string; qty: string; avg_entry_price: string; current_price: string; unrealized_pl: string; unrealized_plpc: string; market_value: string; side: string; }
export interface PortfolioResponse { positions: Position[]; count: number; alpaca_mode: string; }
export interface DailyReport { id: string; report_date: string; stocks_screened: number; halal_passed: number; signals_fired: number; trades_executed: number; alerts_sent: number; summary: string; }
export interface HorizonStats { n: number; avg_return: number; win_rate: number; avg_alpha: number | null; }
export interface PerformanceGroup { "1w": HorizonStats | null; "1m": HorizonStats | null; "3m": HorizonStats | null; }
export interface PerformanceSummary { total_tracked: number; benchmark: string; overall: PerformanceGroup; by_type: Record<string, PerformanceGroup>; by_confidence: Record<string, PerformanceGroup>; }
export interface PerformanceSignal { symbol: string; type: string; confidence: number | null; price_at: number | null; triggered_at: string; return_1w: number | null; return_1m: number | null; return_3m: number | null; alpha_1m: number | null; }
export interface ComplianceCheck { id: string; period: string; symbol: string; previous_status: string | null; new_status: string; status_changed: boolean; inconclusive: boolean; is_held: boolean; quantity: number | null; market_value: number | null; debt_ratio: number | null; haram_revenue_pct: number | null; notes: string | null; checked_at: string; }
export interface ComplianceReview { run_id: string; period: string; checked_at: string; checked: number; held: number; action_required: ComplianceCheck[]; review: ComplianceCheck[]; changed: ComplianceCheck[]; inconclusive: string[]; rows: ComplianceCheck[]; }
export interface ComplianceLatest { review: ComplianceReview | null; changes: ComplianceCheck[]; }
export interface PurificationEntry { id: string; symbol: string; income_date: string; income_amount: number; impure_pct: number; rate_source: string; purification_amount: number; is_paid: boolean; paid_at: string | null; note: string | null; }
export interface PurificationYear { year: number; dividends: number; owed: number; paid: number; outstanding: number; }
export interface PurificationSummary { paper: boolean; total_dividends: number; total_owed: number; total_paid: number; outstanding: number; estimated_count: number; by_year: PurificationYear[]; entries: PurificationEntry[]; }

export const api = {
  health: () => apiFetch<HealthResponse>("/health"),
  auth: {
    sync: (clerkId: string, email: string) =>
      apiFetch<{ id: string; email: string; created: boolean }>("/api/auth/sync", {
        method: "POST",
        body: JSON.stringify({ clerk_id: clerkId, email }),
      }),
  },
  watchlist: {
    list: () => apiFetch<WatchlistItem[]>("/api/watchlist"),
    add: (symbol: string, notes?: string) => apiFetch<WatchlistItem>("/api/watchlist", { method: "POST", body: JSON.stringify({ symbol, notes }) }),
    remove: (symbol: string) => apiFetch<{ message: string }>(`/api/watchlist/${symbol}`, { method: "DELETE" }),
  },
  halal: {
    screen: (symbol: string, forceRefresh = false) => apiFetch<HalalScreenResult>(`/api/screen/${symbol}?force_refresh=${forceRefresh}`),
    clearCache: (symbol: string) => apiFetch<{ message: string }>(`/api/screen/cache/${symbol}`, { method: "DELETE" }),
  },
  signals: { list: (days = 7) => apiFetch<Signal[]>(`/api/signals?days=${days}`) },
  portfolio: { get: () => apiFetch<PortfolioResponse>("/api/portfolio") },
  reports: { list: (limit = 30) => apiFetch<DailyReport[]>(`/api/reports?limit=${limit}`) },
  scheduler: { run: () => apiFetch<{ message: string }>("/api/scheduler/run", { method: "POST" }) },
  performance: {
    summary: () => apiFetch<PerformanceSummary>("/api/performance/summary"),
    signals: (limit = 50) => apiFetch<PerformanceSignal[]>(`/api/performance/signals?limit=${limit}`),
    update:  () => apiFetch<{ eligible: number; updated: number; skipped: number }>("/api/performance/update", { method: "POST" }),
  },
  compliance: {
    latest: () => apiFetch<ComplianceLatest>("/api/compliance/latest"),
    run:    () => apiFetch<{ message: string }>("/api/compliance/run", { method: "POST" }),
  },
  purification: {
    get:         () => apiFetch<PurificationSummary>("/api/purification"),
    sync:        () => apiFetch<{ fetched: number; added: number; skipped: number; new_purification: number }>("/api/purification/sync", { method: "POST" }),
    setPaid:     (id: string, isPaid: boolean) => apiFetch<PurificationEntry>(`/api/purification/${id}`, { method: "PATCH", body: JSON.stringify({ is_paid: isPaid }) }),
    markAllPaid: () => apiFetch<{ marked: number; amount: number }>("/api/purification/mark-all-paid", { method: "POST" }),
  },
};
