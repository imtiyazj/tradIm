const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
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

export const api = {
  health: () => apiFetch<HealthResponse>("/health"),
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
};
