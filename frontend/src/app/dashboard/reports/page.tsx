"use client";
import { useEffect, useState } from "react";
import { api, DailyReport } from "@/lib/api";

export default function ReportsPage() {
  const [reports, setReports]   = useState<DailyReport[]>([]);
  const [selected, setSelected] = useState<DailyReport|null>(null);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    api.reports.list(30).then(data=>{ setReports(data); if(data[0]) setSelected(data[0]); }).catch(console.error).finally(()=>setLoading(false));
  }, []);

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Daily reports</h1>
        <p className="page-sub">History of morning job runs and Claude summaries</p>
      </div>
      <div className="grid-2" style={{ alignItems:"start" }}>
        <div className="card">
          <div className="card-header"><span className="card-title">Report history</span></div>
          {loading ? (
            <div style={{ display:"flex", flexDirection:"column", gap:6 }}>{[0,1,2,3].map(i=><div key={i} className="skeleton" style={{ height:56 }} />)}</div>
          ) : reports.length===0 ? (
            <p style={{ color:"var(--text3)", fontFamily:"var(--mono)", fontSize:12 }}>No reports yet.</p>
          ) : reports.map(r=>(
            <div key={r.id} onClick={()=>setSelected(r)} style={{ padding:"12px", borderRadius:"var(--radius)", cursor:"pointer", background:selected?.id===r.id?"var(--bg3)":"transparent", border:`1px solid ${selected?.id===r.id?"var(--border2)":"transparent"}`, marginBottom:4, transition:"all 0.12s" }}>
              <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                <span style={{ fontFamily:"var(--mono)", fontSize:13, fontWeight:500 }}>{r.report_date}</span>
                <div style={{ display:"flex", gap:6 }}>
                  <span className="badge badge-green">{r.halal_passed} halal</span>
                  <span className="badge badge-muted">{r.signals_fired} signals</span>
                </div>
              </div>
              <div style={{ fontSize:12, color:"var(--text3)", marginTop:4 }}>{r.stocks_screened} screened · {r.alerts_sent} alerts</div>
            </div>
          ))}
        </div>
        {selected && (
          <div>
            <div className="card" style={{ marginBottom:16 }}>
              <div className="card-header"><span className="card-title">{selected.report_date}</span></div>
              <p style={{ fontSize:13, color:"var(--text2)", lineHeight:1.75 }}>{selected.summary}</p>
            </div>
            <div className="grid-2">
              {[["Stocks screened",selected.stocks_screened,"var(--text)"],["Halal passed",selected.halal_passed,"var(--green)"],["Signals fired",selected.signals_fired,"var(--blue)"],["Trades",selected.trades_executed,"var(--amber)"]].map(([l,v,c])=>(
                <div key={l as string} className="card" style={{ padding:"14px 16px" }}>
                  <div style={{ fontFamily:"var(--mono)", fontSize:24, fontWeight:500, color:c as string }}>{v}</div>
                  <div style={{ fontSize:10, color:"var(--text3)", textTransform:"uppercase", letterSpacing:"0.06em", marginTop:2 }}>{l}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
