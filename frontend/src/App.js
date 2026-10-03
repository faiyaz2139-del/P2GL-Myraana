import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Download,
  FileText,
  Layers,
  Link2,
  LogOut,
  Moon,
  PackageCheck,
  Plus,
  Printer,
  Pause,
  Play,
  Send,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  Upload,
  Users,
  X,
} from "lucide-react";
import "@/App.css";
import "@/mobile.css";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const api = async (path, options = {}) => {
  const response = await fetch(`${API}/${path}`, {
    credentials: "include",
    ...options,
    headers: options.body instanceof FormData
      ? options.headers
      : { "Content-Type": "application/json", ...options.headers },
  });
  const data = response.headers.get("content-type")?.includes("application/json")
    ? await response.json()
    : null;
  if (!response.ok) {
    throw new Error(data?.error || "Unable to save. Please retry.");
  }
  return data;
};

const date = (value) => new Date(value).toLocaleString("en-CA", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const latest = (job, stage) => [...(job?.files || [])].reverse().find((file) => file.stage === stage);

function Badge({ status }) {
  return <span className={`badge ${status.toLowerCase().replaceAll(" ", "-")}`} data-testid={`status-${status.toLowerCase().replaceAll(" ", "-")}`}>{status}</span>;
}

function Auth({ auth, onSignedIn }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      const result = await api(`auth/${auth.needsSetup ? "setup" : "login"}`, {
        method: "POST",
        body: JSON.stringify({
          name: form.get("name"),
          email: form.get("email"),
          password: form.get("password"),
        }),
      });
      onSignedIn(result.user);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  return <div className="auth-shell" data-testid="auth-screen">
    <div className="auth-art">
      <Brand />
      <div>
        <span className="eyebrow">PRINT2GO LONDON</span>
        <h1>A clear path<br />to a great print.</h1>
        <p>Artwork, approvals and production.<br />Together in one secure workspace.</p>
      </div>
      <span className="auth-foot">Made for the people behind the print.</span>
    </div>
    <main className="auth-form">
      <span className="eyebrow">YOUR SHOP WORKSPACE</span>
      <h2>{auth.needsSetup ? "Set up your shop" : "Welcome back"}</h2>
      <p className="muted">{auth.needsSetup
        ? "Create the first administrator account."
        : "Sign in to continue your production work."}</p>
      {error && <div className="notice warning" role="alert" data-testid="auth-error">{error}</div>}
      <form onSubmit={submit} data-testid="auth-form">
        {auth.needsSetup && <label>Your name
          <input name="name" required maxLength="80" autoComplete="name"
            data-testid="setup-name-input" placeholder="Shop administrator" />
        </label>}
        <label>Email
          <input name="email" required type="email" autoComplete="username"
            data-testid="auth-email-input" placeholder="you@yourshop.ca" />
        </label>
        <label>Password
          <input name="password" required type="password" minLength="12" maxLength="200"
            autoComplete={auth.needsSetup ? "new-password" : "current-password"}
            data-testid="auth-password-input" placeholder="At least 12 characters" />
        </label>
        <button className="primary wide" disabled={busy} data-testid="auth-submit-button">
          {busy ? "Saving…" : auth.needsSetup ? "Create shop account" : "Sign in"}
        </button>
      </form>
      <p className="tiny"><ShieldCheck size={14} />Files and approvals stay in your shop.</p>
    </main>
  </div>;
}

function Brand() {
  return <div className="brand" data-testid="brand">
    <div className="brand-mark"><Layers size={23} /></div>
    <div className="brand-name">Print<span>2</span>Go<small>PRODUCTION STUDIO</small></div>
  </div>;
}

function JobModal({ recipes, settings, close, created }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const recipe = recipes[0];
  const submit = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    try {
      const job = await api("jobs", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(form)),
      });
      created(job);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };
  return <div className="modal-backdrop" data-testid="new-job-modal">
    <section className="modal" role="dialog" aria-modal="true">
      <div className="section-heading">
        <div><span className="eyebrow">BUSINESS CARDS</span><h2>Start a job</h2></div>
        <button className="icon-button" onClick={close} data-testid="new-job-close-button"><X /></button>
      </div>
      {error && <p className="notice warning" data-testid="new-job-error">{error}</p>}
      <form onSubmit={submit} data-testid="new-job-form">
        <label>Customer or company<input name="customer" required maxLength="180" data-testid="job-customer-input" /></label>
        <div className="form-grid">
          <label>Quantity<input name="quantity" type="number" defaultValue="500" min="1" max="1000000" required data-testid="job-quantity-input" /></label>
          <label>Sides<select name="sides" defaultValue="2" data-testid="job-sides-select"><option value="2">Front and back</option><option value="1">Front only</option></select></label>
          <label>Stock<select name="stock" data-testid="job-stock-select">{(settings?.stocks || []).map((stock) => <option key={stock}>{stock}</option>)}</select></label>
          <label>Finish<select name="finish" data-testid="job-finish-select"><option>Matte</option><option>Gloss</option><option>Soft touch</option><option>Uncoated</option></select></label>
          <label>Due date<input name="due" type="date" required data-testid="job-due-input" /></label>
          <div className="recipe-label"><span>Finished size</span><strong>{recipe?.width} × {recipe?.height} inches</strong><small>Recipe v{recipe?.version}</small></div>
        </div>
        <div className="modal-footer"><span><ShieldCheck size={14} />Recipe version stays with this job</span>
          <button className="primary" disabled={busy} data-testid="create-job-button">{busy ? "Saving…" : "Create job"}</button>
        </div>
      </form>
    </section>
  </div>;
}

