"use client";
import { useEffect, useState } from "react";
import { api, Signal } from "@/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Technicals + Earnings shapes ──────────────────────────────────────────────

interface TechIndicators {
  rsi: number;
  rsi_signal: "oversold" | "neutral" | "overbought";
  macd_trend: "bullish" | "bearish" | "neutral";
  verdict: "bullish" | "bearish" | "neutral";
}
interface EarningsInfo {
  days_until: number | null;
  next_date: string | null;
  imminent: boolean;
}

// ── Trade size shape returned by /api/trade/size ──────────────────────────────

interface SizeInfo {
  dollars:         number;
  shares:          number;
  stop_loss:       number;
  take_profit:     number;
  portfolio_pct:   number;
  confidence_tier: string;
  tradeable:       boolean;
  symbol:          string;
  price:           number;
  portfolio_value: number;
  paper:           boolean;
}

// ── Execute modal ─────────────────────────────────────────────────────────────

interface ExecuteModalProps {
  signal:   Signal;
  onClose:  () => void;
  showToast: (msg: string) => void;
}

function ExecuteModal({ signal, onClose, showToast }: ExecuteModalProps) {
  const [sizeInfo, setSizeInfo]   = useState<SizeInfo | null>(null);
  const [sizeErr, setSizeErr]     = useState<string>("");
  const [loadingSize, setLoadingSize] = useState(true);
  const [placing, setPlacing]     = useState(false);

  const confidence = signal.confidence ?? 0;

  useEffect(() => {
    if (confidence < 0.65) {
      setLoadingSize(false);
      setSizeErr("Signal below minimum confidence (65%)");
      return;
    }
    setLoadingSize(true);
    setSizeErr("");
    fetch(`${API_URL}/api/trade/size?symbol=${signal.symbol}&confidence=${confidence}`)
      .then(r => r.json())
      .then(data => {
        if (data.detail) { setSizeErr(data.detail); }
        else              { setSizeInfo(data as SizeInfo); }
      })
      .catch(() => setSizeErr("Failed to fetch position size"))
      .finally(() => setLoadingSize(false));
  }, [signal.symbol, confidence]);

  const execute = async () => {
    if (!sizeInfo) return;
    setPlacing(true);
    try {
      const res = await fetch(`${API_URL}/api/trade`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          symbol:      signal.symbol,
          qty:         sizeInfo.shares,
          side:        "buy",
          confidence:  confidence,
          auto_size:   false,   // qty already calculated
          use_bracket: true,
        }),
      });
      const data = await res.json();
      if (!res.ok) { showToast(data.detail || "Order failed"); return; }
      showToast(
        `✓ Paper BUY ${sizeInfo.shares} ${signal.symbol} @ $${sizeInfo.price.toFixed(2)} — order ${data.order_id?.slice(0, 8)}…`
      );
      onClose();
    } catch {
      showToast("Order failed — check backend logs");
    } finally {
      setPlacing(false);
    }
  };

  return (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "var(--bg2)", border: "1px solid var(--border2)",
          borderRadius: "var(--radius)", padding: 28, minWidth: 360, maxWidth: 440,
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ fontFamily: "var(--mono)", fontWeight: 600, fontSize: 16, marginBottom: 4 }}>
          📈 Execute Signal — {signal.symbol}{" "}
          <span className="badge badge-green">BUY</span>{" "}
          {signal.confidence != null && (
            <span style={{ color: "var(--green)" }}>{(confidence * 100).toFixed(0)}%</span>
          )}
        </div>
        <div style={{ height: 1, background: "var(--border2)", margin: "12px 0" }} />

        {/* Body */}
        {loadingSize ? (
          <div style={{ padding: "24px 0", textAlign: "center" }}>
            <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--text3)" }}>
              Calculating position size…
            </div>
            <div className="skeleton" style={{ height: 14, marginTop: 12, borderRadius: 4 }} />
            <div className="skeleton" style={{ height: 14, marginTop: 8, borderRadius: 4 }} />
          </div>
        ) : sizeErr ? (
          <div style={{ padding: "16px 0", fontFamily: "var(--mono)", fontSize: 13, color: "var(--red)" }}>
            {sizeErr}
          </div>
        ) : sizeInfo && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Row label="Confidence tier"     value={sizeInfo.confidence_tier} />
            <Row
              label="Portfolio allocation"
              value={`${sizeInfo.portfolio_pct}% ($${sizeInfo.dollars.toFixed(2)})`}
            />
            <Row
              label="Shares to buy"
              value={`~${sizeInfo.shares} shares @ $${sizeInfo.price.toFixed(2)}`}
            />

            <div style={{ height: 1, background: "var(--border2)", margin: "4px 0" }} />

            <Row
              label="Stop-loss"
              value={`$${sizeInfo.stop_loss.toFixed(2)}  (-7%)`}
              valueStyle={{ color: "var(--red)" }}
              suffix="🔴"
            />
            <Row
              label="Take-profit"
              value={`$${sizeInfo.take_profit.toFixed(2)}  (+15%)`}
              valueStyle={{ color: "var(--green)" }}
              suffix="🟢"
            />
          </div>
        )}

        {/* Footer note */}
        <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 16, lineHeight: 1.5 }}>
          This places a bracket order on Alpaca paper trading.
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <button className="btn btn-ghost" onClick={onClose} style={{ flex: 1 }} disabled={placing}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            style={{ flex: 1 }}
            onClick={execute}
            disabled={placing || loadingSize || !!sizeErr || !sizeInfo}
          >
            {placing ? "Placing…" : "Execute (Paper)"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  valueStyle,
  suffix,
}: {
  label:       string;
  value:       string;
  valueStyle?: React.CSSProperties;
  suffix?:     string;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
      <span style={{ color: "var(--text3)", fontFamily: "var(--mono)", fontSize: 12 }}>{label}</span>
      <span style={{ color: "var(--text)", fontFamily: "var(--mono)", ...valueStyle }}>
        {value} {suffix}
      </span>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SignalsPage() {
  const [signals, setSignals]       = useState<Signal[]>([]);
  const [filter, setFilter]         = useState("all");
  const [days, setDays]             = useState(7);
  const [loading, setLoading]       = useState(true);
  const [toast, setToast]           = useState("");
  const [execModal, setExecModal]   = useState<Signal | null>(null);
  const [techMap, setTechMap]       = useState<Record<string, TechIndicators>>({});
  const [earningsMap, setEarningsMap] = useState<Record<string, EarningsInfo>>({});

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 4000); };

  useEffect(() => {
    setLoading(true);
    api.signals.list(days).then(setSignals).catch(console.error).finally(() => setLoading(false));
  }, [days]);

  useEffect(() => {
    const symbols = Array.from(new Set(signals.map(s => s.symbol)));
    symbols.forEach(async sym => {
      try {
        const r = await fetch(`${API_URL}/api/technicals/${sym}`);
        if (r.ok) setTechMap(prev => ({ ...prev, [sym]: await r.json() }));
      } catch {}
      try {
        const r = await fetch(`${API_URL}/api/earnings/${sym}`);
        if (r.ok) setEarningsMap(prev => ({ ...prev, [sym]: await r.json() }));
      } catch {}
    });
  }, [signals]);

  const filtered = filter === "all" ? signals : signals.filter(s => s.type === filter);
  const typeColor: Record<string, string> = {
    buy:   "var(--green)",
    sell:  "var(--red)",
    watch: "var(--amber)",
    avoid: "var(--text3)",
  };

  const isBuyable = (s: Signal) => s.type === "buy" && (s.confidence ?? 0) >= 0.65;

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Signals</h1>
        <p className="page-sub">Claude-generated research signals — for reference only, not financial advice</p>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 20, alignItems: "center" }}>
        {["all", "buy", "sell", "watch", "avoid"].map(t => (
          <button
            key={t}
            className={`btn ${filter === t ? "btn-primary" : "btn-ghost"}`}
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
              className="btn btn-ghost"
              style={{
                padding: "5px 10px",
                color:       days === d ? "var(--green)" : "var(--text3)",
                borderColor: days === d ? "var(--green)" : "var(--border)",
              }}
              onClick={() => setDays(d)}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {[0, 1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 110 }} />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 40 }}>
          <p style={{ color: "var(--text3)", fontFamily: "var(--mono)", fontSize: 13 }}>
            No signals found. Run the morning job to generate signals.
          </p>
        </div>
      ) : filtered.map(s => (
        <div key={s.id} className={`signal-card ${s.type}`} style={{ marginBottom: 8 }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span style={{ fontFamily: "var(--mono)", fontWeight: 500, fontSize: 16 }}>{s.symbol}</span>
                <span className={`badge badge-${s.type === "buy" ? "green" : s.type === "sell" ? "red" : s.type === "watch" ? "amber" : "muted"}`}>
                  {s.type}
                </span>
                {s.acted_on && <span className="badge badge-blue">acted on</span>}
              </div>
              <p style={{ fontSize: 13, color: "var(--text2)", lineHeight: 1.65 }}>{s.reasoning}</p>
              {(techMap[s.symbol] || earningsMap[s.symbol]?.imminent) && (
                <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                  {techMap[s.symbol] && (
                    <>
                      <span className={`badge ${
                        techMap[s.symbol].rsi_signal === "oversold" ? "badge-green" :
                        techMap[s.symbol].rsi_signal === "overbought" ? "badge-red" : "badge-muted"
                      }`} style={{ fontSize: 10 }}>
                        RSI {techMap[s.symbol].rsi.toFixed(1)}
                      </span>
                      <span className={`badge ${
                        techMap[s.symbol].macd_trend === "bullish" ? "badge-green" :
                        techMap[s.symbol].macd_trend === "bearish" ? "badge-red" : "badge-muted"
                      }`} style={{ fontSize: 10 }}>
                        MACD {techMap[s.symbol].macd_trend === "bullish" ? "↑" : techMap[s.symbol].macd_trend === "bearish" ? "↓" : "→"} {techMap[s.symbol].macd_trend}
                      </span>
                      <span className={`badge ${
                        techMap[s.symbol].verdict === "bullish" ? "badge-green" :
                        techMap[s.symbol].verdict === "bearish" ? "badge-red" : "badge-muted"
                      }`} style={{ fontSize: 10 }}>
                        tech: {techMap[s.symbol].verdict}
                      </span>
                    </>
                  )}
                  {earningsMap[s.symbol]?.imminent && (
                    <span className="badge badge-red" style={{ fontSize: 10 }}>
                      ⚠️ Earnings in {earningsMap[s.symbol].days_until}d
                    </span>
                  )}
                </div>
              )}
            </div>

            <div style={{ textAlign: "right", flexShrink: 0 }}>
              {s.confidence != null && (
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
              {s.price_at != null && (
                <div style={{ marginTop: 6, fontFamily: "var(--mono)", fontSize: 12, color: "var(--text3)" }}>
                  ${s.price_at.toFixed(2)}
                </div>
              )}
              <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4, fontFamily: "var(--mono)" }}>
                {new Date(s.triggered_at).toLocaleDateString()}
              </div>

              {/* Execute button — BUY signals with confidence >= 0.65 only */}
              {isBuyable(s) && (
                <button
                  className="btn btn-primary"
                  style={{ marginTop: 10, fontSize: 11, padding: "5px 10px", display: "block", width: "100%" }}
                  onClick={() => setExecModal(s)}
                >
                  Execute
                </button>
              )}
            </div>
          </div>

          {s.confidence != null && (
            <div className="conf-bar" style={{ marginTop: 10 }}>
              <div
                className="conf-fill"
                style={{ width: `${s.confidence * 100}%`, background: typeColor[s.type] || "var(--text3)" }}
              />
            </div>
          )}
        </div>
      ))}

      {toast && <div className="toast">{toast}</div>}

      {execModal && (
        <ExecuteModal
          signal={execModal}
          onClose={() => setExecModal(null)}
          showToast={showToast}
        />
      )}
    </div>
  );
}
