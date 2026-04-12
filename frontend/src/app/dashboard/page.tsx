"use client";
import { useEffect, useState } from "react";
import { api, Signal, DailyReport, PortfolioResponse } from "@/lib/api";

function StatCard({ label, value, sub, color }: { label:string; value:string|number; sub?:string; color?:string }) {
  return (
    <div className="card">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{ color: color||"var(--text)" }}>{value}</div>
      {sub && <div style={{ fontSize:"11px", color:"var(--text3)", marginTop:4, fontFamily:"var(--mono)" }}>{sub}</div>}
    </div>
  );
}

function SignalBadge({ type }: { type:string }) {
  const map: Record<string,string> = { buy:"badge-green", sell:"badge-red", watch:"badge-amber", avoid:"badge-muted" };
  return <span className={`badge ${map[type]||"badge-muted"}`}>{type}</span>;
}

export default function DashboardPage() {
  const [signals, setSignals]     = useState<Signal[]>([]);
  const [report, setReport]       = useState<DailyReport|null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioResponse|null>(null);
  const [mode, setMode]           = useState("");
  const [loading, setLoading]     = useState(true);
  const [running, setRunning]     = useState(false);
  const [toast, setToast]         = useState("");

  useEffect(() => {
    Promise.all([api.signals.list(1), api.reports.list(1), api.portfolio.get(), api.health()])
      .then(([sigs, reports, port, health]) => {
        setSignals(sigs.slice(0,5)); setReport(reports[0]||null);
        setPortfolio(port); setMode(health.alpaca_mode);
      }).catch(console.error).finally(() => setLoading(false));
  }, []);

  const showToast = (msg:string) => { setToast(msg); setTimeout(()=>setToast(""),3500); };

  const triggerJob = async () => {
    setRunning(true);
    try { await api.scheduler.run(); showToast("Morning job triggered. Check Telegram."); }
    catch { showToast("Failed to trigger job."); }
    finally { setRunning(false); }
  };

  const totalPnL = portfolio?.positions.reduce((s,p)=>s+parseFloat(p.unrealized_pl||"0"),0)??0;

  if (loading) return (
    <div>
      <div className="page-header">
        <div className="skeleton" style={{ width:200, height:32, marginBottom:8 }} />
        <div className="skeleton" style={{ width:280, height:14 }} />
      </div>
      <div className="grid-4">{[0,1,2,3].map(i=><div key={i} className="skeleton" style={{ height:90 }} />)}</div>
    </div>
  );

  return (
    <div>
      <div className="page-header" style={{ display:"flex", alignItems:"flex-start", justifyContent:"space-between" }}>
        <div>
          <h1 className="page-title">Good morning</h1>
          <p className="page-sub">
            {new Date().toLocaleDateString("en-US",{ weekday:"long", year:"numeric", month:"long", day:"numeric" })}
            {" · "}
            <span style={{ color: mode==="paper"?"var(--amber)":"var(--green)" }}>
              {mode==="paper"?"● Paper trading":"● Live trading"}
            </span>
          </p>
        </div>
        <button className="btn btn-ghost" onClick={triggerJob} disabled={running}>
          {running?"Running...":"▶ Run morning job"}
        </button>
      </div>

      <div className="grid-4" style={{ marginBottom:24 }}>
        <StatCard label="Portfolio P&L" value={`${totalPnL>=0?"+":""}$${totalPnL.toFixed(2)}`} sub={`${portfolio?.count||0} positions`} color={totalPnL>=0?"var(--green)":"var(--red)"} />
        <StatCard label="Today's signals" value={signals.length} sub={`${signals.filter(s=>s.type==="buy").length} buy · ${signals.filter(s=>s.type==="watch").length} watch`} />
        <StatCard label="Screened today" value={report?.stocks_screened||0} sub={`${report?.halal_passed||0} halal passed`} />
        <StatCard label="Alerts sent" value={report?.alerts_sent||0} sub={report?.report_date||"No report yet"} />
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-header">
            <span className="card-title">Latest signals</span>
            <a href="/dashboard/signals" style={{ fontSize:11, color:"var(--text3)", fontFamily:"var(--mono)", textDecoration:"none" }}>View all →</a>
          </div>
          {signals.length===0 ? (
            <p style={{ color:"var(--text3)", fontSize:12, fontFamily:"var(--mono)" }}>No signals yet. Run the morning job.</p>
          ) : signals.map(s=>(
            <div key={s.id} className={`signal-card ${s.type}`}>
              <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:6 }}>
                <span style={{ fontFamily:"var(--mono)", fontWeight:500, fontSize:14 }}>{s.symbol}</span>
                <SignalBadge type={s.type} />
                {s.confidence && <span style={{ marginLeft:"auto", fontFamily:"var(--mono)", fontSize:11, color:"var(--text3)" }}>{(s.confidence*100).toFixed(0)}%</span>}
              </div>
              <p style={{ fontSize:12, color:"var(--text2)", lineHeight:1.5 }}>{s.reasoning.slice(0,120)}…</p>
            </div>
          ))}
        </div>

        <div>
          <div className="card" style={{ marginBottom:16 }}>
            <div className="card-header">
              <span className="card-title">Daily report</span>
              <a href="/dashboard/reports" style={{ fontSize:11, color:"var(--text3)", fontFamily:"var(--mono)", textDecoration:"none" }}>History →</a>
            </div>
            {report ? (
              <>
                <p style={{ fontSize:13, color:"var(--text2)", lineHeight:1.7, marginBottom:16 }}>{report.summary}</p>
                <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:8 }}>
                  {[["Screened",report.stocks_screened],["Halal passed",report.halal_passed],["Signals",report.signals_fired],["Trades",report.trades_executed]].map(([k,v])=>(
                    <div key={k as string} style={{ background:"var(--bg3)", borderRadius:"var(--radius)", padding:"8px 12px" }}>
                      <div style={{ fontFamily:"var(--mono)", fontSize:18, fontWeight:500 }}>{v}</div>
                      <div style={{ fontSize:10, color:"var(--text3)", textTransform:"uppercase", letterSpacing:"0.06em", marginTop:2 }}>{k}</div>
                    </div>
                  ))}
                </div>
              </>
            ) : <p style={{ color:"var(--text3)", fontSize:12, fontFamily:"var(--mono)" }}>No report yet. Trigger the morning job.</p>}
          </div>
          <div className="card">
            <div className="card-header">
              <span className="card-title">Alpaca status</span>
              <span className={`badge ${mode==="paper"?"badge-amber":"badge-green"}`}>{mode}</span>
            </div>
            {(portfolio?.positions||[]).length===0 ? (
              <p style={{ color:"var(--text3)", fontSize:12, fontFamily:"var(--mono)" }}>No open positions</p>
            ) : portfolio!.positions.slice(0,4).map(p=>(
              <div key={p.symbol} style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"4px 0" }}>
                <span style={{ fontFamily:"var(--mono)", fontSize:13 }}>{p.symbol}</span>
                <span style={{ fontFamily:"var(--mono)", fontSize:12, color:parseFloat(p.unrealized_pl)>=0?"var(--green)":"var(--red)" }}>
                  {parseFloat(p.unrealized_pl)>=0?"+":""}${parseFloat(p.unrealized_pl).toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