function AssistantPanel({ job, settings, user, reload }) {
  const [message, setMessage] = useState("");
  const [stream, setStream] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    if (!message.trim() || busy) return;
    const text = message.trim();
    setMessage("");
    setStream("");
    setError("");
    setBusy(true);
    try {
      const response = await fetch(`${API}/jobs/${job.id}/chat`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      if (!response.ok || !response.body) {
        const data = await response.json();
        throw new Error(data.error || "The assistant could not start safely.");
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        let split = buffer.indexOf("\n\n");
        while (split >= 0) {
          const frame = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);
          const kind = frame.match(/^event: (.+)$/m)?.[1];
          const raw = frame.match(/^data: (.+)$/m)?.[1];
          if (raw) {
            const data = JSON.parse(raw);
            if (kind === "text") setStream((value) => value + data.text);
            if (kind === "error") setError(data.error);
          }
          split = buffer.indexOf("\n\n");
        }
      }
      await reload();
    } catch (reason) {
      setError(reason.message);
      setMessage(text);
    } finally {
      setBusy(false);
      setStream("");
    }
  };
  return <aside className="assistant-panel" data-testid="job-assistant-panel">
    <div className="assistant-heading">
      <div className="ai-icon"><Sparkles size={18} /></div>
      <div><strong>Print2Go Assistant</strong><p>{settings?.aiConnected ? "Backend configured" : "Setup needed"}</p></div>
    </div>
    <div className="chat-messages" data-testid="assistant-message-history">
      <div className="assistant-intro"><span className="eyebrow">LET’S MAKE THIS PRINT.</span><h3>One job.<br />A clear path forward.</h3><p>I explain verified records. Job controls always handle human decisions.</p></div>
      <div className="assistant-context"><FileText size={17} /><div>{job.customer}<small>{job.quantity.toLocaleString()} business cards · Recipe v{job.recipe.version}</small></div></div>
      {!settings?.aiConnected && <div className="notice" data-testid="assistant-unconfigured-notice">Assistant setup is unavailable. You can complete this workflow using the job controls.</div>}
      {(job.messages || []).map((item) => <div className={`message ${item.role}`} key={item.id}><span>{item.role === "user" ? user.name : "Assistant"}</span><p>{item.text}</p></div>)}
      {stream && <div className="message assistant" data-testid="assistant-streaming-message"><span>Assistant</span><p>{stream}</p></div>}
      {error && <div className="notice warning" data-testid="assistant-error">{error}</div>}
    </div>
    <form className="chat-compose" onSubmit={submit} data-testid="assistant-chat-form">
      <textarea value={message} onChange={(event) => setMessage(event.target.value)} maxLength="3000" rows="2" placeholder="Ask about this job…" data-testid="assistant-message-input" />
      <div><span>Grounded in saved job records</span><button className="send-button" disabled={busy || !message.trim()} data-testid="assistant-send-button"><Send size={16} /></button></div>
    </form>
  </aside>;
}

