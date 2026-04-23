"use client";
import { useEffect, useState } from "react";
import { api, WatchlistItem, HalalScreenResult } from "@/lib/api";

export default function WatchlistPage() {
  const [items, setItems]     = useState<WatchlistItem[]>([]);
  const [screens, setScreens] = useState<Record<string,HalalScreenResult>>({});
  const [symbol, setSymbol]   = useState("");
  const [notes, setNotes]     = useState("");
  const [loading, setLoading] = useState(true);
  const [adding, setAdding]   = useState(false);
  const [toast, setToast]     = useState<{ msg:string; ok:boolean }|null>(null);

  const showToast = (msg:string, ok=true) => { setToast({msg,ok}); setTimeout(()=>setToast(null),3500); };

  const loadWatchlist = async () => {
    const data = await api.watchlist.list();
    setItems(data);
    const sr: Record<string,HalalScreenResult> = {};
    await Promise.all(data.map(async item => { try { sr[item.symbol]=await api.halal.screen(item.symbol); } catch {} }));
    setScreens(sr);
  };

  useEffect(() => { loadWatchlist().finally(()=>setLoading(false)); }, []);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!symbol.trim()) return;
    setAdding(true);
    try {
      await api.watchlist.add(symbol.trim().toUpperCase(), notes||undefined);
      showToast(`${symbol.toUpperCase()} added`);
      setSymbol(""); setNotes("");
      await loadWatchlist();
    } catch (err:unknown) {
      showToast(err instanceof Error ? err.message : "Failed to add stock", false);
    } finally { setAdding(false); }
  };

  const handleRemove = async (sym:string) => {
    try { await api.watchlist.remove(sym); showToast(`${sym} removed`); setItems(prev=>prev.filter(i=>i.symbol!==sym)); }
    catch { showToast("Failed to remove",false); }
  };

  const statusBadge = (status:string) => {
    const map: Record<string,string> = { compliant:"badge-green", non_compliant:"badge-red", doubtful:"badge-amber", unknown:"badge-muted" };
    return <span className={`badge ${map[status]||"badge-muted"}`}>{status.replace("_"," ")}</span>;
  };

  const nonHalalItems  = items.filter(i => screens[i.symbol]?.final_status === "non_compliant");
  const halalItems     = items.filter(i => screens[i.symbol]?.final_status !== "non_compliant");

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Watchlist</h1>
        <p className="page-sub">Only Shariah-compliant stocks can be added</p>
      </div>
      <div className="card" style={{ marginBottom:24 }}>
        <div className="card-header"><span className="card-title">Add stock</span></div>
        <form onSubmit={handleAdd} style={{ display:"flex", gap:8 }}>
          <input className="input" style={{ maxWidth:140, textTransform:"uppercase" }} placeholder="Ticker (AAPL)" value={symbol} onChange={e=>setSymbol(e.target.value.toUpperCase())} maxLength={10} />
          <input className="input" placeholder="Notes (optional)" value={notes} onChange={e=>setNotes(e.target.value)} />
          <button type="submit" className="btn btn-primary" disabled={adding||!symbol.trim()} style={{ whiteSpace:"nowrap" }}>
            {adding?"Screening...":"+ Add"}
          </button>
        </form>
        <p style={{ fontSize:11, color:"var(--text3)", fontFamily:"var(--mono)", marginTop:8 }}>Stocks are screened via Zoya API before being added.</p>
      </div>
      {/* Non-halal warning banner */}
      {!loading && nonHalalItems.length > 0 && (
        <div style={{
          background: "var(--red-dim)", border: "1px solid var(--red)",
          borderRadius: "var(--radius)", padding: "14px 18px", marginBottom: 16,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <span style={{ fontSize: 16 }}>🚫</span>
            <span style={{ fontWeight: 600, color: "var(--red)", fontSize: 13 }}>
              {nonHalalItems.length} non-compliant stock{nonHalalItems.length > 1 ? "s" : ""} in your watchlist
            </span>
          </div>
          <p style={{ fontSize: 12, color: "var(--text2)", marginBottom: 12, lineHeight: 1.6 }}>
            The following stocks failed Shariah screening. They are <strong>excluded from daily analysis</strong> and
            re-checked every 15 days. Please remove them to keep your watchlist clean.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {nonHalalItems.map(item => {
              const s = screens[item.symbol];
              return (
                <div key={item.id} style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  background: "var(--bg2)", borderRadius: "var(--radius)", padding: "10px 14px",
                  border: "1px solid var(--red)",
                }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                    <span style={{ fontFamily: "var(--mono)", fontWeight: 600, fontSize: 14, color: "var(--red)" }}>
                      {item.symbol}
                    </span>
                    <span style={{ fontSize: 11, color: "var(--text3)" }}>
                      {s?.notes || "Failed Shariah screening"} · re-checked every 15 days
                    </span>
                  </div>
                  <button
                    className="btn btn-danger"
                    style={{ padding: "5px 14px", fontSize: 12 }}
                    onClick={() => handleRemove(item.symbol)}
                  >
                    Remove
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <span className="card-title">Tracked stocks ({items.length})</span>
          {!loading && nonHalalItems.length > 0 && (
            <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--text3)" }}>
              {halalItems.length} active · {nonHalalItems.length} non-compliant
            </span>
          )}
        </div>
        {loading ? (
          <div style={{ display:"flex", flexDirection:"column", gap:8 }}>{[0,1,2].map(i=><div key={i} className="skeleton" style={{ height:48 }} />)}</div>
        ) : items.length===0 ? (
          <p style={{ color:"var(--text3)", fontFamily:"var(--mono)", fontSize:12 }}>No stocks yet. Add one above.</p>
        ) : (
          <table className="table">
            <thead><tr><th>Symbol</th><th>Halal</th><th>Debt ratio</th><th>Notes</th><th>Added</th><th></th></tr></thead>
            <tbody>
              {halalItems.map(item => {
                const s = screens[item.symbol];
                return (
                  <tr key={item.id}>
                    <td><span style={{ fontFamily:"var(--mono)", fontWeight:500, fontSize:14 }}>{item.symbol}</span></td>
                    <td>{s ? statusBadge(s.final_status) : <span className="badge badge-muted">loading</span>}</td>
                    <td><span style={{ fontFamily:"var(--mono)", fontSize:12, color:"var(--text2)" }}>{s?.debt_ratio!=null?`${(s.debt_ratio*100).toFixed(1)}%`:"—"}</span></td>
                    <td><span style={{ fontSize:12, color:"var(--text2)" }}>{item.notes||"—"}</span></td>
                    <td><span style={{ fontFamily:"var(--mono)", fontSize:11, color:"var(--text3)" }}>{new Date(item.added_at).toLocaleDateString()}</span></td>
                    <td><button className="btn btn-danger" style={{ padding:"4px 10px", fontSize:11 }} onClick={()=>handleRemove(item.symbol)}>Remove</button></td>
                  </tr>
                );
              })}
              {nonHalalItems.map(item => {
                const s = screens[item.symbol];
                return (
                  <tr key={item.id} style={{ opacity: 0.5 }}>
                    <td>
                      <span style={{ fontFamily:"var(--mono)", fontWeight:500, fontSize:14, color:"var(--red)", textDecoration:"line-through" }}>{item.symbol}</span>
                    </td>
                    <td>{s ? statusBadge(s.final_status) : <span className="badge badge-muted">loading</span>}</td>
                    <td><span style={{ fontFamily:"var(--mono)", fontSize:12, color:"var(--text2)" }}>{s?.debt_ratio!=null?`${(s.debt_ratio*100).toFixed(1)}%`:"—"}</span></td>
                    <td><span style={{ fontSize:11, color:"var(--red)" }}>⚠️ Non-compliant — remove</span></td>
                    <td><span style={{ fontFamily:"var(--mono)", fontSize:11, color:"var(--text3)" }}>{new Date(item.added_at).toLocaleDateString()}</span></td>
                    <td><button className="btn btn-danger" style={{ padding:"4px 10px", fontSize:11 }} onClick={()=>handleRemove(item.symbol)}>Remove</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {toast && <div className="toast" style={{ borderColor:toast.ok?"var(--green)":"var(--red)" }}>{toast.msg}</div>}
    </div>
  );
}
