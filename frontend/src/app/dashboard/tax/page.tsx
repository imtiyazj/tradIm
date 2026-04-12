"use client";
import { useState } from "react";

interface TaxSummary {
  short_term_gains:number; long_term_gains:number; quarterly_estimate:number;
  harvesting_opportunities:{symbol:string;unrealized_loss:number;note:string}[];
  schedule_d_rows:{symbol:string;acquired:string;sold:string;proceeds:number;cost_basis:number;gain_loss:number;term:string}[];
  notes:string; error?:string;
}

export default function TaxPage() {
  const [year, setYear]       = useState(new Date().getFullYear());
  const [summary, setSummary] = useState<TaxSummary|null>(null);
  const [count, setCount]     = useState(0);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded]   = useState(false);

  const loadTax = () => {
    setLoading(true);
    fetch(`${process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000"}/api/tax/summary?year=${year}`)
      .then(r=>r.json()).then(data=>{ setSummary(data.summary); setCount(data.trade_count); setLoaded(true); })
      .catch(console.error).finally(()=>setLoading(false));
  };

  const totalGains=(summary?.short_term_gains??0)+(summary?.long_term_gains??0);

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Tax summary</h1>
        <p className="page-sub">CPA-ready report · supplements but does not replace your broker 1099-B</p>
      </div>
      <div className="card" style={{ marginBottom:24 }}>
        <div style={{ display:"flex", gap:12, alignItems:"center" }}>
          <span style={{ fontFamily:"var(--mono)", fontSize:12, color:"var(--text2)" }}>Tax year:</span>
          {[new Date().getFullYear(), new Date().getFullYear()-1].map(y=>(
            <button key={y} className={`btn ${year===y?"btn-primary":"btn-ghost"}`} onClick={()=>setYear(y)}>{y}</button>
          ))}
          <button className="btn btn-ghost" onClick={loadTax} disabled={loading} style={{ marginLeft:"auto" }}>
            {loading?"Generating...":"Generate report"}
          </button>
        </div>
      </div>
      {!loaded&&!loading && (
        <div className="card" style={{ textAlign:"center", padding:48 }}>
          <p style={{ color:"var(--text3)", fontFamily:"var(--mono)", fontSize:13 }}>Click "Generate report" to run Claude's tax analysis</p>
        </div>
      )}
      {loading && <div style={{ display:"flex", flexDirection:"column", gap:16 }}><div className="skeleton" style={{ height:100 }} /><div className="skeleton" style={{ height:200 }} /></div>}
      {loaded&&summary&&!summary.error && (
        <>
          <div className="grid-4" style={{ marginBottom:24 }}>
            <div className="card"><div className="stat-label">Short-term gains</div><div className="stat-value" style={{ color:(summary.short_term_gains??0)>=0?"var(--green)":"var(--red)", fontSize:22 }}>${(summary.short_term_gains??0).toFixed(2)}</div><div style={{ fontSize:10, color:"var(--text3)", marginTop:4, fontFamily:"var(--mono)" }}>Ordinary income rate</div></div>
            <div className="card"><div className="stat-label">Long-term gains</div><div className="stat-value" style={{ color:(summary.long_term_gains??0)>=0?"var(--green)":"var(--red)", fontSize:22 }}>${(summary.long_term_gains??0).toFixed(2)}</div><div style={{ fontSize:10, color:"var(--text3)", marginTop:4, fontFamily:"var(--mono)" }}>Preferred tax rate</div></div>
            <div className="card"><div className="stat-label">Total realized</div><div className="stat-value" style={{ fontSize:22 }}>${totalGains.toFixed(2)}</div><div style={{ fontSize:10, color:"var(--text3)", marginTop:4, fontFamily:"var(--mono)" }}>{count} trades</div></div>
            <div className="card"><div className="stat-label">Quarterly estimate</div><div className="stat-value" style={{ color:"var(--amber)", fontSize:22 }}>${(summary.quarterly_estimate??0).toFixed(2)}</div><div style={{ fontSize:10, color:"var(--text3)", marginTop:4, fontFamily:"var(--mono)" }}>Form 1040-ES</div></div>
          </div>
          {(summary.schedule_d_rows?.length??0)>0 && (
            <div className="card" style={{ marginBottom:24 }}>
              <div className="card-header"><span className="card-title">Schedule D</span></div>
              <table className="table">
                <thead><tr><th>Symbol</th><th>Acquired</th><th>Sold</th><th>Proceeds</th><th>Cost basis</th><th>Gain/loss</th><th>Term</th></tr></thead>
                <tbody>
                  {summary.schedule_d_rows.map((r,i)=>(
                    <tr key={i}>
                      <td><span style={{ fontFamily:"var(--mono)", fontWeight:500 }}>{r.symbol}</span></td>
                      <td><span style={{ fontFamily:"var(--mono)", fontSize:12 }}>{r.acquired}</span></td>
                      <td><span style={{ fontFamily:"var(--mono)", fontSize:12 }}>{r.sold}</span></td>
                      <td><span style={{ fontFamily:"var(--mono)", fontSize:12 }}>${r.proceeds.toFixed(2)}</span></td>
                      <td><span style={{ fontFamily:"var(--mono)", fontSize:12 }}>${r.cost_basis.toFixed(2)}</span></td>
                      <td><span style={{ fontFamily:"var(--mono)", fontSize:12, color:r.gain_loss>=0?"var(--green)":"var(--red)" }}>{r.gain_loss>=0?"+":""}${r.gain_loss.toFixed(2)}</span></td>
                      <td><span className={`badge ${r.term==="long"?"badge-green":"badge-amber"}`}>{r.term}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {summary.notes && (
            <div className="card">
              <div className="card-header"><span className="card-title">Notes from Claude</span></div>
              <p style={{ fontSize:13, color:"var(--text2)", lineHeight:1.7 }}>{summary.notes}</p>
              <p style={{ fontSize:11, color:"var(--text3)", fontFamily:"var(--mono)", marginTop:12 }}>⚠ Always review with a CPA before filing.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