function JobView({ job, reload, back, settings, user, openSettings }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ack, setAck] = useState(false);
  const current = job.tasks.findIndex((task) => task.status !== "Completed");
  const task = job.tasks[current] || job.tasks[job.tasks.length - 1];
  const proof = latest(job, "PRINT_READY");
  const original = latest(job, "ORIGINAL");
  const act = async (action, extra = {}) => {
    setBusy(true);
    setError("");
    try {
      await api(`jobs/${job.id}/action`, {
        method: "POST",
        body: JSON.stringify({ action, generation: job.generation, ...extra }),
      });
      await reload();
      setAck(false);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };
  const upload = async (file) => {
    if (!file) return;
    setBusy(true);
    const data = new FormData();
    data.set("file", file);
    try {
      await api(`jobs/${job.id}/artwork`, { method: "POST", body: data });
      await reload();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };
  const process = async () => {
    setBusy(true);
    try {
      await api(`jobs/${job.id}/process`, { method: "POST", body: JSON.stringify({ generation: job.generation }) });
      await reload();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };
  const actionPanel = () => {
    if (current === 1 || (current <= 6 && task.status === "Blocked")) return <label className="upload-button primary" data-testid="artwork-upload-label"><Upload size={17} />{original ? "Upload revised artwork" : "Upload artwork"}<input type="file" accept="application/pdf" disabled={busy} data-testid="artwork-upload-input" onChange={(event) => upload(event.target.files?.[0])} /></label>;
    if (current === 2 || current === 4 || current === 5 || current === 6) return <button className="primary" onClick={process} disabled={busy} data-testid="process-artwork-button"><ShieldCheck size={17} />{busy ? "Checking…" : "Check artwork"}</button>;
    if (current === 3) return <div className="action-row"><button className="primary" disabled={busy} onClick={() => act("bleed", { decision: "blank-border" })} data-testid="accept-blank-border-button">Accept blank border</button><label className="button" data-testid="corrected-artwork-label">Upload corrected artwork<input type="file" accept="application/pdf" data-testid="corrected-artwork-input" onChange={(event) => upload(event.target.files?.[0])} /></label></div>;
    if (current === 7) return <HumanAction label="I reviewed the actual proof, margins, and all notes." buttonLabel="Approve proof" ack={ack} setAck={setAck} busy={busy} testId="approve-proof" onAction={() => act("approve", { sha: proof?.sha, acknowledged: ack })} />;
    if (current === 8) return <button className="primary" onClick={() => act("route")} disabled={busy} data-testid="select-route-button">Use production route</button>;
    if (current === 9) return <RIPAction action={act} busy={busy} />;
    if (current === 10) return <div className="action-row"><button className="primary" onClick={() => act("readiness")} disabled={busy} data-testid="check-readiness-button"><Link2 size={17} />Check shop readiness</button><button className="button" onClick={openSettings} data-testid="connect-shop-button">Connect shop</button></div>;
    if (current === 11) return <HumanAction label="I authorize staging this exact approved PDF. This does not print it." buttonLabel="Authorize production" ack={ack} setAck={setAck} busy={busy} testId="authorize-production" onAction={() => act("authorize", { sha: proof?.sha, acknowledged: ack })} />;
    if (current === 12) return <HumanAction label="The sheets have physically printed. A file copy does not count." buttonLabel="Confirm printed" ack={ack} setAck={setAck} busy={busy} testId="confirm-printed" onAction={() => act("printed", { acknowledged: ack })} />;
    if (current === 13) return <div><p className="notice" data-testid="cutting-instructions">{job.recipe.cutInstructions}</p><HumanAction label="The cards have been cut and finished as ordered." buttonLabel="Confirm cut" ack={ack} setAck={setAck} busy={busy} testId="confirm-cut" onAction={() => act("cut", { acknowledged: ack })} /></div>;
    if (current === 14 && task.status === "Needs attention") return <button className="primary" onClick={() => act("rework")} disabled={busy} data-testid="start-rework-button">Start rework</button>;
    if (current === 14) return <QCAction action={act} busy={busy} />;
    if (current === 15) return <PackAction action={act} busy={busy} />;
    return null;
  };
  const control = async (state) => {
    setBusy(true);
    try {
      await api(`jobs/${job.id}/control`, { method: "POST", body: JSON.stringify({ state }) });
      await reload();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };
  return <div className="job-shell" data-testid="job-detail-view">
    <div className="job-toolbar"><button className="text-button" onClick={back} data-testid="back-to-jobs-button"><ArrowLeft size={16} />All jobs</button><span className="job-id">JOB {job.id.slice(0, 8).toUpperCase()}</span>{job.state === "active" && <button className="text-button" onClick={() => control("paused")} data-testid="pause-job-button"><Pause size={16} />Pause</button>}{job.state === "paused" && <button className="text-button" onClick={() => control("active")} data-testid="resume-job-button"><Play size={16} />Resume</button>}{job.state !== "complete" && job.state !== "cancelled" && <button className="text-button" onClick={() => control("cancelled")} data-testid="cancel-job-button"><X size={16} />Cancel</button>}</div>
    <div className="split-workspace"><AssistantPanel job={job} settings={settings} user={user} reload={reload} />
    <div className="execution-panel">
      {error && <p className="notice warning" data-testid="job-action-error">{error}</p>}
      <div className="job-heading"><div><span className="eyebrow">BUSINESS CARDS · RECIPE V{job.recipe.version}</span><h1 data-testid="job-customer-title">{job.customer}</h1><p>{job.quantity.toLocaleString()} cards · {job.sides === 2 ? "Double-sided" : "Single-sided"} · Due {job.due}</p></div><Badge status={task.status} /></div>
      <div className="summary-strip"><div><span>Finished size</span><strong>{job.recipe.width} × {job.recipe.height} in</strong></div><div><span>Stock</span><strong>{job.stock}</strong></div><div><span>Finish</span><strong>{job.finish}</strong></div><div><span>Progress</span><strong>{job.tasks.filter((item) => item.status === "Completed").length} of 16 steps</strong></div></div>
      <div className="progress-line" data-testid="job-progress">{job.tasks.map((item) => <div key={item.id} className={item.status === "Completed" ? "done" : item.status === "Running" ? "running" : ""} />)}</div>
      <section className="next-action" data-testid="next-action-panel"><div className="next-label"><span className="eyebrow">YOUR NEXT STEP</span><span>Step {current + 1} of 16</span></div><h2>{task.title}</h2><p>{task.result}</p>{actionPanel()}</section>
      {proof && <section className="proof-section" data-testid="production-proof-section"><div className="section-heading"><h3>Production proof</h3><a className="text-button" href={`${API}/files/${job.id}/${proof.id}?download`} data-testid="download-print-ready-link"><Download size={15} />Download PDF</a></div><div className="proof-holder"><div className="proof-pages">{Array.from({ length: job.sides }).map((_, index) => <div className="proof-page" key={index}><p>{index ? "Back" : "Front"}</p><img src={`${API}/files/${job.id}/${proof.id}/preview/${index + 1}`} alt={`Proof page ${index + 1}`} data-testid={`proof-page-${index + 1}`} /></div>)}</div></div><div className="file-identity"><ShieldCheck size={15} /><span>Actual generated production file<small data-testid="print-ready-sha">SHA-256 {proof.sha}</small></span></div></section>}
      {job.inspection && <details className="inspection-details" open data-testid="inspection-details"><summary><AlertTriangle size={16} />Artwork inspection · {job.inspection.errors.length} blocking issue(s)</summary><div>{job.inspection.errors.map((item) => <p className="notice warning" key={item}>{item}</p>)}{job.inspection.warnings.map((item) => <p className="inspection-note" key={item}>{item}</p>)}</div></details>}
      <section className="tasks-section"><div className="section-heading"><h3>Production recipe</h3><span>{job.tasks.filter((item) => item.status === "Completed").length} / 16 complete</span></div><div className="task-list">{job.tasks.map((item, index) => <details className={`task ${index === current ? "current" : ""}`} key={item.id}><summary data-testid={`task-${index + 1}-summary`}><span className={`task-number ${item.status === "Completed" ? "done" : ""}`}>{item.status === "Completed" ? <Check size={15} /> : index + 1}</span><span className="task-title">{item.title}<small>{item.party === "Application" ? "Automated check" : "Human confirmation"}</small></span><Badge status={item.status} /></summary><div className="task-details"><p>{item.result}</p><div className="task-meta"><span>Updated {date(item.updated)}</span></div></div></details>)}</div></section>
    </div>
    </div>
  </div>;
}

function HumanAction({ label, buttonLabel, ack, setAck, busy, onAction, testId }) {
  return <div><label className="check-label"><input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} data-testid={`${testId}-checkbox`} />{label}</label><button className="primary" disabled={busy || !ack} onClick={onAction} data-testid={`${testId}-button`}>{buttonLabel}</button></div>;
}

function RIPAction({ action, busy }) {
  const [note, setNote] = useState("");
  return <div><label>RIP job name and imposition settings<input value={note} onChange={(event) => setNote(event.target.value)} minLength="5" data-testid="rip-note-input" /></label><button className="primary" disabled={busy || note.length < 5} onClick={() => action("handoff", { note })} data-testid="confirm-rip-staging-button">Confirm RIP staging</button></div>;
}

function QCAction({ action, busy }) {
  const [checks, setChecks] = useState({ quantity: false, alignment: false, appearance: false, finishing: false });
  return <div><div className="qc-grid">{Object.keys(checks).map((key) => <label className="check-label" key={key}><input type="checkbox" checked={checks[key]} onChange={(event) => setChecks({ ...checks, [key]: event.target.checked })} data-testid={`qc-${key}-checkbox`} />{key} passed</label>)}</div><button className="primary" disabled={busy} onClick={() => action("qc", { checks })} data-testid="record-qc-button">Record quality check</button></div>;
}

function PackAction({ action, busy }) {
  const [method, setMethod] = useState("collection");
  const [ack, setAck] = useState(false);
  return <div><label>Ready for<select value={method} onChange={(event) => setMethod(event.target.value)} data-testid="pack-method-select"><option value="collection">Customer collection</option><option value="delivery">Delivery</option></select></label><HumanAction label="The order is packed and labelled." buttonLabel="Complete job" ack={ack} setAck={setAck} busy={busy} testId="complete-job" onAction={() => action("pack", { method, acknowledged: ack })} /></div>;
}

function Recipes({ recipes, reload, user }) {
  const [message, setMessage] = useState("");
  const recipe = recipes[0];
  const save = async (event) => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api("recipes", { method: "POST", body: JSON.stringify(form) });
      setMessage("New recipe version saved. Existing jobs remain pinned.");
      reload();
    } catch (reason) { setMessage(reason.message); }
  };
  return <main className="settings-page" data-testid="recipes-page"><div className="page-heading"><div><span className="eyebrow">CONSISTENT PRINTS, EVERY TIME</span><h1>Recipes</h1><p className="muted">Each job keeps the version it started with.</p></div></div><div className="settings-layout"><section className="settings-card"><h3>{recipe?.name}</h3>{message && <p className="notice" data-testid="recipe-message">{message}</p>}<form onSubmit={save} data-testid="recipe-form"><fieldset disabled={user.role !== "admin"}><label>Recipe name<input name="name" defaultValue={recipe?.name} data-testid="recipe-name-input" /></label><div className="form-grid">{["width", "height", "bleed", "safe", "minDpi"].map((key) => <label key={key}>{key}<input name={key} type="number" step="0.001" defaultValue={recipe?.[key]} data-testid={`recipe-${key}-input`} /></label>)}</div><label>Cutting instructions<textarea name="cutInstructions" defaultValue={recipe?.cutInstructions} data-testid="recipe-instructions-input" /></label><button className="primary" data-testid="save-recipe-button">Save a new version</button></fieldset></form></section><aside className="settings-aside"><Layers size={25} /><h3>Version history</h3>{recipes.map((item) => <div className="version-row" key={item.version}><strong>v{item.version}</strong><span>{date(item.created)}</span></div>)}</aside></div></main>;
}

