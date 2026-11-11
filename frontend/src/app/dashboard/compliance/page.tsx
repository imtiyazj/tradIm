"use client";
import { useEffect, useState } from "react";
import { api, ComplianceLatest, ComplianceCheck, PurificationSummary } from "@/lib/api";

const mono = { fontFamily: "var(--mono)", fontSize: 12 } as const;

function money(v: number | null | undefined) {
  if (v === null || v === undefined) return "—";
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function statusBadge(status: string | null) {
  if (!status) return <span className="badge badge-muted">new</span>;
  const cls =
    status === "compliant" ? "badge-green" :
    status === "non_compliant" ? "badge-red" :
    status === "doubtful" ? "badge-amber" : "badge-muted";
  return <span className={`badge ${cls}`}>{status.replace("_", "-")}</span>;
}

function CheckRow({ c }: { c: ComplianceCheck }) {
  return (
    <tr>
      <td><span style={{ ...mono, fontWeight: 500, fontSize: 14 }}>{c.symbol}</span></td>
      <td>{c.is_held ? <span className="badge badge-blue">held</span> : <span className="badge badge-muted">watchlist</span>}</td>
      <td>
        {c.inconclusive
          ? <span className="badge badge-muted">not verified</span>
          : statusBadge(c.new_status)}
      </td>
      <td>
        {c.status_changed
          ? <span style={mono}>{statusBadge(c.previous_status)} →</span>
          : <span style={{ ...mono, color: "var(--text3)" }}>no change</span>}
      </td>
      <td><span style={mono}>{c.is_held ? money(c.market_value) : "—"}</span></td>
      <td><span style={{ fontSize: 12, color: "var(--text2)" }}>{c.notes || "—"}</span></td>
    </tr>
  );
}

export default function CompliancePage() {
  const [data, setData]       = useState<ComplianceLatest | null>(null);
  const [ledger, setLedger]   = useState<PurificationSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [busy, setBusy]       = useState("");
  const [toast, setToast]     = useState("");

  const load = () =>
    Promise.all([api.compliance.latest(), api.purification.get()])
      .then(([c, p]) => { setData(c); setLedger(p); setError(""); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));

  useEffect(() => { load(); }, []);

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 4000); };

  const runReview = async () => {
    setBusy("review");
    try {
      const res = await api.compliance.run();
      showToast(res.message);
      // The review runs in the background — refresh once it has had time to finish.
      setTimeout(load, 60000);
    } catch (e: any) {
      showToast(e.message || "Could not start the review.");
    } finally {
      setBusy("");
    }
  };

  const syncDividends = async () => {
    setBusy("sync");
    try {
      const res = await api.purification.sync();
      showToast(res.added ? `${res.added} new dividend(s) recorded.` : "No new dividends.");
      await load();
    } catch (e: any) {
      showToast(e.message || "Dividend sync failed.");
    } finally {
      setBusy("");
    }
  };

  const setPaid = async (id: string, isPaid: boolean) => {
    try {
      await api.purification.setPaid(id, isPaid);
      await load();
    } catch (e: any) {
      showToast(e.message || "Update failed.");
    }
  };

  const markAllPaid = async () => {
    if (!ledger || ledger.outstanding <= 0) return;
    if (!window.confirm(`Mark ${money(ledger.outstanding)} as donated?`)) return;
    setBusy("paid");
    try {
      const res = await api.purification.markAllPaid();
      showToast(`${res.marked} entr${res.marked === 1 ? "y" : "ies"} marked as donated.`);
      await load();
    } catch (e: any) {
      showToast(e.message || "Update failed.");
    } finally {
      setBusy("");
    }
  };

  if (loading) return (
    <div>
      <div className="page-header">
        <div className="skeleton" style={{ width: 240, height: 32, marginBottom: 8 }} />
        <div className="skeleton" style={{ width: 360, height: 14 }} />
      </div>
      <div className="skeleton" style={{ height: 200 }} />
    </div>
  );

  const review = data?.review ?? null;

  return (
    <div>
      <div className="page-header" style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <h1 className="page-title">Compliance</h1>
          <p className="page-sub">
            Quarterly Shariah review of your holdings · dividend purification ledger
          </p>
        </div>
        <button className="btn btn-ghost" onClick={runReview} disabled={busy === "review"}>
          {busy === "review" ? "Starting..." : "↻ Run review now"}
        </button>
      </div>

      {error && (
        <div className="card" style={{ marginBottom: 16 }}>
          <p style={{ ...mono, color: "var(--red)" }}>{error}</p>
        </div>
      )}

      {/* ── Quarterly review ── */}
      {!review ? (
        <div className="card" style={{ marginBottom: 24 }}>
          <p style={{ color: "var(--text3)", fontSize: 13, lineHeight: 1.7 }}>
            No compliance review yet. One runs automatically in the first week of March, June,
            September and December, after quarterly filings are in — or press “Run review now”.
          </p>
        </div>
      ) : (
        <>
          <div className="grid-4" style={{ marginBottom: 24 }}>
            <div className="card">
              <div className="stat-label">Last review</div>
              <div className="stat-value" style={{ fontSize: 22 }}>{review.period}</div>
              <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4, fontFamily: "var(--mono)" }}>
                {new Date(review.checked_at).toLocaleDateString()}
              </div>
            </div>
            <div className="card">
              <div className="stat-label">Symbols checked</div>
              <div className="stat-value" style={{ fontSize: 22 }}>{review.checked}</div>
              <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4, fontFamily: "var(--mono)" }}>
                {review.held} held
              </div>
            </div>
            <div className="card">
              <div className="stat-label">Action required</div>
              <div className="stat-value" style={{ fontSize: 22, color: review.action_required.length ? "var(--red)" : "var(--green)" }}>
                {review.action_required.length}
              </div>
              <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4, fontFamily: "var(--mono)" }}>
                non-compliant holdings
              </div>
            </div>
            <div className="card">
              <div className="stat-label">Status changes</div>
              <div className="stat-value" style={{ fontSize: 22 }}>{review.changed.length}</div>
              <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4, fontFamily: "var(--mono)" }}>
                since previous review
              </div>
            </div>
          </div>

          {review.action_required.length > 0 && (
            <div className="card" style={{ marginBottom: 16, borderColor: "var(--red)" }}>
              <div className="card-header"><span className="card-title" style={{ color: "var(--red)" }}>Sell these holdings</span></div>
              {review.action_required.map(c => (
                <p key={c.id} style={{ fontSize: 13, color: "var(--text2)", lineHeight: 1.7 }}>
                  <span style={{ ...mono, fontWeight: 500, color: "var(--text)" }}>{c.symbol}</span>
                  {" "}is no longer Shariah-compliant
                  {c.quantity !== null ? ` — you hold ${c.quantity} shares (${money(c.market_value)})` : ""}.
                  {c.notes ? ` ${c.notes}` : ""}
                </p>
              ))}
              <p style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--mono)", marginTop: 8 }}>
                Nothing is sold automatically.
              </p>
            </div>
          )}

          {(review.review.length > 0 || review.inconclusive.length > 0) && (
            <div className="card" style={{ marginBottom: 16 }}>
              {review.review.length > 0 && (
                <p style={{ fontSize: 13, color: "var(--amber)", lineHeight: 1.7 }}>
                  Doubtful holdings to review: {review.review.map(c => c.symbol).join(", ")}
                </p>
              )}
              {review.inconclusive.length > 0 && (
                <p style={{ fontSize: 13, color: "var(--text3)", lineHeight: 1.7 }}>
                  Could not be verified this run: {review.inconclusive.join(", ")}
                </p>
              )}
            </div>
          )}

          <div className="card" style={{ marginBottom: 24 }}>
            <div className="card-header"><span className="card-title">Review {review.period}</span></div>
            <div style={{ overflowX: "auto" }}>
              <table className="table">
                <thead><tr><th>Symbol</th><th>Type</th><th>Status</th><th>Previously</th><th>Market value</th><th>Notes</th></tr></thead>
                <tbody>{review.rows.map(c => <CheckRow key={c.id} c={c} />)}</tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ── Purification ── */}
      <div className="page-header" style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginTop: 8 }}>
        <div>
          <h2 className="page-title" style={{ fontSize: 20 }}>Purification</h2>
          <p className="page-sub">
            Share of each dividend that came from impermissible income, to give to charity
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {ledger?.paper && <span className="badge badge-amber">Paper trading</span>}
          <button className="btn btn-ghost" onClick={syncDividends} disabled={busy === "sync"}>
            {busy === "sync" ? "Syncing..." : "↻ Sync dividends"}
          </button>
        </div>
      </div>

      {ledger && (
        <>
          <div className="grid-4" style={{ marginBottom: 24 }}>
            <div className="card">
              <div className="stat-label">Dividends received</div>
              <div className="stat-value" style={{ fontSize: 22 }}>{money(ledger.total_dividends)}</div>
            </div>
            <div className="card">
              <div className="stat-label">Total to purify</div>
              <div className="stat-value" style={{ fontSize: 22 }}>{money(ledger.total_owed)}</div>
            </div>
            <div className="card">
              <div className="stat-label">Donated</div>
              <div className="stat-value" style={{ fontSize: 22, color: "var(--green)" }}>{money(ledger.total_paid)}</div>
            </div>
            <div className="card">
              <div className="stat-label">Outstanding</div>
              <div className="stat-value" style={{ fontSize: 22, color: ledger.outstanding > 0 ? "var(--amber)" : "var(--green)" }}>
                {money(ledger.outstanding)}
              </div>
            </div>
          </div>

          {ledger.entries.length === 0 ? (
            <div className="card">
              <p style={{ color: "var(--text3)", fontSize: 13, lineHeight: 1.7 }}>
                No dividends recorded yet. Dividends are pulled from Alpaca every Saturday —
                or press “Sync dividends”.
              </p>
            </div>
          ) : (
            <div className="card">
              <div className="card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span className="card-title">Dividend ledger</span>
                {ledger.outstanding > 0 && (
                  <button className="btn btn-primary" onClick={markAllPaid} disabled={busy === "paid"}>
                    Mark all as donated
                  </button>
                )}
              </div>
              <div style={{ overflowX: "auto" }}>
                <table className="table">
                  <thead><tr><th>Date</th><th>Symbol</th><th>Dividend</th><th>Impure share</th><th>To purify</th><th>Status</th><th></th></tr></thead>
                  <tbody>
                    {ledger.entries.map(e => (
                      <tr key={e.id}>
                        <td><span style={{ ...mono, color: "var(--text3)" }}>{e.income_date.slice(0, 10)}</span></td>
                        <td><span style={{ ...mono, fontWeight: 500 }}>{e.symbol}</span></td>
                        <td><span style={mono}>{money(e.income_amount)}</span></td>
                        <td title={e.note || undefined}>
                          <span style={mono}>{(e.impure_pct * 100).toFixed(2)}%</span>
                          {e.rate_source === "default_cap" && <span className="badge badge-muted" style={{ marginLeft: 6 }}>estimate</span>}
                        </td>
                        <td><span style={mono}>{money(e.purification_amount)}</span></td>
                        <td>{e.is_paid ? <span className="badge badge-green">donated</span> : <span className="badge badge-amber">owed</span>}</td>
                        <td>
                          <button className="btn btn-ghost" onClick={() => setPaid(e.id, !e.is_paid)}>
                            {e.is_paid ? "Undo" : "Mark donated"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {ledger.estimated_count > 0 && (
                <p style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--mono)", marginTop: 12 }}>
                  “Estimate” = the screen had no impermissible-income figure, so the 5% compliance ceiling was used as an upper bound.
                </p>
              )}
            </div>
          )}
        </>
      )}

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
