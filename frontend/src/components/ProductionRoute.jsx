import { useEffect, useState } from "react";

export default function ProductionRoute({ job, api, action, busy, error, openSettings, reloadJob }) {
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState("");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    setLoading(true);
    setLoadError("");
    setConfirmed(false);
    api(`jobs/${job.id}/route-options`, { signal: controller.signal })
      .then((result) => {
        if (!result || !Array.isArray(result.options)) throw new Error("Printer service returned an invalid response. Refresh the page and try again.");
        if (active) { setData(result); setSelected(""); }
      })
      .catch((reason) => { if (active) { setData(null); setLoadError(reason.name === "AbortError" ? "Printer list timed out. Refresh to try again." : reason.message); } })
      .finally(() => { clearTimeout(timeout); if (active) setLoading(false); });
    return () => { active = false; clearTimeout(timeout); controller.abort(); };
  }, [job.id, api, refresh]);
  const option = data?.options?.find((item) => item.id === selected);
  const canSelect = option?.eligible && confirmed && note.trim().length >= 5;
  return <div data-testid="production-route-panel" aria-busy={busy || loading}>
    <p>Printer discovery does not verify paper support or a PDF handoff. Check compatibility before selecting a route.</p>
    {loading && <p role="status">Loading discovered printers...</p>}
    {loadError && <p role="alert" className="notice warning">{loadError}</p>}
    {!loading && data && <>
      <p>{data.message}</p>
      <label>Production printer
        <select value={selected} disabled={busy} data-testid="production-printer-select" onChange={(event) => { setSelected(event.target.value); setConfirmed(false); setNote(""); }}>
          <option value="">Choose a printer</option>
          {(data.options || []).map((item) => <option key={item.id} value={item.id} label={`${item.printer} - ${item.hostname} (${item.status})`} />)}
        </select>
      </label>
      {option && <>
        <p>{option.capabilitySource}.</p>
        {option.blockers?.length > 0 && <ul role="alert" data-testid="route-blockers">{option.blockers.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
        {option.eligible && <>
          <label>Compatibility evidence
            <textarea value={note} maxLength={1000} disabled={busy} data-testid="route-verification-note" onChange={(event) => { setNote(event.target.value); setConfirmed(false); }} placeholder="Record the printer specification or validated shop setup you checked." />
          </label>
          <label className="check-label"><input type="checkbox" checked={confirmed} disabled={busy} data-testid="route-compatibility-checkbox" onChange={(event) => setConfirmed(event.target.checked)} />I verified this printer supports {job.stock} and {job.sides === 2 ? "double-sided" : "single-sided"} production. Discovery alone is not proof.</label>
        </>}
      </>}
    </>}
    {error && <p role="alert" className="notice warning" data-testid="route-action-error">{error}</p>}
    <div className="action-row">
      <button className="primary" disabled={busy || loading || !canSelect} data-testid="select-route-button" onClick={() => action("route", { routeId: selected, settingsVersion: data.settingsVersion, compatibilityConfirmed: confirmed, verificationNote: note })}>{busy ? "Saving route..." : "Use production route"}</button>
      <button className="button" disabled={busy || loading} onClick={() => setRefresh((value) => value + 1)}>Refresh printers</button>
      <button className="button" disabled={busy} onClick={openSettings}>Shop settings</button>
      {error && <button className="button" disabled={busy} onClick={reloadJob}>Refresh job status</button>}
    </div>
    {!canSelect && !busy && !loading && <p role="status">{!option ? "Choose a printer to see its configuration requirements." : option.blockers?.length ? "Resolve the listed blockers in Shop settings, then refresh printers." : "Record compatibility evidence and check the confirmation above."}</p>}
    <p>Selecting a route does not authorize production or send a PDF to a printer.</p>
  </div>;
}
