"use client";
import { useEffect, useState } from "react";

interface DiscoveryPick {
  symbol:           string;
  signal:           string;
  confidence:       number;
  reasoning:        string;
  price:            number;
  change_pct:       number;
  catalysts:        string[];
  risks:            string[];
  suggested_action: string;
}

interface DiscoveryResult {
  top_picks: DiscoveryPick[];
  summary:   string;
  screened:  number;
  compliant: number;
  run_at:    string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function DiscoverPage() {
  const [result, setResult]   = useState<DiscoveryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded]   = useState(false);
  const [topN, setTopN]       = useState(10);
  const [toast, setToast]     = useState("");

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 3000); };

  const runDiscovery = async (forceRefresh = false) => {
    setLoading(true);
    try {
      const url = forceRefresh
        ? `${API_URL}/api/discover/refresh?top_n=${topN}`
        : `${API_URL}/api/discover?top_n=${topN}`;
      const method = forceRefresh ? "POST" : "GET";
      const res = await fetch(url, { method });
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const data = await res.json();
      setResult(data);
      setLoaded(true);
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : "Discovery failed");
    } finally {
      setLoading(false);
    }
  };

  // Load cached result on mount
  useEffect(() => { runDiscovery(false); }, []);

  const signalColor: Record<string, string> = {
    buy:   "var(--green)",
    watch: "var(--amber)",
    avoid: "var(--red)",
  };

  const signalBadgeClass: Record<string, string> = {
    buy:   "badge-green",
    watch: "badge-amber",
    avoid: "badge-red",
  };

  return (
    <div>
      {/* Header */}
      <div className="page-header" style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <h1 className="page-title">Discover</h1>
          <p className="page-sub">
            AI-powered halal stock discovery · scans {result?.screened || "~100"} stocks · 
            {result?.compliant ? ` ${result.compliant} halal-compliant` : " screening universe"}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select
            value={topN}
            onChange={e => setTopN(Number(e.target.value))}
            style={{ background: "var(--bg3)", border: "1px solid var(--border2)", color: "var(--text)", borderRadius: "var(--radius)", padding: "7px 12px", fontFamily: "var(--mono)", fontSize: 12, cursor: "pointer" }}
          >
            {[5, 10, 15, 20].map(n => <option key={n} value={n}>Top {n}</option>)}
          </select>
          <button className="btn btn-ghost" onClick={() => runDiscovery(false)} disabled={loading}>
            {loading ? "Scanning..." : "↻ Refresh"}
          </button>
          <button className="btn btn-primary" onClick={() => runDiscovery(true)} disabled={loading}>
            {loading ? "Scanning..." : "⚡ Force scan"}
          </button>
        </div>
      </div>

      {/* Info banner */}
      <div style={{ background: "var(--blue-dim)", border: "1px solid var(--blue)", borderRadius: "var(--radius)", padding: "10px 16px", marginBottom: 24, display: "flex", gap: 10, alignItems: "flex-start" }}>
        <span style={{ color: "var(--blue)", fontSize: 14 }}>ℹ</span>
        <p style={{ fontSize: 12, color: "var(--text2)", lineHeight: 1.6 }}>
          Discovery scans a curated universe of ~{HALAL_UNIVERSE_COUNT} Shariah-compliant stocks from SPUS/HLAL ETF holdings. 
          Results are cached for 1 hour. Click <strong style={{ color: "var(--text)" }}>Force scan</strong> for fresh analysis. 
          All suggestions are for <strong style={{ color: "var(--text)" }}>passive long-term investing</strong> only.
        </p>
      </div>

      {/* Loading state */}
      {loading && !loaded && (
        <div>
          <div style={{ textAlign: "center", padding: "48px 0" }}>
            <div style={{ fontFamily: "var(--mono)", fontSize: 13, color: "var(--text3)", marginBottom: 16 }}>
              Scanning halal universe · screening compliance · running Claude analysis...
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 600, margin: "0 auto" }}>
              {[0,1,2,3,4].map(i => <div key={i} className="skeleton" style={{ height: 140 }} />)}
            </div>
          </div>
        </div>
      )}

      {/* Summary */}
      {loaded && result && (
        <>
          {result.summary && (
            <div className="card" style={{ marginBottom: 24 }}>
              <div className="card-header">
                <span className="card-title">Today's market overview</span>
                {result.run_at && (
                  <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--text3)" }}>
                    {new Date(result.run_at).toLocaleTimeString()}
                  </span>
                )}
              </div>
              <p style={{ fontSize: 13, color: "var(--text2)", lineHeight: 1.75 }}>{result.summary}</p>
              <div style={{ display: "flex", gap: 16, marginTop: 16 }}>
                <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--text3)" }}>
                  <span style={{ color: "var(--text)", fontWeight: 500 }}>{result.screened}</span> stocks scanned
                </div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--text3)" }}>
                  <span style={{ color: "var(--green)", fontWeight: 500 }}>{result.compliant}</span> halal compliant
                </div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--text3)" }}>
                  <span style={{ color: "var(--blue)", fontWeight: 500 }}>{result.top_picks?.length || 0}</span> top picks
                </div>
              </div>
            </div>
          )}

          {/* Top picks */}
          {(result.top_picks?.length || 0) === 0 ? (
            <div className="card" style={{ textAlign: "center", padding: 48 }}>
              <p style={{ color: "var(--text3)", fontFamily: "var(--mono)", fontSize: 13 }}>
                No picks available. Try force scanning for fresh results.
              </p>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {result.top_picks.map((pick, idx) => (
                <div
                  key={pick.symbol}
                  className="card"
                  style={{
                    borderLeft: `3px solid ${signalColor[pick.signal] || "var(--text3)"}`,
                    padding: "20px 24px",
                  }}
                >
                  {/* Top row */}
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 16, marginBottom: 12 }}>
                    {/* Rank */}
                    <div style={{
                      fontFamily: "var(--mono)", fontSize: 11, color: "var(--text3)",
                      background: "var(--bg3)", borderRadius: "var(--radius)",
                      padding: "4px 8px", flexShrink: 0, marginTop: 2,
                    }}>
                      #{idx + 1}
                    </div>

                    {/* Symbol + badges */}
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                        <span style={{ fontFamily: "var(--mono)", fontWeight: 500, fontSize: 20 }}>
                          {pick.symbol}
                        </span>
                        <span className={`badge ${signalBadgeClass[pick.signal] || "badge-muted"}`}>
                          {pick.signal}
                        </span>
                        <span className="badge badge-green">halal ✓</span>
                        {pick.change_pct !== undefined && (
                          <span style={{
                            fontFamily: "var(--mono)", fontSize: 12,
                            color: pick.change_pct >= 0 ? "var(--green)" : "var(--red)",
                          }}>
                            {pick.change_pct >= 0 ? "▲" : "▼"} {Math.abs(pick.change_pct).toFixed(2)}%
                          </span>
                        )}
                      </div>

                      {/* Reasoning */}
                      <p style={{ fontSize: 13, color: "var(--text2)", lineHeight: 1.65, marginBottom: 12 }}>
                        {pick.reasoning}
                      </p>

                      {/* Catalysts + Risks */}
                      <div className="grid-2" style={{ gap: 12, marginBottom: 12 }}>
                        {pick.catalysts?.length > 0 && (
                          <div style={{ background: "var(--green-dim)", borderRadius: "var(--radius)", padding: "10px 12px" }}>
                            <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--green)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                              Catalysts
                            </div>
                            {pick.catalysts.map((c, i) => (
                              <div key={i} style={{ fontSize: 12, color: "var(--text2)", marginBottom: 3 }}>
                                ↑ {c}
                              </div>
                            ))}
                          </div>
                        )}
                        {pick.risks?.length > 0 && (
                          <div style={{ background: "var(--red-dim)", borderRadius: "var(--radius)", padding: "10px 12px" }}>
                            <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--red)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                              Risks
                            </div>
                            {pick.risks.map((r, i) => (
                              <div key={i} style={{ fontSize: 12, color: "var(--text2)", marginBottom: 3 }}>
                                ↓ {r}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>

                      {/* Suggested action */}
                      {pick.suggested_action && (
                        <div style={{ background: "var(--bg3)", borderRadius: "var(--radius)", padding: "8px 12px", borderLeft: "2px solid var(--border2)" }}>
                          <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                            Suggested action:{" "}
                          </span>
                          <span style={{ fontSize: 12, color: "var(--text2)" }}>{pick.suggested_action}</span>
                        </div>
                      )}
                    </div>

                    {/* Right: price + confidence */}
                    <div style={{ textAlign: "right", flexShrink: 0 }}>
                      {pick.price && (
                        <div style={{ fontFamily: "var(--mono)", fontSize: 22, fontWeight: 500, marginBottom: 4 }}>
                          ${pick.price.toFixed(2)}
                        </div>
                      )}
                      {pick.confidence && (
                        <div>
                          <div style={{
                            fontFamily: "var(--mono)", fontSize: 28, fontWeight: 500,
                            color: signalColor[pick.signal] || "var(--text)",
                            lineHeight: 1,
                          }}>
                            {(pick.confidence * 100).toFixed(0)}
                            <span style={{ fontSize: 13, color: "var(--text3)" }}>%</span>
                          </div>
                          <div style={{ fontSize: 10, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.06em", marginTop: 2 }}>
                            confidence
                          </div>
                          <div className="conf-bar" style={{ marginTop: 6, width: 60, marginLeft: "auto" }}>
                            <div className="conf-fill" style={{
                              width: `${pick.confidence * 100}%`,
                              background: signalColor[pick.signal] || "var(--text3)",
                            }} />
                          </div>
                        </div>
                      )}

                      {/* Add to watchlist button */}
                      <button
                        className="btn btn-ghost"
                        style={{ marginTop: 12, fontSize: 11, padding: "5px 10px" }}
                        onClick={() => addToWatchlist(pick.symbol, showToast)}
                      >
                        + Watchlist
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const HALAL_UNIVERSE_COUNT = 100;

async function addToWatchlist(symbol: string, showToast: (msg: string) => void) {
  try {
    const res = await fetch(`${API_URL}/api/watchlist`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol }),
    });
    if (res.status === 409) { showToast(`${symbol} already on watchlist`); return; }
    if (!res.ok) {
      const err = await res.json();
      showToast(err.detail || `Failed to add ${symbol}`);
      return;
    }
    showToast(`✓ ${symbol} added to watchlist`);
  } catch {
    showToast(`Failed to add ${symbol}`);
  }
}
