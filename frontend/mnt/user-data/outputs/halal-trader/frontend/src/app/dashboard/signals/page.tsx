"use client";
import { useEffect, useState } from "react";
import { api, Signal } from "@/lib/api";

const TYPES = ["all", "buy", "sell", "watch", "avoid"];

export default function SignalsPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [filter, setFilter]   = useState("all");
  const [days, setDays]       = useState(7);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.signals.list(days)
      .then(setSignals)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [days]);

  const filtered = filter === "all" ? signals : signals.filter(s => s.type === filter);

  const typeColor: Record<string, string> = {
    buy: "var(--green)", sell: "var(--red)",
    watch: "var(--amber)", avoid: "var(--text3)",
  };

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Signals</h1>
        <p className="page-sub">Claude-generated research signals — for reference only, not financial advice</p>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 8, marginBottom: 20, alignItems: "center" }}>
        {TYPES.map(t => (
          <button
            key={t}
            className={`btn ${filter === t ? "btn-primary" : "btn-ghost"}`}
            style={filter !== t ? {} : {}}
            onClick={() => setFilter(t)}
          >
            {t}
          </button>
        ))}
        <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
          <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--text3)" }}>Days:</span>
          {[1, 7, 14, 30].map(d => (
            <button
              key={d}
              className={`btn ${days === d ? "btn-ghost" : "btn-ghost"}`}
              style={{
                padding: "5px 10px",
                color: days === d ? "var(--green)" : "var(--text3)",
                borderColor: days === d ? "var(--green)" : "var(--border)",
              }}
              onClick={() => setDays(d)}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* Signals list */}
      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {[0,1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 110 }} />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 40 }}>
          <p style={{ color: "var(--text3)", fontFamily: "var(--mono)", fontSize: 13 }}>
            No signals found. Run the morning job to generate signals.
          </p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {filtered.map(s => (
            <div key={s.id} className={`signal-card ${s.type}`}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                {/* Left */}
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <span style={{ fontFamily: "var(--mono)", fontWeight: 500, fontSize: 16 }}>
                      {s.symbol}
                    </span>
                    <span className={`badge badge-${s.type === "buy" ? "green" : s.type === "sell" ? "red" : s.type === "watch" ? "amber" : "muted"}`}>
                      {s.type}
                    </span>
                    {s.acted_on && (
                      <span className="badge badge-blue">acted on</span>
                    )}
                  </div>
                  <p style={{ fontSize: 13, color: "var(--text2)", lineHeight: 1.65 }}>
                    {s.reasoning}
                  </p>
                </div>

                {/* Right */}
                <div style={{ textAlign: "right", flexShrink: 0 }}>
                  {s.confidence && (
                    <div>
                      <div style={{
                        fontFamily: "var(--mono)", fontSize: 22, fontWeight: 500,
                        color: typeColor[s.type] || "var(--text)",
                      }}>
                        {(s.confidence * 100).toFixed(0)}
                        <span style={{ fontSize: 12, color: "var(--text3)" }}>%</span>
                      </div>
                      <div style={{ fontSize: 10, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        confidence
                      </div>
                    </div>
                  )}
                  {s.price_at && (
                    <div style={{ marginTop: 6, fontFamily: "var(--mono)", fontSize: 12, color: "var(--text3)" }}>
                      ${s.price_at.toFixed(2)}
                    </div>
                  )}
                  <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4, fontFamily: "var(--mono)" }}>
                    {new Date(s.triggered_at).toLocaleDateString()}
                  </div>
                </div>
              </div>

              {/* Confidence bar */}
              {s.confidence && (
                <div style={{ marginTop: 10 }}>
                  <div className="conf-bar">
                    <div className="conf-fill" style={{
                      width: `${s.confidence * 100}%`,
                      background: typeColor[s.type] || "var(--text3)",
                    }} />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
