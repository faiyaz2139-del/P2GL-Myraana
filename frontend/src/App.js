import { useEffect, useMemo, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
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
import { API, api } from "@/api";
import { JobModal } from "@/JobForm";
import { Contact, Home, Legal, NotFound, Signup } from "@/site/Marketing";

const date = (value) => new Date(value).toLocaleString("en-CA", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const latest = (job, stage) => [...(job?.files || [])].reverse().find((file) => file.stage === stage);

function reviewHeadline(results) {
  const passed = (results || []).filter((item) => item.status === "PASS");
  const stopped = (results || []).find((item) => item.status === "STOP");
  if (!stopped) return { title: "Production review complete", detail: `${passed.length} checks passed.` };
  if (passed.length) return { title: `${passed.length} checks passed`, detail: `Stopped at ${stopped.agent}: ${stopped.summary}` };
  return { title: "Not production-ready", detail: stopped.summary || "Review stopped." };
}

function displayStatus(job, task) {
  if (job.state === "paused") return "Paused";
  if (job.state === "complete") return "Completed";
  if (job.state === "cancelled") return "Cancelled";
  if (job.statusLabel) return job.statusLabel;
  if (job.approval && task?.title === "Choose production route") return "Proof approved";
  return task?.status || "Pending";
}

function productLine(item) {
  const name = item.spec?.productName || item.recipe?.name || "Print";
  const sides = item.sides === 2 ? "Double-sided" : "Single-sided";
  return `${Number(item.quantity || 0).toLocaleString()} · ${name} · ${sides}`;
}

function trimNumber(value) {
  const number = Number(value);
  if (Number.isNaN(number)) return value;
  return String(number);
}

function Badge({ status }) {
  return <span className={`badge ${status.toLowerCase().replaceAll(" ", "-")}`} data-testid={`status-${status.toLowerCase().replaceAll(" ", "-")}`}>{status}</span>;
}

function Auth({ auth, onSignedIn }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const invite = params.get("invite") || "";
  const resetToken = invite ? "" : (params.get("reset") || "");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [forgot, setForgot] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    const formNode = event.currentTarget;
    const form = new FormData(formNode);
    setBusy(true);
    setError("");
    try {
      const result = invite
        ? await api("public/invites/accept", {
          method: "POST",
          body: JSON.stringify({
            token: invite,
            name: form.get("name"),
            password: form.get("password"),
          }),
        })
        : await api(`auth/${auth.needsSetup ? "setup" : "login"}`, {
          method: "POST",
          body: JSON.stringify({
            name: form.get("name"),
            email: form.get("email"),
            password: form.get("password"),
            shop: form.get("shop") || "",
          }),
        });
      onSignedIn(result.user);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  const requestReset = async (event) => {
    event.preventDefault();
    const formNode = event.currentTarget;
    const form = new FormData(formNode);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api("public/password-reset", {
        method: "POST",
        body: JSON.stringify({ email: form.get("email"), shop: form.get("shop") || "" }),
      });
      setNotice(result.message);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  const confirmReset = async (event) => {
    event.preventDefault();
    const formNode = event.currentTarget;
    const form = new FormData(formNode);
    setBusy(true);
    setError("");
    try {
      const result = await api("public/password-reset/confirm", {
        method: "POST",
        body: JSON.stringify({ token: resetToken, password: form.get("password") }),
      });
      setNotice(result.message);
      navigate("/login", { replace: true });
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  const heading = invite
    ? "Join your shop"
    : resetToken
      ? "Choose a new password"
      : forgot
        ? "Reset your password"
        : auth.needsSetup
          ? "Set up your shop"
          : "Welcome back";
  const intro = invite
    ? "Choose a password to accept this invite. It only joins the shop that sent it."
    : resetToken
      ? "This link works once. After you save, sign in with the new password."
      : forgot
        ? "Enter the email and the shop address. We reply the same way whether or not that account exists."
        : auth.needsSetup
          ? "Create the first administrator account."
          : "Sign in to continue your production work.";

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
      <div className="mobile-brand"><Brand /></div>
      <p className="tiny">Myraana for Print2Go, London.</p>
      <span className="eyebrow">YOUR SHOP WORKSPACE</span>
      <h2>{heading}</h2>
      <p className="muted">{intro}</p>
      {error && <div className="notice warning" role="alert" data-testid="auth-error">{error}</div>}
      {notice && <div className="notice" role="status" data-testid="auth-notice">{notice}</div>}
      {resetToken && <form onSubmit={confirmReset} data-testid="reset-confirm-form">
        <label>New password
          <input name="password" required type="password" minLength="12" maxLength="200"
            autoComplete="new-password" data-testid="reset-password-input" placeholder="At least 12 characters" />
        </label>
        <button className="primary wide" disabled={busy} data-testid="reset-confirm-button">
          {busy ? "Saving…" : "Save password"}
        </button>
      </form>}
      {!resetToken && forgot && <form onSubmit={requestReset} data-testid="reset-request-form">
        <label>Email
          <input name="email" required type="email" autoComplete="username"
            data-testid="reset-email-input" placeholder="you@yourshop.ca" />
        </label>
        <label>Shop address
          <input name="shop" required maxLength="80" autoComplete="off"
            data-testid="reset-shop-input" placeholder="print2go" />
        </label>
        <button className="primary wide" disabled={busy} data-testid="reset-request-button">
          {busy ? "Sending…" : "Send reset link"}
        </button>
        <button type="button" className="text-button" data-testid="reset-back-button" onClick={() => { setForgot(false); setNotice(""); setError(""); }}>
          Back to sign in
        </button>
      </form>}
      {!resetToken && !forgot && <form onSubmit={submit} data-testid={invite ? "invite-accept-form" : "auth-form"}>
        {(auth.needsSetup || invite) && <label>Your name
          <input name="name" required maxLength="80" autoComplete="name"
            data-testid="setup-name-input" placeholder="Shop administrator" />
        </label>}
        {!invite && <label>Email
          <input name="email" required type="email" autoComplete="username"
            data-testid="auth-email-input" placeholder="you@yourshop.ca" />
        </label>}
        {!invite && !auth.needsSetup && <label>Shop address
          <input name="shop" maxLength="80" autoComplete="off"
            data-testid="auth-shop-input" placeholder="Only if this email is used by more than one shop" />
        </label>}
        <label>Password
          <input name="password" required type="password" minLength="12" maxLength="200"
            autoComplete={auth.needsSetup || invite ? "new-password" : "current-password"}
            data-testid="auth-password-input" placeholder="At least 12 characters" />
        </label>
        <button className="primary wide" disabled={busy} data-testid="auth-submit-button">
          {busy ? "Saving…" : invite ? "Join shop" : auth.needsSetup ? "Create shop account" : "Sign in"}
        </button>
      </form>}
      {!invite && !resetToken && !forgot && !auth.needsSetup && <button type="button" className="text-button" data-testid="forgot-password-button" onClick={() => { setForgot(true); setError(""); }}>
        Forgot password?
      </button>}
      <p className="tiny"><ShieldCheck size={14} />Files and approvals stay in your shop.</p>
    </main>
  </div>;
}

function Brand() {
  return <div className="brand" data-testid="brand">
    <img className="brand-mark" src="/myraana-mark.svg" alt="" />
    <div className="brand-name">Myraana<small>PRODUCTION STUDIO</small></div>
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
      <div><strong>Myraana Assistant</strong><p>{settings?.aiConnected ? "Backend configured" : "Setup needed"}</p></div>
    </div>
    <div className="chat-messages" data-testid="assistant-message-history">
      <div className="assistant-intro"><span className="eyebrow">LET’S MAKE THIS PRINT.</span><h3>One job.<br />A clear path forward.</h3><p>I explain verified records. Job controls always handle human decisions.</p></div>
      <div className="assistant-context"><FileText size={17} /><div>{job.customer}<small>{productLine(job)} · Recipe v{job.recipe.version}</small></div></div>
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
  const [errorCode, setErrorCode] = useState("");
  const [ack, setAck] = useState(false);
  const [uploadAck, setUploadAck] = useState(false);
  const [agentReview, setAgentReview] = useState(null);
  const current = job.tasks.findIndex((task) => task.status !== "Completed");
  const task = job.tasks[current] || job.tasks[job.tasks.length - 1];
  const visualStatus = displayStatus(job, task);
  const accept = (settings?.artworkRules?.acceptedTypes || ["pdf", "jpg", "jpeg", "png", "gif", "eps", "ai", "psd"])
    .map((type) => `.${type}`).join(",");
  const proof = latest(job, "PRINT_READY");
  const original = latest(job, "ORIGINAL");
  const act = async (action, extra = {}) => {
    setBusy(true);
    setError("");
    setErrorCode("");
    try {
      await api(`jobs/${job.id}/action`, {
        method: "POST",
        body: JSON.stringify({ action, generation: job.generation, ...extra }),
      });
      await reload();
      setAck(false);
    } catch (reason) {
      setError(reason.message);
      setErrorCode(reason.code || "");
    } finally {
      setBusy(false);
    }
  };
  const upload = async (file) => {
    if (!file) return;
    if (!uploadAck) {
      setError("Confirm this is the artwork for the job before upload.");
      return;
    }
    setBusy(true);
    setError("");
    setErrorCode("");
    const data = new FormData();
    data.set("file", file);
    data.set("acknowledged", "true");
    try {
      await api(`jobs/${job.id}/artwork`, { method: "POST", body: data });
      setUploadAck(false);
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
  const runAgentReview = async () => {
    setBusy(true);
    setError("");
    try {
      const review = await api(`jobs/${job.id}/agents/evaluate`, { method: "POST" });
      setAgentReview(review);
      await reload();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };
  const artworkUpload = (label, labelId, inputId) => <div>
    <label className="check-label"><input type="checkbox" checked={uploadAck} onChange={(event) => setUploadAck(event.target.checked)} data-testid="artwork-acknowledge-checkbox" />This file is the artwork for this job.</label>
    <label className="upload-button primary" data-testid={labelId}><Upload size={17} />{label}<input type="file" accept={accept} disabled={busy || !uploadAck} data-testid={inputId} onChange={(event) => upload(event.target.files?.[0])} /></label>
  </div>;
  const actionPanel = () => {
    if (current === 1 || (current <= 6 && task.status === "Blocked")) return artworkUpload(original ? "Upload revised artwork" : "Upload artwork", "artwork-upload-label", "artwork-upload-input");
    if (current === 2 || current === 4 || current === 5 || current === 6) return <button className="primary" onClick={process} disabled={busy} data-testid="process-artwork-button"><ShieldCheck size={17} />{busy ? "Checking…" : "Check artwork"}</button>;
    if (current === 3 && (job.inspection?.bleed === "missing" && !job.bleedDecision)) return <div>
      <label className="check-label"><input type="checkbox" checked={uploadAck} onChange={(event) => setUploadAck(event.target.checked)} data-testid="artwork-acknowledge-checkbox" />This file is the artwork for this job.</label>
      <div className="action-row"><button className="primary" disabled={busy} onClick={() => act("bleed", { decision: "blank-border" })} data-testid="accept-blank-border-button">Accept blank border</button><label className="button" data-testid="corrected-artwork-label">Upload corrected artwork<input type="file" accept={accept} disabled={!uploadAck} data-testid="corrected-artwork-input" onChange={(event) => upload(event.target.files?.[0])} /></label></div>
    </div>;
    if (current === 3 && !job.bleedConfirmation) return <HumanAction label="I confirm the bleed and safe area on this file." buttonLabel="Confirm bleed handling" ack={ack} setAck={setAck} busy={busy} testId="confirm-bleed" onAction={() => act("confirm-bleed", { acknowledged: ack })} />;
    if (current === 3) return <button className="primary" onClick={process} disabled={busy} data-testid="process-artwork-button"><ShieldCheck size={17} />{busy ? "Checking…" : "Prepare print-ready file"}</button>;
    if (current === 7) return <HumanAction label="I reviewed the actual proof, margins, and all notes." buttonLabel="Approve proof" ack={ack} setAck={setAck} busy={busy} testId="approve-proof" onAction={() => act("approve", { sha: proof?.sha, acknowledged: ack })} />;
    if (current === 8) return <div>
      <div className="action-row">
        <button className="primary" onClick={() => act("route", { mode: "production" })} disabled={busy} data-testid="select-route-button">Use production route</button>
        <button className="button" onClick={() => act("route", { mode: "proof-only" })} disabled={busy} data-testid="proof-only-route-button">Proof only</button>
        <button className="text-button" onClick={openSettings} data-testid="verify-machine-link">Verify a machine in Shop settings</button>
      </div>
      {errorCode === "machine-required" && <p className="notice warning" data-testid="machine-required-notice">No verified press for this stock. Continue with a proof-only route, or verify a printer in Shop settings.</p>}
    </div>;
    if (current === 9) return <RIPAction action={act} busy={busy} />;
    if (current === 10) return <div className="action-row"><button className="primary" onClick={() => act("readiness")} disabled={busy} data-testid="check-readiness-button"><Link2 size={17} />Check shop readiness</button><button className="button" onClick={openSettings} data-testid="connect-shop-button">Connect shop</button></div>;
    if (current === 11) return <HumanAction label="I authorize staging this exact approved PDF. This does not print it." buttonLabel="Authorize production" ack={ack} setAck={setAck} busy={busy} testId="authorize-production" onAction={() => act("authorize", { sha: proof?.sha, acknowledged: ack })} />;
    if (current === 12) return <HumanAction label="The sheets have physically printed. A file copy does not count." buttonLabel="Confirm printed" ack={ack} setAck={setAck} busy={busy} testId="confirm-printed" onAction={() => act("printed", { acknowledged: ack })} />;
    if (current === 13) return <div><p className="notice" data-testid="cutting-instructions">{job.recipe.cutInstructions}</p><HumanAction label="The pieces have been cut and finished as ordered." buttonLabel="Confirm cut" ack={ack} setAck={setAck} busy={busy} testId="confirm-cut" onAction={() => act("cut", { acknowledged: ack })} /></div>;
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
      <div className="job-heading"><div><span className="eyebrow">{(job.spec?.productName || job.recipe?.name || "PRINT").toUpperCase()} · RECIPE V{job.recipe.version}</span><h1 data-testid="job-customer-title">{job.customer}</h1><p>{productLine(job)} · Due {job.due}</p></div><Badge status={visualStatus} /></div>
      <div className="summary-strip"><div><span>Finished size</span><strong>{job.spec ? `${trimNumber(job.spec.width)} × ${trimNumber(job.spec.height)} ${job.spec.unit}` : `${job.recipe.width} × ${job.recipe.height} in`}</strong></div><div><span>Stock</span><strong>{job.stock}</strong></div><div><span>Finish</span><strong>{job.finish}</strong></div><div><span>Progress</span><strong>{job.tasks.filter((item) => item.status === "Completed").length} of 16 steps</strong></div></div>
      <div className="progress-line" data-testid="job-progress">{job.tasks.map((item) => <div key={item.id} className={item.status === "Completed" ? "done" : item.status === "Running" ? "running" : ""} />)}</div>
      <section className="next-action" data-testid="production-review-panel"><div className="next-label"><span className="eyebrow">PRODUCTION REVIEW</span><span>{settings?.aiConnected ? "AI-assisted" : "Rule-based review"}</span></div><h2>Run AI Production Review</h2><p>Reviews saved job evidence only. It cannot approve, complete workflow steps, or print.</p><button className="button" onClick={runAgentReview} disabled={busy} data-testid="run-production-review-button"><ShieldCheck size={17} />{busy ? "Reviewing…" : "Run AI Production Review"}</button>{agentReview && <div className="inspection-details" data-testid="production-review-results"><div className="section-heading"><div><h3 data-testid="production-review-headline">{(agentReview.headline || reviewHeadline(agentReview.results)).title}</h3><p data-testid="production-review-detail">{(agentReview.headline || reviewHeadline(agentReview.results)).detail}</p></div><span>{settings?.aiConnected ? "AI-assisted" : "Rule-based review"}</span></div>{(agentReview.results || []).map((item) => <div className="inspection-note" key={`${agentReview.execution}-${item.agent}`}><strong>{item.agent} · {item.status}</strong><p>{item.summary}</p>{item.stop_reasons?.length > 0 && <p>Next: {item.stop_reasons.join(" ")}</p>}{item.warnings?.length > 0 && <p>Next: {item.warnings.join(" ")}</p>}{item.data?.selected_plan?.cost_estimate && <p data-testid="cost-estimate-summary">Cost {item.data.selected_plan.cost_estimate.total} · Margin {item.data.selected_plan.cost_estimate.profit_margin_percent ?? "unavailable"}%</p>}{item.data?.money_cost === "UNKNOWN" && <p data-testid="cost-inputs-missing">Cost inputs are unavailable; no cheapest route is claimed.</p>}</div>)}</div>}</section>
      <section className="next-action" data-testid="next-action-panel"><div className="next-label"><span className="eyebrow">YOUR NEXT STEP</span><span>Step {current + 1} of 16</span></div><h2>{task.title}</h2><p>{task.result}</p>{actionPanel()}</section>
      {proof && <section className="proof-section" data-testid="production-proof-section"><div className="section-heading"><h3>Production proof</h3><a className="text-button" href={`${API}/files/${job.id}/${proof.id}?download`} data-testid="download-print-ready-link"><Download size={15} />Download PDF</a></div><div className="proof-holder"><div className="proof-pages">{Array.from({ length: job.sides }).map((_, index) => <div className="proof-page" key={index}><p>{index ? "Back" : "Front"}</p><img src={`${API}/files/${job.id}/${proof.id}/preview/${index + 1}`} alt={`Proof page ${index + 1}`} data-testid={`proof-page-${index + 1}`} /></div>)}</div></div><div className="file-identity"><ShieldCheck size={15} /><span>Actual generated production file<small data-testid="print-ready-sha">SHA-256 {proof.sha}</small></span></div></section>}
      {job.inspection && <details className="inspection-details" open data-testid="inspection-details"><summary><AlertTriangle size={16} />Artwork inspection · {job.inspection.errors.length} blocking issue(s)</summary><div>{job.inspection.errors.map((item) => <p className="notice warning" key={item}>{item}</p>)}{job.inspection.actions?.map((item) => <p className="inspection-note" key={item}>Corrective action: {item}</p>)}{job.inspection.warnings.map((item) => <p className="inspection-note" key={item}>{item}</p>)}</div></details>}
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

function Recipes({ recipes, catalog, reload, user }) {
  const presets = (catalog?.presets || []).filter((item) => item.kind !== "service");
  const [productId, setProductId] = useState(presets.find((item) => item.id === "business-card")?.id || presets[0]?.id || "business-card");
  const [message, setMessage] = useState("");
  const versions = recipes.filter((item) => (item.product || item.id) === productId);
  const recipe = versions[0];
  const preset = presets.find((item) => item.id === productId);
  const save = async (event) => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api("recipes", { method: "POST", body: JSON.stringify({ ...form, product: productId }) });
      setMessage("New recipe version saved. Existing jobs remain pinned.");
      reload();
    } catch (reason) { setMessage(reason.message); }
  };
  return <main className="settings-page" data-testid="recipes-page">
    <div className="page-heading"><div><span className="eyebrow">SHOP EDITS</span><h1>Recipes</h1><p className="muted">A saved version is a shop override. New jobs still start from the catalog preset unless you leave size blank.</p></div></div>
    <div className="settings-layout">
      <section className="settings-card">
        <label>Product
          <select value={productId} onChange={(event) => setProductId(event.target.value)} data-testid="recipe-product-select">
            {(presets.length ? presets : [{ id: "business-card", name: "Business card" }, { id: "flyer", name: "Flyer" }]).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        {message && <p className="notice" data-testid="recipe-message">{message}</p>}
        <form key={productId} onSubmit={save} data-testid="recipe-form">
          <fieldset disabled={user.role !== "admin"}>
            <label>Recipe name<input name="name" defaultValue={recipe?.name || preset?.name || ""} data-testid="recipe-name-input" /></label>
            <div className="form-grid">{["width", "height", "bleed", "safe", "minDpi"].map((key) => <label key={key}>{key}<input name={key} type="number" step="0.001" defaultValue={recipe?.[key] ?? (key === "minDpi" ? 300 : "")} data-testid={`recipe-${key}-input`} /></label>)}</div>
            <label>Cutting instructions<textarea name="cutInstructions" defaultValue={recipe?.cutInstructions || ""} data-testid="recipe-instructions-input" /></label>
            <button className="primary" data-testid="save-recipe-button">Save a new version</button>
          </fieldset>
        </form>
      </section>
      <aside className="settings-aside"><Layers size={25} /><h3>Version history</h3>{versions.length ? versions.map((item) => <div className="version-row" key={`${item.id}-${item.version}`}><strong>{item.name} v{item.version}</strong><span>{date(item.created)}</span></div>) : <p>No saved version for this product yet. Jobs use the catalog preset.</p>}</aside>
    </div>
  </main>;
}

function ConnectorPairing({ settings, reload }) {
  const [pairing, setPairing] = useState(null);
  const [message, setMessage] = useState("");
  const start = async () => {
    try {
      const result = await api("connector-pairings", { method: "POST", body: "{}" });
      setPairing(result);
      setMessage("Enter this one-time code in the installed Windows Connector.");
      await reload();
    } catch (reason) {
      setMessage(reason.message);
    }
  };
  const approve = async (id) => {
    try {
      await api(`connector-pairings/${id}/approve`, { method: "POST", body: "{}" });
      setMessage("Approved. The connector will reconnect automatically.");
      await reload();
    } catch (reason) {
      setMessage(reason.message);
    }
  };
  return <section className="settings-card" data-testid="connector-pairing-panel">
    <div className="section-heading"><h3>Connect Windows Connector</h3><Link2 /></div>
    <p>Discovery is read-only. It cannot print, change printer settings, or release jobs.</p>
    <a className="button" href="https://github.com/faiyaz2139-del/P2GL-Myraana/releases/download/windows-connector-preview/MyraanaConnector.zip" data-testid="download-windows-connector-link">
      <Download size={16} />Download Windows Connector
    </a>
    <ol className="muted"><li>Download and extract the ZIP, then open MyraanaConnector.exe.</li><li>Click Pair connector here. Enter this website and the code in the connector window: <strong>{window.location.origin}</strong></li><li>Click Connect in the window, then Approve below.</li></ol>
    <p className="muted">Windows 10/11 only · Preview version · No Python or PowerShell setup required.</p>
    <button className="primary" onClick={start} data-testid="start-connector-pairing-button">
      Pair connector
    </button>
    {pairing && <p className="notice" data-testid="connector-pairing-code">
      One-time code: <strong>{pairing.code}</strong>
    </p>}
    {message && <p className="notice" data-testid="connector-pairing-message">{message}</p>}
    {(settings.pairings || []).filter((item) => item.status === "Found").map((item) => <div className="version-row" key={item.id} data-testid={`pending-connector-${item.id}`}>
      <span>{item.inventory?.hostname || "Windows connector"} · Found</span>
      <button className="button" onClick={() => approve(item.id)} data-testid={`approve-connector-${item.id}`}>Approve</button>
    </div>)}
    {(settings.pairedDevices || []).map((item) => <div className="version-row" key={item.id} data-testid={`paired-connector-${item.id}`}>
      <span>{item.inventory?.hostname || "Windows connector"} · {item.status}</span>
      <span>{item.inventory?.printers?.length || 0} discovered printer(s)</span>
    </div>)}
  </section>;
}

function CostProfiles() {
  const [profiles, setProfiles] = useState([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const fields = [
    ["material_per_sheet", "Material / sheet"],
    ["click_per_side", "Click / side"],
    ["setup", "Setup"],
    ["finishing_per_unit", "Finishing / unit"],
    ["labour_per_hour", "Labour / hour"],
    ["machine_per_hour", "Machine / hour"],
    ["waste_percent", "Waste %"],
    ["outsourcing", "Outsourcing"],
    ["sell_price_per_unit", "Sell price / unit"],
  ];
  const load = async () => {
    try {
      setProfiles(await api("cost-profiles"));
    } catch (reason) {
      setMessage(reason.message);
    }
  };
  useEffect(() => { load(); }, []);
  const save = async (event) => {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      await api("cost-profiles", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))),
      });
      event.currentTarget.reset();
      setMessage("Cost profile saved. Attach it to a verified machine plan before comparing routes.");
      await load();
    } catch (reason) {
      setMessage(reason.message);
    } finally {
      setBusy(false);
    }
  };
  return <section className="settings-card" data-testid="cost-profiles-panel">
    <div className="section-heading"><h3>Production cost inputs</h3><PackageCheck /></div>
    <p>Only configured inputs can support a lowest-cost recommendation.</p>
    {message && <p className="notice" data-testid="cost-profile-message">{message}</p>}
    <form onSubmit={save} data-testid="cost-profile-form">
      <label>Profile name<input name="name" required maxLength="100" data-testid="cost-profile-name-input" /></label>
      <div className="form-grid">{fields.map(([name, label]) => <label key={name}>{label}
        <input name={name} type="number" min="0" step="0.0001" required data-testid={`cost-${name}-input`} />
      </label>)}</div>
      <button className="primary" disabled={busy} data-testid="save-cost-profile-button">
        {busy ? "Saving…" : "Save cost inputs"}
      </button>
    </form>
    {profiles.map((profile) => <div className="version-row" key={profile.id} data-testid={`cost-profile-${profile.id}`}>
      <strong>{profile.name}</strong><span>Configured inputs</span>
    </div>)}
  </section>;
}

const FILE_TYPES = ["jpg", "jpeg", "gif", "png", "eps", "ai", "pdf", "psd"];

function ArtworkRules({ settings, user, reload }) {
  const rules = settings.artworkRules || {};
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const acceptedTypes = FILE_TYPES.filter((type) => form.get(`type-${type}`));
    setBusy(true);
    setMessage("");
    try {
      await api("artwork-rules", {
        method: "POST",
        body: JSON.stringify({
          bleedInches: form.get("bleedInches"),
          safeInches: form.get("safeInches"),
          imageDpi: form.get("imageDpi"),
          rasterTextDpi: form.get("rasterTextDpi"),
          outputDpi: form.get("outputDpi"),
          colourMode: form.get("colourMode"),
          rgbPolicy: form.get("rgbPolicy"),
          allowSpotColours: form.get("allowSpotColours") === "on",
          acceptedTypes,
          maxUploadMb: form.get("maxUploadMb"),
        }),
      });
      setMessage("Artwork rules saved. Jobs already started keep the rules they were given.");
      reload();
    } catch (reason) {
      setMessage(reason.message);
    } finally {
      setBusy(false);
    }
  };
  return <section className="settings-card" data-testid="artwork-rules-panel">
    <div className="section-heading"><h3>Artwork rules</h3><FileText /></div>
    <p>These are the shop defaults for new jobs. Print2Go starts from 1/8 in bleed, 1/4 in safe zone, CMYK, and 300 dpi.</p>
    {message && <p className="notice" data-testid="artwork-rules-message">{message}</p>}
    <form onSubmit={save} data-testid="artwork-rules-form">
      <fieldset disabled={user.role !== "admin" || busy}>
        <div className="form-grid">
          <label>Bleed (inches)<input name="bleedInches" type="number" step="0.001" min="0" max="1" defaultValue={rules.bleedInches ?? 0.125} data-testid="artwork-bleed-input" /></label>
          <label>Safe zone (inches)<input name="safeInches" type="number" step="0.001" min="0" max="1" defaultValue={rules.safeInches ?? 0.25} data-testid="artwork-safe-input" /></label>
          <label>Image DPI<input name="imageDpi" type="number" min="72" max="1200" defaultValue={rules.imageDpi ?? 300} data-testid="artwork-image-dpi-input" /></label>
          <label>Raster text and logo DPI<input name="rasterTextDpi" type="number" min="72" max="2400" defaultValue={rules.rasterTextDpi ?? 1200} data-testid="artwork-text-dpi-input" /></label>
          <label>Output DPI<input name="outputDpi" type="number" min="72" max="1200" defaultValue={rules.outputDpi ?? 300} data-testid="artwork-output-dpi-input" /></label>
          <label>Max upload (MB)<input name="maxUploadMb" type="number" min="1" max="150" defaultValue={Math.round((rules.maxUploadBytes || 150000000) / 1000000)} data-testid="artwork-upload-mb-input" /></label>
          <label>Colour mode<select name="colourMode" defaultValue={rules.colourMode || "CMYK"} data-testid="artwork-colour-select"><option>CMYK</option><option>RGB</option><option>ANY</option></select></label>
          <label>RGB uploads<select name="rgbPolicy" defaultValue={rules.rgbPolicy || "warn"} data-testid="artwork-rgb-select"><option value="warn">Warn and continue</option><option value="reject">Reject</option></select></label>
        </div>
        <label className="check-label"><input type="checkbox" name="allowSpotColours" defaultChecked={rules.allowSpotColours !== false} data-testid="artwork-spot-checkbox" />Allow Pantone and other spot colours</label>
        <div className="qc-grid">{FILE_TYPES.map((type) => <label className="check-label" key={type}><input type="checkbox" name={`type-${type}`} defaultChecked={(rules.acceptedTypes || FILE_TYPES).includes(type)} data-testid={`artwork-type-${type}`} />.{type}</label>)}</div>
        <button className="primary" data-testid="save-artwork-rules-button">{busy ? "Saving…" : "Save artwork rules"}</button>
      </fieldset>
    </form>
  </section>;
}

function DiscoveredPrinters({ settings, user, reload }) {
  const [message, setMessage] = useState("");
  const verify = async (printer) => {
    setMessage("");
    try {
      await api("printers/verify", {
        method: "POST",
        body: JSON.stringify({ name: printer.name, driver: printer.driver, port: printer.port, use: true }),
      });
      setMessage(`${printer.name} is verified for production.`);
      reload();
    } catch (reason) {
      setMessage(reason.message);
    }
  };
  const rows = settings.discoveredPrinters || [];
  return <section className="settings-card" data-testid="discovered-printers-panel">
    <div className="section-heading"><h3>Discovered printers</h3><Printer /></div>
    <p>Virtual printers such as Microsoft Print to PDF, OneNote, and Adobe PDF are hidden. A connected computer is not the same as a verified press.</p>
    {message && <p className="notice" data-testid="printer-verify-message">{message}</p>}
    {!rows.length && <p data-testid="printers-empty">No physical printers reported yet. A job can still use a proof-only route.</p>}
    {rows.map((printer) => {
      const slug = printer.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "printer";
      return <div className="version-row" key={`${printer.name}-${printer.port}`} data-testid={`printer-row-${slug}`}>
        <span><strong>{printer.name}</strong><br />{printer.deviceStatus} · {printer.productionStatus}</span>
        {user.role === "admin" && printer.productionStatus !== "Verified"
          ? <button className="button" onClick={() => verify(printer)} data-testid={`verify-printer-${slug}`}>Verify</button>
          : <Badge status={printer.productionStatus} />}
      </div>;
    })}
  </section>;
}

function Settings({ settings, user, reload }) {
  const [message, setMessage] = useState("");
  const [build, setBuild] = useState(null);
  useEffect(() => { api("build-info").then(setBuild).catch(() => setBuild(null)); }, []);
  const save = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api("settings", {
        method: "POST",
        body: JSON.stringify({
          shopName: form.get("shopName"),
          printer: form.get("printer"),
          stocks: String(form.get("stocks")).split("\n").filter(Boolean),
          sides: [1, 2],
          instructions: form.get("instructions"),
        }),
      });
      setMessage("Shop settings saved. Active jobs require a route review.");
      reload();
    } catch (reason) {
      setMessage(reason.message);
    }
  };
  return <main className="settings-page" data-testid="settings-page">
    <div className="page-heading">
      <div>
        <span className="eyebrow">{(settings.shopName || "Print2Go").toUpperCase()}</span>
        <h1>Shop settings</h1>
        <p className="muted">Route, artwork rules, printers, and operators.</p>
      </div>
      <Badge status={settings.connected ? "Connected" : "Offline"} />
    </div>
    <div className="settings-layout"><div>
      <section className="settings-card">
        <div className="section-heading"><h3>Production route</h3><Printer /></div>
        {message && <p className="notice" data-testid="settings-message">{message}</p>}
        <form onSubmit={save} data-testid="settings-form">
          <fieldset disabled={user.role !== "admin"}>
            <label>Shop name<input name="shopName" defaultValue={settings.shopName || "Print2Go"} maxLength="80" data-testid="shop-name-input" /></label>
            <label>Printer name<input name="printer" defaultValue={settings.printer} data-testid="printer-name-input" /></label>
            <label>Supported stocks<textarea name="stocks" defaultValue={(settings.stocks || []).join("\n")} data-testid="stocks-input" /></label>
            <label>Handoff instructions<textarea name="instructions" defaultValue={settings.instructions} data-testid="handoff-instructions-input" /></label>
            <button className="primary" data-testid="save-settings-button">Save shop settings</button>
          </fieldset>
        </form>
      </section>
      <ArtworkRules settings={settings} user={user} reload={reload} />
      <DiscoveredPrinters settings={settings} user={user} reload={reload} />
      <section className="settings-card">
        <div className="section-heading"><h3>Connect shop</h3><Link2 /></div>
        <p data-testid="connector-status">{settings.connected ? "The connector reports a writable destination." : "No verified local connection. Use a proof-only route until a press is verified."}</p>
        <a className="button" href="/setup/print2go-connector.py" download data-testid="download-connector-link"><Download size={16} />Download local connector</a>
        <details className="technical"><summary data-testid="connector-setup-summary">Connection setup</summary><ol><li>Configure the server and shop computer with the same connector secret.</li><li>Set the HTTPS Studio URL and a writable staging folder.</li><li>Run the connector. It stages authorized PDFs only; it never prints.</li></ol></details>
      </section>
      {user.role === "admin" && <ConnectorPairing settings={settings} reload={reload} />}
      {user.role === "admin" && <CostProfiles />}
      {user.role === "admin" && <Operators />}
    </div>
    <aside className="settings-aside">
      <ShieldCheck size={26} />
      <h3>A shop you can trust.</h3>
      <p data-testid="assistant-status">Assistant: {settings.aiConnected ? "configured; first request verifies access" : "server setup needed"}</p>
      <p>Local shop: {settings.connected ? "Connected" : "Offline"}</p>
      <p>Billing: {settings.billing?.enabled ? "configured" : "off"}</p>
      <p>RIP integration: operator-assisted.</p>
      {build && <p data-testid="build-info">Build {build.commit} · {build.builtAt}</p>}
    </aside>
    </div>
  </main>;
}

function Operators() {
  const [message, setMessage] = useState("");
  const [inviteMessage, setInviteMessage] = useState("");
  const [inviteLink, setInviteLink] = useState("");
  const [pending, setPending] = useState([]);
  const [busy, setBusy] = useState(false);
  const loadInvites = async () => {
    try {
      setPending(await api("invites"));
    } catch (reason) {
      setInviteMessage(reason.message);
    }
  };
  useEffect(() => { loadInvites(); }, []);
  const submit = async (event) => {
    event.preventDefault();
    const formNode = event.currentTarget;
    setBusy(true);
    try {
      await api("users", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(formNode))),
      });
      formNode.reset();
      setMessage("Operator account created.");
    } catch (reason) {
      setMessage(reason.message);
    } finally {
      setBusy(false);
    }
  };
  const invite = async (event) => {
    event.preventDefault();
    const formNode = event.currentTarget;
    setBusy(true);
    setInviteLink("");
    try {
      const result = await api("invites", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(formNode))),
      });
      formNode.reset();
      setInviteLink(`${window.location.origin}/login?invite=${result.token}`);
      setInviteMessage(result.emailed
        ? "Invite emailed. The link is below if you also want to copy it. It expires in 7 days and only joins this shop."
        : "Invite ready. Email was logged or not configured, so copy this link. It expires in 7 days and only joins this shop.");
      await loadInvites();
    } catch (reason) {
      setInviteMessage(reason.message);
    } finally {
      setBusy(false);
    }
  };
  const resend = async (id) => {
    setBusy(true);
    try {
      const result = await api(`invites/${id}/resend`, { method: "POST", body: "{}" });
      setInviteLink(`${window.location.origin}/login?invite=${result.token}`);
      setInviteMessage(result.emailed
        ? "Invite resent by email. The new link replaces the old one."
        : "Invite resent. Email was logged or not configured, so copy the new link.");
      await loadInvites();
    } catch (reason) {
      setInviteMessage(reason.message);
    } finally {
      setBusy(false);
    }
  };
  const revoke = async (id) => {
    setBusy(true);
    try {
      await api(`invites/${id}/revoke`, { method: "POST", body: "{}" });
      setInviteMessage("Invite revoked. That link can no longer be used.");
      await loadInvites();
    } catch (reason) {
      setInviteMessage(reason.message);
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
    <form onSubmit={invite} data-testid="invite-form">
      <label>Invite by email<input name="email" type="email" required data-testid="invite-email-input" /></label>
      <label>Permission<select name="role" defaultValue="operator" data-testid="invite-role-select"><option value="operator">Operator</option><option value="admin">Administrator</option></select></label>
      <button className="button" disabled={busy} data-testid="invite-operator-button">Create invite link</button>
    </form>
    {inviteMessage && <p className="notice" data-testid="invite-message">{inviteMessage}</p>}
    {inviteLink && <label>Invite link
      <input readOnly value={inviteLink} data-testid="invite-link" onFocus={(event) => event.target.select()} />
    </label>}
    {!!pending.length && <ul className="plain-list" data-testid="invite-list">
      {pending.map((item) => <li key={item.id} data-testid={`invite-row-${item.id}`}>
        <span>{item.email} · {item.role}{item.revoked ? " · revoked" : ""}</span>
        <button type="button" className="text-button" disabled={busy} data-testid={`invite-resend-${item.id}`} onClick={() => resend(item.id)}>Resend</button>
        {!item.revoked && <button type="button" className="text-button" disabled={busy} data-testid={`invite-revoke-${item.id}`} onClick={() => revoke(item.id)}>Revoke</button>}
      </li>)}
    </ul>}
  </section>;
}

function Studio() {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams();
  const jobId = params.jobId || location.pathname.match(/^\/jobs\/([^/]+)/)?.[1];
  const [auth, setAuth] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [recipes, setRecipes] = useState([]);
  const [settings, setSettings] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [job, setJob] = useState(null);
  const [newJob, setNewJob] = useState(false);
  const [theme, setTheme] = useState("light");
  const [error, setError] = useState("");
  const view = location.pathname.startsWith("/settings")
    ? "settings"
    : location.pathname.startsWith("/recipes")
      ? "recipes"
      : "jobs";
  const load = async () => {
    try {
      const [foundJobs, foundRecipes, foundSettings, foundCatalog] = await Promise.all([
        api("jobs"), api("recipes"), api("settings"), api("products"),
      ]);
      setJobs(foundJobs);
      setRecipes(foundRecipes);
      setSettings(foundSettings);
      setCatalog(foundCatalog);
    } catch (reason) {
      setError(reason.message);
    }
  };
  useEffect(() => { api("auth").then(setAuth).catch((reason) => setError(reason.message)); }, []);
  useEffect(() => { if (auth?.user && auth.user.role !== "superadmin") load(); }, [auth?.user]);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => {
    if (!auth?.user || view !== "jobs") return undefined;
    if (!jobId) {
      setJob(null);
      return undefined;
    }
    let cancelled = false;
    api(`jobs/${jobId}`).then((detail) => { if (!cancelled) setJob(detail); }).catch((reason) => setError(reason.message));
    return () => { cancelled = true; };
  }, [auth?.user, jobId, view]);
  const reloadJob = async () => {
    const id = job?.id || jobId;
    if (!id) return;
    setJob(await api(`jobs/${id}`));
    await load();
  };
  const nav = useMemo(() => [["jobs", "Jobs", FileText], ["recipes", "Recipes", Layers], ["settings", "Shop settings", Settings2]], []);
  if (!auth) return <div className="auth-shell" data-testid="loading-screen"><p>{error || "Opening your shop…"}</p></div>;
  if (!auth.user) {
    if (location.pathname !== "/login") return <Navigate to="/login" replace />;
    return <Auth auth={auth} onSignedIn={(user) => { setAuth({ user, needsSetup: false }); navigate("/jobs"); }} />;
  }
  if (auth.user.role === "superadmin") {
    return <div className="auth-shell" data-testid="platform-screen">
      <main className="auth-form">
        <h2>Platform administrator</h2>
        <p className="muted">This sign-in is not a shop workspace. Shop jobs, files, and settings stay inside each shop.</p>
        <button className="primary wide" data-testid="platform-sign-out-button" onClick={async () => { await api("auth/logout", { method: "POST", body: "{}" }); setAuth({ user: null, needsSetup: false }); navigate("/login"); }}>Sign out</button>
      </main>
    </div>;
  }
  if (location.pathname === "/login") return <Navigate to="/jobs" replace />;
  return <div className="app-shell" data-testid="studio-app">
    <header className="topbar">
      <button className="brand" onClick={() => navigate("/jobs")} data-testid="brand-home-button"><Brand /></button>
      <nav aria-label="Main navigation">{nav.map(([id, label, Icon]) => <button key={id} className={`nav-link ${view === id ? "selected" : ""}`} onClick={() => navigate(id === "jobs" ? "/jobs" : `/${id}`)} data-testid={`nav-${id}-button`}><Icon size={17} />{label}</button>)}</nav>
      <div className="topbar-right">
        <span className="shop-label" data-testid="shop-name-label">{settings?.shopName || "Print2Go"}</span>
        <button className="icon-button" onClick={() => setTheme(theme === "light" ? "dark" : "light")} data-testid="theme-toggle-button">{theme === "light" ? <Moon /> : <Sun />}</button>
        <button className="text-button" onClick={async () => { await api("auth/logout", { method: "POST", body: "{}" }); setAuth({ user: null, needsSetup: false }); navigate("/login"); }} data-testid="logout-button"><LogOut size={16} />Sign out</button>
      </div>
    </header>
    {error && <div className="error-bar" data-testid="global-error"><AlertTriangle />{error}<button className="icon-button" onClick={() => setError("")} data-testid="dismiss-error-button"><X /></button></div>}
    {view === "jobs" && !job && <main className="jobs-page" data-testid="jobs-page">
      <div className="page-heading"><div><span className="eyebrow">YOUR PRODUCTION WORKSPACE</span><h1>Jobs</h1><p className="muted">Every order. Every step. A clear next action.</p></div><button className="primary" onClick={() => setNewJob(true)} data-testid="start-job-button"><Plus />Start a job</button></div>
      {!jobs.length
        ? <div className="empty-state" data-testid="jobs-empty-state"><FileText size={36} /><h2>Your first great print starts here.</h2><p>Create a job from a product preset or custom specs, upload artwork, and follow a clear path to an approved proof.</p><button className="primary" onClick={() => setNewJob(true)} data-testid="empty-start-job-button"><Plus />Start a job</button></div>
        : <div className="job-list">{jobs.map((item) => {
          const task = item.tasks?.find((entry) => entry.status !== "Completed");
          return <button className="job-card" key={item.id} onClick={() => navigate(`/jobs/${item.id}`)} data-testid={`job-card-${item.id}`}><div className="product-icon"><FileText /></div><div className="job-card-main"><strong>{item.customer}</strong><p>{productLine(item)}</p></div><div className="job-card-status"><Badge status={displayStatus(item, task)} /></div></button>;
        })}</div>}
      <footer className="page-foot"><ShieldCheck size={15} />Approvals stay tied to the exact production file.</footer>
    </main>}
    {view === "jobs" && job && <JobView job={job} settings={settings} user={auth.user} reload={reloadJob} back={() => navigate("/jobs")} openSettings={() => navigate("/settings")} />}
    {view === "recipes" && <Recipes recipes={recipes} catalog={catalog} reload={load} user={auth.user} />}
    {view === "settings" && settings && <Settings settings={settings} user={auth.user} reload={load} />}
    {newJob && <JobModal catalog={catalog} settings={settings} close={() => setNewJob(false)} created={(created, defaults) => { setSettings((current) => ({ ...(current || {}), jobDefaults: defaults })); setJob(created); setNewJob(false); navigate(`/jobs/${created.id}`); load(); }} />}
  </div>;
}

function App() {
  return <BrowserRouter>
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/contact" element={<Contact />} />
      <Route path="/privacy" element={<Legal kind="privacy" />} />
      <Route path="/terms" element={<Legal kind="terms" />} />
      <Route element={<Studio />}>
        <Route path="/login" />
        <Route path="/jobs/:jobId?" />
        <Route path="/recipes" />
        <Route path="/settings" />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  </BrowserRouter>;
}

export default App;