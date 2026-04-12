"use client";
import { useEffect, useState } from "react";
import { api, PortfolioResponse } from "@/lib/api";

export default function PortfolioPage() {
  const [portfolio, setPortfolio] = useState<PortfolioResponse|null>(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState("");

  useEffect(() => { api.portfolio.get().then(setPortfolio).catch(e=>setError(e.message)).finally(()=>setLoading(false)); }, []);

  const totalValue = portfolio?.positions.reduce((s,p)=>s+parseFloat(p.market_value||"0"),0)??0;
  const totalPnL   = portfolio?.positions.reduce((s,p)=>s+parseFloat(p.unrealized_pl||"0"),0)??0;

  return (
    <div>
      <div className="page-header" style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start" }}>
        <div>
          <h1 className="page-title">Portfolio</h1>
          <p className="page-sub">Live Alpaca positions · {portfolio?.alpaca_mode==="paper"?"Paper trading":"Live trading"}</p>
        </div>
        {portfolio?.alpaca_mode==="paper" && <span className="badge badge-amber">Paper trading</span>}
      </div>
      {portfolio && (
        <div className="grid-3" style={{ marginBottom:24 }}>
          <div className="card"><div className="stat-label">Market value</div><div className="stat-value">${totalValue.toFixed(2)}</div></div>
          <div className="card"><div className="stat-label">Unrealized P&L</div><div className="stat-value" style={{ color:totalPnL>=0?"var(--green)":"var(--red)" }}>{totalPnL>=0?"+":""}${totalPnL.toFixed(2)}</div></div>
          <div className="card"><div className="stat-label">Open positions</div><div className="stat-value">{portfolio.count}</div></div>
        </div>
      )}
      <div className="card">
        <div className="card-header"><span className="card-title">Positions</span></div>
        {loading ? (
          <div style={{ display:"flex", flexDirection:"column", gap:8 }}>{[0,1,2].map(i=><div key={i} className="skeleton" style={{ height:48 }} />)}</div>
        ) : error ? (
          <p style={{ color:"var(--red)", fontFamily:"var(--mono)", fontSize:12 }}>{error}</p>
        ) : !portfolio?.positions.length ? (
          <div style={{ textAlign:"center", padding:40 }}>
            <p style={{ color:"var(--text3)", fontFamily:"var(--mono)", fontSize:13 }}>No open positions</p>
          </div>
        ) : (
          <table className="table">
            <thead><tr><th>Symbol</th><th>Qty</th><th>Avg entry</th><th>Current</th><th>Market value</th><th>P&L</th><th>Return</th></tr></thead>
            <tbody>
              {portfolio.positions.map(p=>{
                const pnl=parseFloat(p.unrealized_pl), pct=parseFloat(p.unrealized_plpc)*100, up=pnl>=0;
                return (
                  <tr key={p.symbol}>
                    <td><span style={{ fontFamily:"var(--mono)", fontWeight:500, fontSize:14 }}>{p.symbol}</span></td>
                    <td><span style={{ fontFamily:"var(--mono)", fontSize:13 }}>{p.qty}</span></td>
                    <td><span style={{ fontFamily:"var(--mono)", fontSize:13 }}>${parseFloat(p.avg_entry_price).toFixed(2)}</span></td>
                    <td><span style={{ fontFamily:"var(--mono)", fontSize:13 }}>${parseFloat(p.current_price).toFixed(2)}</span></td>
                    <td><span style={{ fontFamily:"var(--mono)", fontSize:13 }}>${parseFloat(p.market_value).toFixed(2)}</span></td>
                    <td><span style={{ fontFamily:"var(--mono)", fontSize:13, color:up?"var(--green)":"var(--red)" }}>{up?"+":""}${pnl.toFixed(2)}</span></td>
                    <td><span style={{ fontFamily:"var(--mono)", fontSize:12, color:up?"var(--green)":"var(--red)" }}>{up?"+":""}{pct.toFixed(2)}%</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