function Settings({ settings, user, reload }) {
  const [message, setMessage] = useState("");
  const save = async (event) => { event.preventDefault(); const form = new FormData(event.currentTarget); try { await api("settings", { method: "POST", body: JSON.stringify({ printer: form.get("printer"), stocks: String(form.get("stocks")).split("\n").filter(Boolean), sides: [1, 2], instructions: form.get("instructions") }) }); setMessage("Shop settings saved. Active jobs require a route review."); reload(); } catch (reason) { setMessage(reason.message); } };
  return <main className="settings-page" data-testid="settings-page"><div className="page-heading"><div><span className="eyebrow">PRINT2GO LONDON</span><h1>Shop settings</h1><p className="muted">Your route, connection and operators.</p></div><Badge status={settings.connected ? "Completed" : "Blocked"} /></div><div className="settings-layout"><div><section className="settings-card"><div className="section-heading"><h3>Production route</h3><Printer /></div>{message && <p className="notice" data-testid="settings-message">{message}</p>}<form onSubmit={save} data-testid="settings-form"><fieldset disabled={user.role !== "admin"}><label>Printer name<input name="printer" defaultValue={settings.printer} data-testid="printer-name-input" /></label><label>Supported stocks<textarea name="stocks" defaultValue={settings.stocks.join("\n")} data-testid="stocks-input" /></label><label>Handoff instructions<textarea name="instructions" defaultValue={settings.instructions} data-testid="handoff-instructions-input" /></label><button className="primary" data-testid="save-settings-button">Save shop settings</button></fieldset></form></section><section className="settings-card"><div className="section-heading"><h3>Connect shop</h3><Link2 /></div><p data-testid="connector-status">{settings.connected ? "The connector reports a writable destination." : "No verified local connection. Production readiness stays blocked."}</p><a className="button" href="/setup/print2go-connector.py" download data-testid="download-connector-link"><Download size={16} />Download local connector</a><details className="technical"><summary data-testid="connector-setup-summary">Connection setup</summary><ol><li>Configure the server and shop computer with the same connector secret.</li><li>Set the HTTPS Studio URL and a writable staging folder.</li><li>Run the connector. It stages authorized PDFs only; it never prints.</li></ol></details></section>{user.role === "admin" && <Operators />}</div><aside className="settings-aside"><ShieldCheck size={26} /><h3>A shop you can trust.</h3><p data-testid="assistant-status">Assistant: {settings.aiConnected ? "configured; first request verifies access" : "server setup needed"}</p><p>Local shop: {settings.connected ? "connected" : "disconnected"}</p><p>RIP integration: operator-assisted.</p></aside></div></main>;
}

