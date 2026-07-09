"use client";
import { useEffect, useState } from "react";
import { api, PerformanceSummary, PerformanceSignal, PerformanceGroup, HorizonStats } from "@/lib/api";

const HORIZONS = ["1w", "1m", "3m"] as const;

function pct(v: number | null | undefined, signed = true) {
  if (v === null || v === undefined) return "—";
  const s = signed && v > 0 ? "+" : "";
  return `${s}${v.toFixed(1)}%`;
}

function retColor(v: number | null | undefined) {
  if (v === null || v === undefined) return "var(--text3)";
  return v >= 0 ? "var(--green)" : "var(--red)";
}

function HorizonCells({ stats }: { stats: HorizonStats | null }) {
  if (!stats) return (
    <>
      <td style={{ color: "var(--text3)" }}>—</td>
      <td style={{ color: "var(--text3)" }}>—</td>
      <td style={{ color: "var(--text3)" }}>—</td>
    </>
  );
  return (
    <>
      <td style={{ color: retColor(stats.avg_return), fontFamily: "var(--mono)" }}>{pct(stats.avg_return)}</td>
      <td style={{ fontFamily: "var(--mono)" }}>{stats.win_rate.toFixed(0)}% <span style={{ color: "var(--text3)" }}>({stats.n})</span></td>
      <td style={{ color: retColor(stats.avg_alpha), fontFamily: "var(--mono)" }}>{pct(stats.avg_alpha)}</td>
    </>
  );
}

