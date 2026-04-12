"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface TaxSummary {
  short_term_gains: number;
  long_term_gains:  number;
  total_realized:   number;
  quarterly_estimate: number;
  harvesting_opportunities: { symbol: string; unrealized_loss: number; note: string }[];
  schedule_d_rows: {
    symbol: string; acquired: string; sold: string;
    proceeds: number; cost_basis: number; gain_loss: number; term: string;
  }[];
  notes: string;
  error?: string;
}

export default function TaxPage() {
  const [year, setYear]       = useState(new Date().getFullYear());
  const [summary, setSummary] = useState<TaxSummary | null>(null);
  const [count, setCount]     = useState(0);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded]   = useState(false);

  const loadTax = () => {
    setLoading(true);
    api.reports.list(1).then(() => {}); // warm up
    fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/tax/summary?year=${year}`)
      .then(r => r.json())
      .then(data => {
        setSummary(data.summary);
        setCount(data.trade_count);
        setLoaded(true);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  const totalGains = (summary?.short_term_gains ?? 0) + (summary?.long_term_gains ?? 0);

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Tax summary</h1>
        <p className="page-sub">CPA-ready report · supplements but does not replace your broker 1099-B</p>
      </div>

      {/* Year selector */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--text2)" }}>Tax year:</span>
          {[new Date().getFullYear(), new Date().getFullYear() - 1].map(y => (
            <button
              key={y}
              className={`btn ${year === y ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setYear(y)}
            >
              {y}
            </button>
          ))}
          <button className="btn btn-ghost" onClick={loadTax} disabled={loading} style={{ marginLeft: "auto" }}>
            {loading ? "Generating..." : "Generate report"}
          </button>
        </div>
      </div>

      {!loaded && !loading && (
        <div className="card" style={{ textAlign: "center", padding: 48 }}>
          <p style={{ color: "var(--text3)", fontFamily: "var(--mono)", fontSize: 13 }}>
            Click "Generate report" to run Claude's tax analysis
          </p>
        </div>
      )}

      {loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="skeleton" style={{ height: 100 }} />
          <div className="skeleton" style={{ height: 200 }} />
        </div>
      )}

      {loaded && summary && !summary.error && (
        <>
          {/* Summary stats */}
          <div className="grid-4" style={{ marginBottom: 24 }}>
            <div className="card">
              <div className="stat-label">Short-term gains</div>
              <div className="stat-value" style={{ color: (summary.short_term_gains ?? 0) >= 0 ? "var(--green)" : "var(--red)", fontSize: 22 }}>
                ${(summary.short_term_gains ?? 0).toFixed(2)}
              </div>
              <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4, fontFamily: "var(--mono)" }}>Taxed as ordinary income</div>
            </div>
            <div className="card">
              <div className="stat-label">Long-term gains</div>
              <div className="stat-value" style={{ color: (summary.long_term_gains ?? 0) >= 0 ? "var(--green)" : "var(--red)", fontSize: 22 }}>
                ${(summary.long_term_gains ?? 0).toFixed(2)}
              </div>
              <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4, fontFamily: "var(--mono)" }}>Preferred tax rate</div>
            </div>
            <div className="card">
              <div className="stat-label">Total realized</div>
              <div className="stat-value" style={{ fontSize: 22 }}>${totalGains.toFixed(2)}</div>
              <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4, fontFamily: "var(--mono)" }}>{count} trades logged</div>
            </div>
            <div className="card">
              <div className="stat-label">Quarterly estimate</div>
              <div className="stat-value" style={{ color: "var(--amber)", fontSize: 22 }}>
                ${(summary.quarterly_estimate ?? 0).toFixed(2)}
              </div>
              <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4, fontFamily: "var(--mono)" }}>Form 1040-ES</div>
            </div>
          </div>

          {/* Harvesting opportunities */}
          {(summary.harvesting_opportunities?.length ?? 0) > 0 && (
            <div className="card" style={{ marginBottom: 24 }}>
              <div className="card-header">
                <span className="card-title">Tax-loss harvesting opportunities</span>
                <span className="badge badge-amber">{summary.harvesting_opportunities.length} found</span>
              </div>
              {summary.harvesting_opportunities.map(h => (
                <div key={h.symbol} style={{
                  display: "flex", justifyContent: "space-between", alignItems: "flex-start",
                  padding: "10px 0", borderBottom: "1px solid var(--border)",
                }}>
                  <div>
                    <span style={{ fontFamily: "var(--mono)", fontWeight: 500 }}>{h.symbol}</span>
                    <p style={{ fontSize: 12, color: "var(--text2)", marginTop: 4 }}>{h.note}</p>
                  </div>
                  <span style={{ fontFamily: "var(--mono)", color: "var(--red)", fontSize: 14 }}>
                    -${Math.abs(h.unrealized_loss).toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Schedule D rows */}
          {(summary.schedule_d_rows?.length ?? 0) > 0 && (
            <div className="card" style={{ marginBottom: 24 }}>
              <div className="card-header">
                <span className="card-title">Schedule D summary</span>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Symbol</th><th>Acquired</th><th>Sold</th>
                    <th>Proceeds</th><th>Cost basis</th><th>Gain/loss</th><th>Term</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.schedule_d_rows.map((row, i) => (
                    <tr key={i}>
                      <td><span style={{ fontFamily: "var(--mono)", fontWeight: 500 }}>{row.symbol}</span></td>
                      <td><span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{row.acquired}</span></td>
                      <td><span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{row.sold}</span></td>
                      <td><span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>${row.proceeds.toFixed(2)}</span></td>
                      <td><span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>${row.cost_basis.toFixed(2)}</span></td>
                      <td>
                        <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: row.gain_loss >= 0 ? "var(--green)" : "var(--red)" }}>
                          {row.gain_loss >= 0 ? "+" : ""}${row.gain_loss.toFixed(2)}
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${row.term === "long" ? "badge-green" : "badge-amber"}`}>
                          {row.term}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Notes */}
          {summary.notes && (
            <div className="card">
              <div className="card-header"><span className="card-title">Notes from Claude</span></div>
              <p style={{ fontSize: 13, color: "var(--text2)", lineHeight: 1.7 }}>{summary.notes}</p>
              <p style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--mono)", marginTop: 12 }}>
                ⚠ This report supplements but does not replace your broker-issued 1099-B. Always review with a CPA before filing.
              </p>
            </div>
          )}
        </>
      )}

      {loaded && summary?.error && (
        <div className="card">
          <p style={{ color: "var(--red)", fontFamily: "var(--mono)", fontSize: 12 }}>{summary.error}</p>
        </div>
      )}
    </div>
  );
}