function Operators() {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      await api("users", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))),
      });
      event.currentTarget.reset();
      setMessage("Operator account created.");
    } catch (reason) {
      setMessage(reason.message);
    } finally {
      setBusy(false);
    }
  };
  return <section className="settings-card" data-testid="operators-section">
    <div className="section-heading"><h3>Operators</h3><Users size={21} /></div>
    {message && <p className="notice" data-testid="operator-message">{message}</p>}
    <form onSubmit={submit} data-testid="operator-form">
      <div className="form-grid">
        <label>Name<input name="name" required maxLength="80" data-testid="operator-name-input" /></label>
        <label>Email<input name="email" type="email" required data-testid="operator-email-input" /></label>
      </div>
      <label>Initial password<input name="password" type="password" minLength="12" maxLength="200" required data-testid="operator-password-input" /></label>
      <label>Permission<select name="role" defaultValue="operator" data-testid="operator-role-select"><option value="operator">Operator</option><option value="admin">Administrator</option></select></label>
      <button className="button" disabled={busy} data-testid="create-operator-button"><Users size={15} />Add operator</button>
    </form>
  </section>;
}

function App() {
  const [auth, setAuth] = useState(null);
  const [view, setView] = useState("jobs");
  const [jobs, setJobs] = useState([]);
  const [recipes, setRecipes] = useState([]);
  const [settings, setSettings] = useState(null);
  const [job, setJob] = useState(null);
  const [newJob, setNewJob] = useState(false);
  const [theme, setTheme] = useState("light");
  const [error, setError] = useState("");
  const load = async () => { try { const [foundJobs, foundRecipes, foundSettings] = await Promise.all([api("jobs"), api("recipes"), api("settings")]); setJobs(foundJobs); setRecipes(foundRecipes); setSettings(foundSettings); } catch (reason) { setError(reason.message); } };
  useEffect(() => { api("auth").then(setAuth).catch((reason) => setError(reason.message)); }, []);
  useEffect(() => { if (auth?.user) load(); }, [auth?.user]);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  const open = async (item) => { const detail = await api(`jobs/${item.id}`); setJob(detail); };
  const reloadJob = async () => { if (job) { setJob(await api(`jobs/${job.id}`)); await load(); } };
  const nav = useMemo(() => [["jobs", "Jobs", FileText], ["recipes", "Recipes", Layers], ["settings", "Shop settings", Settings2]], []);
  if (!auth) return <div className="auth-shell" data-testid="loading-screen"><p>Opening your shop…</p></div>;
  if (!auth.user) return <Auth auth={auth} onSignedIn={(user) => setAuth({ user, needsSetup: false })} />;
  return <div className="app-shell" data-testid="studio-app"><header className="topbar"><button className="brand" onClick={() => { setView("jobs"); setJob(null); }} data-testid="brand-home-button"><Brand /></button><nav aria-label="Main navigation">{nav.map(([id, label, Icon]) => <button key={id} className={`nav-link ${view === id ? "selected" : ""}`} onClick={() => { setView(id); setJob(null); }} data-testid={`nav-${id}-button`}><Icon size={17} />{label}</button>)}</nav><div className="topbar-right"><button className="icon-button" onClick={() => setTheme(theme === "light" ? "dark" : "light")} data-testid="theme-toggle-button">{theme === "light" ? <Moon /> : <Sun />}</button><button className="text-button" onClick={async () => { await api("auth/logout", { method: "POST", body: "{}" }); setAuth({ user: null, needsSetup: false }); }} data-testid="logout-button"><LogOut size={16} />Sign out</button></div></header>{error && <div className="error-bar" data-testid="global-error"><AlertTriangle />{error}<button className="icon-button" onClick={() => setError("")} data-testid="dismiss-error-button"><X /></button></div>}{view === "jobs" && !job && <main className="jobs-page" data-testid="jobs-page"><div className="page-heading"><div><span className="eyebrow">YOUR PRODUCTION WORKSPACE</span><h1>Jobs</h1><p className="muted">Every order. Every step. A clear next action.</p></div><button className="primary" onClick={() => setNewJob(true)} data-testid="start-job-button"><Plus />Start a job</button></div>{!jobs.length ? <div className="empty-state" data-testid="jobs-empty-state"><FileText size={36} /><h2>Your first great print starts here.</h2><p>Create a business-card job, upload artwork and follow a clear path to an approved proof.</p><button className="primary" onClick={() => setNewJob(true)} data-testid="empty-start-job-button"><Plus />Start a job</button></div> : <div className="job-list">{jobs.map((item) => <button className="job-card" key={item.id} onClick={() => open(item)} data-testid={`job-card-${item.id}`}><div className="product-icon"><FileText /></div><div className="job-card-main"><strong>{item.customer}</strong><p>{item.quantity.toLocaleString()} business cards · {item.sides === 2 ? "Double-sided" : "Single-sided"}</p></div><div className="job-card-status"><Badge status={item.state === "complete" ? "Completed" : item.tasks.find((task) => task.status !== "Completed")?.status || "Completed"} /></div></button>)}</div>}<footer className="page-foot"><ShieldCheck size={15} />Approvals stay tied to the exact production file.</footer></main>}{view === "jobs" && job && <JobView job={job} settings={settings} user={auth.user} reload={reloadJob} back={() => { setJob(null); load(); }} openSettings={() => { setView("settings"); setJob(null); }} />}{view === "recipes" && <Recipes recipes={recipes} reload={load} user={auth.user} />}{view === "settings" && settings && <Settings settings={settings} user={auth.user} reload={load} />}{newJob && <JobModal recipes={recipes} settings={settings} close={() => setNewJob(false)} created={(created) => { setJob(created); setNewJob(false); load(); }} />}</div>;
}

export default App;