function GroupTable({ title, groups }: { title: string; groups: Record<string, PerformanceGroup> }) {
  const keys = Object.keys(groups);
  if (keys.length === 0) return null;
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-header"><span className="card-title">{title}</span></div>
      <div style={{ overflowX: "auto" }}>
        <table className="table" style={{ width: "100%", fontSize: 12 }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}></th>
              {HORIZONS.map(h => (
                <th key={h} colSpan={3} style={{ textAlign: "left", borderLeft: "1px solid var(--border)", paddingLeft: 8 }}>{h}</th>
              ))}
            </tr>
            <tr style={{ color: "var(--text3)", fontSize: 10, textTransform: "uppercase" }}>
              <th style={{ textAlign: "left" }}>Group</th>
              {HORIZONS.map(h => (
                <HeaderTriplet key={h} />
              ))}
            </tr>
          </thead>
          <tbody>
            {keys.map(k => (
              <tr key={k}>
                <td style={{ fontFamily: "var(--mono)", fontWeight: 500 }}>{k}</td>
                {HORIZONS.map(h => <HorizonCells key={h} stats={groups[k][h]} />)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HeaderTriplet() {
  return (
    <>
      <th style={{ textAlign: "left", borderLeft: "1px solid var(--border)", paddingLeft: 8 }}>Avg ret</th>
      <th style={{ textAlign: "left" }}>Win rate</th>
      <th style={{ textAlign: "left" }}>α vs SPUS</th>
    </>
  );
}

export default function PerformancePage() {
  const [summary, setSummary] = useState<PerformanceSummary | null>(null);
  const [recent, setRecent]   = useState<PerformanceSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [toast, setToast]     = useState("");

  const load = () =>
    Promise.all([api.performance.summary(), api.performance.signals(50)])
      .then(([s, r]) => { setSummary(s); setRecent(r); })
      .catch(console.error)
      .finally(() => setLoading(false));

  useEffect(() => { load(); }, []);

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 3500); };

  const runUpdate = async () => {
    setUpdating(true);
    try {
      const res = await api.performance.update();
      showToast(`Updated ${res.updated} of ${res.eligible} eligible signals.`);
      await load();
    } catch {
      showToast("Update failed.");
    } finally {
      setUpdating(false);
    }
  };

  if (loading) return (
    <div>
      <div className="page-header">
        <div className="skeleton" style={{ width: 240, height: 32, marginBottom: 8 }} />
        <div className="skeleton" style={{ width: 320, height: 14 }} />
      </div>
      <div className="skeleton" style={{ height: 160 }} />
    </div>
  );

  const overall1m = summary?.overall?.["1m"];

  return (
    <div>
      <div className="page-header" style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <h1 className="page-title">Signal performance</h1>
          <p className="page-sub">
            Forward returns per signal vs {summary?.benchmark || "SPUS"} — do the signals actually beat the halal index?
          </p>
        </div>
        <button className="btn btn-ghost" onClick={runUpdate} disabled={updating}>
          {updating ? "Updating..." : "↻ Update returns"}
        </button>
      </div>

      {(!summary || summary.total_tracked === 0) ? (
        <div className="card">
          <p style={{ color: "var(--text3)", fontSize: 13, lineHeight: 1.7 }}>
            No measurable signals yet. Signals become trackable one week after they fire —
            keep the morning job running and check back. Returns update nightly at 17:30 ET
            (or press “Update returns”).
          </p>
        </div>
      ) : (
        <>
          <div className="grid-4" style={{ marginBottom: 24 }}>
            <div className="card">
              <div className="stat-label">Signals tracked</div>
              <div className="stat-value">{summary.total_tracked}</div>
            </div>
            <div className="card">
              <div className="stat-label">Avg 1-month return</div>
              <div className="stat-value" style={{ color: retColor(overall1m?.avg_return ?? null) }}>{pct(overall1m?.avg_return ?? null)}</div>
            </div>
            <div className="card">
              <div className="stat-label">1-month win rate</div>
              <div className="stat-value">{overall1m ? `${overall1m.win_rate.toFixed(0)}%` : "—"}</div>
            </div>
            <div className="card">
              <div className="stat-label">Avg 1-month α vs {summary.benchmark}</div>
              <div className="stat-value" style={{ color: retColor(overall1m?.avg_alpha ?? null) }}>{pct(overall1m?.avg_alpha ?? null)}</div>
              <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 4, fontFamily: "var(--mono)" }}>
                negative = index wins
              </div>
            </div>
          </div>

          <GroupTable title="By signal type" groups={summary.by_type} />
          <GroupTable title="By confidence bucket" groups={summary.by_confidence} />

          <div className="card">
            <div className="card-header"><span className="card-title">Recent tracked signals</span></div>
            <div style={{ overflowX: "auto" }}>
              <table className="table" style={{ width: "100%", fontSize: 12 }}>
                <thead>
                  <tr style={{ color: "var(--text3)", fontSize: 10, textTransform: "uppercase" }}>
                    <th style={{ textAlign: "left" }}>Symbol</th>
                    <th style={{ textAlign: "left" }}>Type</th>
                    <th style={{ textAlign: "left" }}>Conf</th>
                    <th style={{ textAlign: "left" }}>Fired</th>
                    <th style={{ textAlign: "left" }}>1w</th>
                    <th style={{ textAlign: "left" }}>1m</th>
                    <th style={{ textAlign: "left" }}>3m</th>
                    <th style={{ textAlign: "left" }}>α 1m</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map((r, i) => (
                    <tr key={`${r.symbol}-${r.triggered_at}-${i}`}>
                      <td style={{ fontFamily: "var(--mono)", fontWeight: 500 }}>{r.symbol}</td>
                      <td><span className={`badge ${r.type === "buy" ? "badge-green" : r.type === "sell" ? "badge-red" : "badge-muted"}`}>{r.type}</span></td>
                      <td style={{ fontFamily: "var(--mono)" }}>{r.confidence !== null ? `${(r.confidence * 100).toFixed(0)}%` : "—"}</td>
                      <td style={{ fontFamily: "var(--mono)", color: "var(--text3)" }}>{new Date(r.triggered_at).toLocaleDateString()}</td>
                      <td style={{ fontFamily: "var(--mono)", color: retColor(r.return_1w) }}>{pct(r.return_1w)}</td>
                      <td style={{ fontFamily: "var(--mono)", color: retColor(r.return_1m) }}>{pct(r.return_1m)}</td>
                      <td style={{ fontFamily: "var(--mono)", color: retColor(r.return_3m) }}>{pct(r.return_3m)}</td>
                      <td style={{ fontFamily: "var(--mono)", color: retColor(r.alpha_1m) }}>{pct(r.alpha_1m)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
