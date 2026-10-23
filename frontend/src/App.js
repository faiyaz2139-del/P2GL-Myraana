import { useEffect, useMemo, useRef, useState } from "react";
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

function knownFinish(value) {
  const text = String(value || "").trim().toLowerCase();
  if (text === "matte" || text === "matt" || text === "matte cardstock") return "Matte";
  if (text === "glossy" || text === "gloss" || text === "gloss cardstock") return "Glossy";
  return "";
}

const QUEUE_GROUPS = [
  ["needs-you", "Needs you"],
  ["waiting-customer", "Waiting on customer"],
  ["ready-to-print", "Ready to print"],
  ["printing-cutting", "Printing/cutting"],
  ["done", "Done"],
];

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
      if (invite) {
        await api("public/invites/accept", {
          method: "POST",
          body: JSON.stringify({
            token: invite,
            name: form.get("name"),
            password: form.get("password"),
          }),
        });
      } else {
        await api(`auth/${auth.needsSetup ? "setup" : "login"}`, {
          method: "POST",
          body: JSON.stringify({
            name: form.get("name"),
            email: form.get("email"),
            password: form.get("password"),
            shop: form.get("shop") || "",
          }),
        });
      }
      const session = await api("auth");
      if (!session?.user) throw new Error("Sign in to your shop.");
      onSignedIn(session.user);
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

function JobTimeline({ job, busy, ack, setAck, onRun, onApprove, onLink, onEmail, email, setEmail, linkNote, onPrinted, onCut }) {
  const phases = Array.isArray(job.timeline) ? job.timeline : [];
  const failed = phases.some((phase) => phase.state === "failed");
  const approval = phases.find((phase) => phase.id === "approval");
  const press = phases.find((phase) => phase.id === "press");
  const proofOpen = phases.find((phase) => phase.id === "proof");
  const showRun = failed || proofOpen?.state === "current" || proofOpen?.state === "waiting";
  return <section className="next-action" data-testid="job-timeline">
    <div className="next-label"><span className="eyebrow">THIS JOB</span><span>Automatic mode</span></div>
    <ol className="job-timeline">{phases.map((phase) => <li key={phase.id} data-testid={`timeline-${phase.id}`} data-state={phase.state}><strong>{phase.title}</strong><span>{phase.state}</span>{phase.detail ? <p>{phase.detail}</p> : null}</li>)}</ol>
    {showRun && <button className="primary" disabled={busy} data-testid={failed ? "fix-and-retry-button" : "run-job-button"} onClick={onRun}>{failed ? "Fix and retry" : "Run job"}</button>}
    {approval?.state === "current" && <div className="action-row">
      <button className="primary" disabled={busy} data-testid="approved-by-customer-button" onClick={onApprove}>Approved by customer</button>
      <button className="button" disabled={busy} data-testid="copy-approval-link" onClick={onLink}>Copy approval link</button>
    </div>}
    {approval?.state === "current" && <label>Email the approval link<input value={email} onChange={(event) => setEmail(event.target.value)} data-testid="approval-email-input" /></label>}
    {approval?.state === "current" && <button className="button" disabled={busy || !email} data-testid="email-approval-link" onClick={onEmail}>Email the approval link</button>}
    {linkNote && <p className="notice" data-testid="approval-link-note">{linkNote}</p>}
    {job.automatic?.routeNote && <p className="notice" data-testid="automatic-route-note">{job.automatic.routeNote}</p>}
    {job.automatic?.error && <p className="notice warning" data-testid="automatic-error">{job.automatic.error}</p>}
    {press?.state === "current" && (job.tasks || [])[12]?.status !== "Completed" && <HumanAction label="The sheets have physically printed. A file copy does not count." buttonLabel="Confirm printed" ack={ack} setAck={setAck} busy={busy} testId="confirm-printed" onAction={onPrinted} />}
    {press?.state === "current" && (job.tasks || [])[12]?.status === "Completed" && (job.tasks || [])[13]?.status !== "Completed" && <HumanAction label="The pieces have been cut and finished as ordered." buttonLabel="Confirm cut" ack={ack} setAck={setAck} busy={busy} testId="confirm-cut" onAction={onCut} />}
  </section>;
}

function JobView({ job, reload, back, settings, user, openSettings, onArchived }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errorCode, setErrorCode] = useState("");
  const [ack, setAck] = useState(false);
  const [uploadAck, setUploadAck] = useState(false);
  const [agentReview, setAgentReview] = useState(null);
  const [proofFinish, setProofFinish] = useState(knownFinish(job.finish));
  const [showSteps, setShowSteps] = useState(false);
  const [approvalEmail, setApprovalEmail] = useState("");
  const [linkNote, setLinkNote] = useState("");
  const automatic = settings?.automaticMode !== false;
  useEffect(() => { setProofFinish(knownFinish(job.finish)); }, [job.id, job.finish]);
  useEffect(() => {
    if (!automatic || job.fieryHold?.status !== "queued") return undefined;
    const timer = setInterval(() => { reload(); }, 3000);
    return () => clearInterval(timer);
  }, [automatic, job.fieryHold?.status, job.id, reload]);
  const current = job.tasks.findIndex((task) => task.status !== "Completed");
  const task = job.tasks[current] || job.tasks[job.tasks.length - 1];
  const visualStatus = displayStatus(job, task);
  const accept = (settings?.artworkRules?.acceptedTypes || ["pdf", "jpg", "jpeg", "png", "gif", "eps", "ai", "psd"])
    .map((type) => `.${type}`).join(",");
  const proof = latest(job, "PRINT_READY");
  const original = latest(job, "ORIGINAL");
  const act = async (action, extra = {}, options = {}) => {
    setBusy(true);
    setError("");
    setErrorCode("");
    const controller = new AbortController();
    const onAbort = () => controller.abort();
    if (options.signal) {
      if (options.signal.aborted) controller.abort();
      else options.signal.addEventListener("abort", onAbort);
    }
    const timer = options.timeoutMs ? setTimeout(() => controller.abort(), options.timeoutMs) : null;
    const limited = Boolean(options.timeoutMs || options.signal);
    const untilAbort = (promise) => new Promise((resolve, reject) => {
      const fail = () => {
        const timeout = new Error("This took too long. Retry. Nothing was sent to a press.");
        timeout.code = "timeout";
        reject(timeout);
      };
      if (controller.signal.aborted) {
        fail();
        return;
      }
      const onLate = () => fail();
      controller.signal.addEventListener("abort", onLate);
      promise.then((value) => {
        controller.signal.removeEventListener("abort", onLate);
        resolve(value);
      }, (reason) => {
        controller.signal.removeEventListener("abort", onLate);
        reject(reason);
      });
    });
    try {
      const call = api(`jobs/${job.id}/action`, {
        method: "POST",
        body: JSON.stringify({ action, generation: job.generation, ...extra }),
        signal: limited ? controller.signal : undefined,
      });
      await (limited ? untilAbort(call) : call);
      const follow = reload();
      await (limited ? untilAbort(follow) : follow);
      setAck(false);
      return { ok: true };
    } catch (reason) {
      setError(routeFailureMessage(reason));
      setErrorCode(reason.code || "");
      return { ok: false, error: reason };
    } finally {
      if (timer) clearTimeout(timer);
      if (options.signal) options.signal.removeEventListener("abort", onAbort);
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
    {job.recipe?.production?.preset === "London BC" && <p className="notice" data-testid="file-location-rule">Ask for the design file location. Don't search for or guess the file. Open that file and confirm it belongs to {job.customer}.</p>}
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
    if (current === 7) {
      const card = job.product === "business-card" || job.spec?.product === "business-card" || job.recipe?.production?.preset === "London BC";
      if (!card) return <HumanAction label="I reviewed the actual proof, margins, and all notes." buttonLabel="Approve proof" ack={ack} setAck={setAck} busy={busy} testId="approve-proof" onAction={() => act("approve", { sha: proof?.sha, acknowledged: ack })} />;
      const coating = knownFinish(job.finish) || proofFinish;
      return <div data-testid="proof-approval">
        {knownFinish(job.finish)
          ? <p data-testid="proof-finish-known">Finish is {knownFinish(job.finish)}. The Fiery stock step will use it.</p>
          : <div data-testid="proof-finish-choice">
            <p>Confirm Matte or Glossy. This answers the Fiery stock step.</p>
            <div className="finish-choice">
              <button type="button" className={proofFinish === "Matte" ? "primary" : "button"} data-testid="proof-finish-matte" onClick={() => setProofFinish("Matte")}>Matte</button>
              <button type="button" className={proofFinish === "Glossy" ? "primary" : "button"} data-testid="proof-finish-glossy" onClick={() => setProofFinish("Glossy")}>Glossy</button>
            </div>
          </div>}
        <HumanAction label="I reviewed the actual proof, margins, and all notes." buttonLabel="Approve proof" ack={ack} setAck={setAck} busy={busy || !coating} testId="approve-proof" onAction={() => act("approve", { sha: proof?.sha, acknowledged: ack, finish: coating })} />
      </div>;
    }
    if (current === 8) return <RouteAction job={job} settings={settings} user={user} act={act} busy={busy} error={error} errorCode={errorCode} openSettings={openSettings} />;
    if (current === 9 && job.route?.mode === "proof-only") return <div>
      <p className="notice" data-testid="proof-only-stop">This job is a proof only, so it does not go to a press. Switch to production here if it should be printed.</p>
      <button className="primary" onClick={() => act("route", { mode: "production" })} disabled={busy} data-testid="switch-production-route-button">Switch to production route</button>
    </div>;
    if (current === 9 && job.fieryHold?.status === "queued") return <p className="notice" data-testid="fiery-hold-pending">Sending the PRINT_READY file to the Fiery hold queue. It stays on HOLD and will not print.</p>;
    if (current === 9 && job.route?.mode === "production" && job.fieryHold?.status !== "held" && (job.route.manual || oneFieryPress(settings?.discoveredPrinters) || isPrintOrder(job))) {
      return <ManualPressCard job={job} settings={settings} proof={proof} act={act} busy={busy} openSettings={openSettings} />;
    }
    if (current === 9 && job.productionChecklist) return <LondonChecklist job={job} action={act} busy={busy} />;
    if (current === 9) return <RIPAction action={act} busy={busy} />;
    if (current === 10) return <div>
      <p className="notice" data-testid="readiness-connector-notice">{readinessNotice(settings)}</p>
      <div className="action-row"><button className="primary" onClick={() => act("readiness")} disabled={busy} data-testid="check-readiness-button"><Link2 size={17} />Check shop readiness</button><button className="button" onClick={openSettings} data-testid="connect-shop-button">Connect shop</button></div>
    </div>;
    if (current === 11) return <HumanAction label="I authorize staging this exact approved PDF. This does not print it." buttonLabel="Authorize production" ack={ack} setAck={setAck} busy={busy} testId="authorize-production" onAction={() => act("authorize", { sha: proof?.sha, acknowledged: ack })} />;
    if (current === 12) return <HumanAction label="The sheets have physically printed. A file copy does not count." buttonLabel="Confirm printed" ack={ack} setAck={setAck} busy={busy} testId="confirm-printed" onAction={() => act("printed", { acknowledged: ack })} />;
    if (current === 13) {
      const cutter = job.recipe?.production?.cutter;
      const duplo = cutter
        ? (cutter.model === "Duplo DC-618" && Number(cutter.jobNumber ?? 2) === 2
          ? "Cut on Duplo DC-618, job 2"
          : `Cut on ${cutter.model || "Duplo DC-618"}, job ${cutter.jobNumber || 2}`)
        : job.recipe.cutInstructions;
      return <div><p className="notice" data-testid="cutting-instructions">{duplo}</p><HumanAction label="The pieces have been cut and finished as ordered." buttonLabel="Confirm cut" ack={ack} setAck={setAck} busy={busy} testId="confirm-cut" onAction={() => act("cut", { acknowledged: ack })} /></div>;
    }
    if (current === 14 && task.status === "Needs attention") return <button className="primary" onClick={() => act("rework")} disabled={busy} data-testid="start-rework-button">Start rework</button>;
    if (current === 14) return <QCAction action={act} busy={busy} />;
    if (current === 15) return <PackAction action={act} busy={busy} />;
    return null;
  };
  const readinessTried = useRef(false);
  useEffect(() => {
    if (current !== 10 || job.state !== "active" || readinessTried.current) return;
    readinessTried.current = true;
    act("readiness");
  }, [current, job.id, job.state]);
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
  const archive = async () => {
    setBusy(true);
    try {
      await api(`jobs/${job.id}/archive`, { method: "POST", body: "{}" });
      if (onArchived) await onArchived();
      else back();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };
  return <div className="job-shell" data-testid="job-detail-view">
    <div className="job-toolbar"><button className="text-button" onClick={back} data-testid="back-to-jobs-button"><ArrowLeft size={16} />All jobs</button><span className="job-id">JOB {job.id.slice(0, 8).toUpperCase()}</span>{job.state === "active" && <button className="text-button" onClick={() => control("paused")} data-testid="pause-job-button"><Pause size={16} />Pause</button>}{job.state === "paused" && <button className="text-button" onClick={() => control("active")} data-testid="resume-job-button"><Play size={16} />Resume</button>}{job.state !== "complete" && job.state !== "cancelled" && !job.archived && <button className="text-button" onClick={() => control("cancelled")} data-testid="cancel-job-button"><X size={16} />Cancel</button>}{user?.role === "admin" && !job.archived && <button className="text-button" onClick={archive} disabled={busy} data-testid="archive-job-button">Archive</button>}</div>
    <div className="split-workspace"><AssistantPanel job={job} settings={settings} user={user} reload={reload} />
    <div className="execution-panel">
      {error && <p className="notice warning" data-testid="job-action-error">{error}</p>}
      <div className="job-heading"><div><span className="eyebrow">{(job.spec?.productName || job.recipe?.name || "PRINT").toUpperCase()} · RECIPE V{job.recipe.version}</span><h1 data-testid="job-customer-title">{job.customer}</h1><p>{productLine(job)} · Due {job.due}</p></div><Badge status={visualStatus} /></div>
      <div className="summary-strip"><div><span>Finished size</span><strong>{job.spec ? `${trimNumber(job.spec.width)} × ${trimNumber(job.spec.height)} ${job.spec.unit}` : `${job.recipe.width} × ${job.recipe.height} in`}</strong></div><div><span>Stock</span><strong>{job.stock}</strong></div><div><span>Finish</span><strong>{job.finish}</strong></div><div><span>Progress</span><strong>{job.tasks.filter((item) => item.status === "Completed").length} of 16 steps</strong></div></div>
      <div className="progress-line" data-testid="job-progress">{job.tasks.map((item) => <div key={item.id} className={item.status === "Completed" ? "done" : item.status === "Running" ? "running" : ""} />)}</div>
      {job.cardRoute && <p className={`notice${job.cardRoute.stop ? " warning" : ""}`} data-testid="card-route"><StepKind kind={job.cardRoute.kind} /> {job.cardRoute.message}</p>}
      {automatic && <JobTimeline job={job} busy={busy} ack={ack} setAck={setAck} email={approvalEmail} setEmail={setApprovalEmail} linkNote={linkNote} onRun={() => act("run-job")} onApprove={() => act("approve", { sha: proof?.sha, acknowledged: true, finish: proofFinish || job.finish })} onLink={async () => { const result = await api(`jobs/${job.id}/proof-link`, { method: "POST", body: "{}" }); setLinkNote(result.url || ""); try { await navigator.clipboard.writeText(result.url || ""); } catch (reason) { setLinkNote(result.url || reason.message); } }} onEmail={async () => { const result = await api(`jobs/${job.id}/proof-link`, { method: "POST", body: JSON.stringify({ email: approvalEmail }) }); setLinkNote(result.emailed ? "The approval link was emailed. Approving does not print the job." : (result.url || "")); }} onPrinted={() => act("printed", { acknowledged: ack })} onCut={() => act("cut", { acknowledged: ack })} />}
      {automatic && <button type="button" className="text-button" data-testid="show-the-steps" onClick={() => setShowSteps((value) => !value)}>{showSteps ? "Hide the steps" : "Show the steps"}</button>}
      {(!automatic || showSteps) && <section className="next-action prominent" data-testid="next-action-panel"><div className="next-label"><span className="eyebrow">YOUR NEXT STEP</span><span>Step {Math.max(current, 0) + 1} of 16</span></div><h2>{current === 7 ? "Check the proof" : task.title}</h2><p>{task.result}</p>{job.fieryHold?.status === "failed" && <p className="notice warning" data-testid="fiery-hold-error">{job.fieryHold.error || "The Fiery Hold queue did not confirm the file. Nothing was printed."}</p>}{actionPanel()}</section>}
      {proof && <section className="proof-section" data-testid="production-proof-section"><div className="section-heading"><h3>Production proof</h3><a className="text-button" href={`${API}/files/${job.id}/${proof.id}?download`} data-testid="download-print-ready-link"><Download size={15} />Download PDF</a></div><div className="proof-holder"><div className="proof-pages">{Array.from({ length: job.sides }).map((_, index) => <div className="proof-page" key={index}><p>{index ? "Back" : "Front"}</p><img src={`${API}/files/${job.id}/${proof.id}/preview/${index + 1}`} alt={`Proof page ${index + 1}`} data-testid={`proof-page-${index + 1}`} /></div>)}</div></div><div className="file-identity"><ShieldCheck size={15} /><span>Actual generated production file<small data-testid="print-ready-sha">SHA-256 {proof.sha}</small></span></div></section>}
      {job.inspection && <details className="inspection-details" open={job.inspection.errors.length > 0} data-testid="inspection-details"><summary><AlertTriangle size={16} />Artwork inspection · {job.inspection.errors.length} blocking issue(s)</summary><div>{job.inspection.errors.map((item) => <p className="notice warning" key={item}>{item}</p>)}{job.inspection.actions?.map((item) => <p className="inspection-note" key={item}>Corrective action: {item}</p>)}{job.inspection.warnings.map((item) => <p className="inspection-note" key={item}>{item}</p>)}</div></details>}
      <details className="history-details" data-testid="done-automatically"><summary>Done automatically ({job.tasks.filter((item) => item.status === "Completed").length})</summary><section className="tasks-section"><div className="section-heading"><h3>Production recipe</h3><span>{job.tasks.filter((item) => item.status === "Completed").length} / 16 complete</span></div><div className="task-list">{job.tasks.map((item, index) => <details className={`task ${index === current ? "current" : ""}`} key={item.id}><summary data-testid={`task-${index + 1}-summary`}><span className={`task-number ${item.status === "Completed" ? "done" : ""}`}>{item.status === "Completed" ? <Check size={15} /> : index + 1}</span><span className="task-title">{item.title}<small>{item.party === "Application" ? "Automated check" : "Human confirmation"}</small></span><Badge status={item.status} /></summary><div className="task-details"><p>{item.result}</p><div className="task-meta"><span>Updated {date(item.updated)}</span></div></div></details>)}</div></section><ul className="audit-events" data-testid="job-history">{[...(job.events || [])].slice().reverse().map((event) => <li key={event.id}><p>{event.actor}: {event.text}</p></li>)}</ul><section className="history-details" data-testid="production-review-panel"><div className="next-label"><span className="eyebrow">PRODUCTION REVIEW</span><span>{settings?.aiConnected ? "AI-assisted" : "Rule-based review"}</span></div><h2>Run AI Production Review</h2><p>Reviews saved job evidence only. It cannot approve, complete workflow steps, or print.</p><button className="button" onClick={runAgentReview} disabled={busy} data-testid="run-production-review-button"><ShieldCheck size={17} />{busy ? "Reviewing…" : "Run AI Production Review"}</button>{agentReview && <div className="inspection-details" data-testid="production-review-results"><div className="section-heading"><div><h3 data-testid="production-review-headline">{(agentReview.headline || reviewHeadline(agentReview.results)).title}</h3><p data-testid="production-review-detail">{(agentReview.headline || reviewHeadline(agentReview.results)).detail}</p></div><span>{settings?.aiConnected ? "AI-assisted" : "Rule-based review"}</span></div>{(agentReview.results || []).map((item) => <div className="inspection-note" key={`${agentReview.execution}-${item.agent}`}><strong>{item.agent} · {item.status}</strong><p>{item.summary}</p>{item.stop_reasons?.length > 0 && <p>Next: {item.stop_reasons.join(" ")}</p>}{item.warnings?.length > 0 && <p>Next: {item.warnings.join(" ")}</p>}{item.data?.selected_plan?.cost_estimate && <p data-testid="cost-estimate-summary">Cost {item.data.selected_plan.cost_estimate.total} · Margin {item.data.selected_plan.cost_estimate.profit_margin_percent ?? "unavailable"}%</p>}{item.data?.money_cost === "UNKNOWN" && <p data-testid="cost-inputs-missing">Cost inputs are unavailable; no cheapest route is claimed.</p>}</div>)}</div>}</section></details>
    </div>
    </div>
  </div>;
}

function HumanAction({ label, buttonLabel, ack, setAck, busy, onAction, testId }) {
  return <div><label className="check-label"><input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} data-testid={`${testId}-checkbox`} />{label}</label><button className="primary" disabled={busy || !ack} onClick={onAction} data-testid={`${testId}-button`}>{buttonLabel}</button></div>;
}

function isPrintOrder(job) {
  const product = job?.spec?.product || job?.product || job?.recipe?.product || job?.recipe?.id || "";
  return product === "business-card" || product === "flyer";
}

function oneFieryPress(printers) {
  const fiery = (printers || []).filter((item) => item && item.isFiery && item.name);
  const hosts = new Set(fiery.map((item) => String(item.address || "").trim() || item.name));
  if (hosts.size !== 1) return "";
  const server = fiery.find((item) => /fiery|command\s*workstation|\befi\b|ex-li|ex-i\b|ex-p\b|\bpx\d|server/i.test(`${item.name} ${item.model || ""} ${item.driver || ""}`));
  return (server || fiery[0]).name;
}

function ManualPressCard({ job, settings, proof, act, busy, openSettings }) {
  const fiery = oneFieryPress(settings?.discoveredPrinters || []);
  const stock = job.stock || "the ordered stock";
  const flyer = (job.spec?.product || job.product || job.recipe?.product || job.recipe?.id) === "flyer";
  const impose = flyer ? "impose this flyer" : "impose with London BC";
  return <div data-testid="manual-fiery-card">
    {fiery && <button className="primary" disabled={busy} data-testid="send-fiery-hold-button" onClick={() => act("send-hold")}>Send to Fiery HOLD</button>}
    <p data-testid="manual-fiery-instructions">Print it yourself: download the PRINT_READY PDF, import it to Fiery, hold it, {impose}, set {stock}</p>
    <div className="action-row">
      {proof && <a className="button" href={`${API}/files/${job.id}/${proof.id}?download`} data-testid="download-print-ready-button"><Download size={16} />Download PRINT_READY</a>}
      <button className="primary" disabled={busy || !proof} data-testid="mark-sent-fiery-button" onClick={() => act("mark-sent")}>Mark sent to Fiery</button>
    </div>
    <button type="button" className="text-button" onClick={openSettings} data-testid="pair-connector-link">Pair the connector to send automatically</button>
  </div>;
}

function connectorOnline(settings) {
  if (!settings) return false;
  if (settings.connectorConnected) return true;
  if ((settings.pairedDevices || []).some((item) => item.status === "Connected")) return true;
  return Boolean(settings.connected);
}

function routeFailureMessage(reason) {
  if (!reason) return "The printer could not be verified. Retry.";
  if (reason.code === "timeout") return "Checking the printer took too long. Retry, or choose Proof only. Nothing was sent to a press.";
  if (reason.code === "network") return reason.message;
  if (reason.status === 409 || reason.code === "machine-required" || reason.code === "conflict") {
    return reason.message || "The shop could not accept this step. Retry, or choose Proof only. Nothing was sent to a press.";
  }
  return reason.message || "Unable to save. Please retry.";
}

function printerLabel(printer) {
  return [printer.name, printer.isFiery ? "Fiery" : "", printer.model, printer.address].filter(Boolean).join(" · ");
}

const PICKER_IDS = {
  settings: {
    root: "printer-picker",
    select: "printer-select",
    manual: "printer-name-input",
    scan: "scan-printers-button",
    spinner: "settings-printer-spinner",
    error: "settings-printer-error",
    retry: "settings-printer-retry",
    offline: "connector-offline-message",
    empty: "settings-printers-empty",
  },
  route: {
    root: "route-printer-picker",
    select: "inline-printer-select",
    manual: "inline-printer-input",
    scan: "route-scan-printers-button",
    spinner: "route-printer-spinner",
    error: "route-printer-error",
    retry: "route-printer-retry",
    offline: "route-connector-offline",
    empty: "route-printers-empty",
  },
};

function PrinterPicker({ settings, selected, onSelect, user, reload, testPrefix, onOpenSettings }) {
  const ids = PICKER_IDS[testPrefix] || PICKER_IDS.settings;
  const [printers, setPrinters] = useState(settings?.discoveredPrinters || []);
  const [online, setOnline] = useState(() => connectorOnline(settings));
  const [loading, setLoading] = useState(!(settings?.discoveredPrinters || []).length);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState("");
  const onSelectRef = useRef(onSelect);
  const scanLock = useRef(false);
  onSelectRef.current = onSelect;

  const apply = (data) => {
    const next = data?.printers || [];
    setPrinters(next);
    setOnline(Boolean(data?.connectorConnected));
    return { next, pending: Boolean(data?.scanPending), online: Boolean(data?.connectorConnected) };
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(!(settings?.discoveredPrinters || []).length);
    api("printers/discovered", { timeoutMs: 10000 }).then((data) => {
      if (!cancelled) apply(data);
    }).catch((reason) => {
      if (!cancelled) setError(reason.code === "timeout" ? "Looking for printers took too long. Retry." : (reason.message || "Printers could not be loaded. Retry."));
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [settings?.shopName]);

  useEffect(() => {
    const names = new Set(printers.map((item) => item.name));
    const choice = oneFieryPress(printers);
    if (choice && (!selected || !names.has(selected))) onSelectRef.current(choice);
  }, [printers, selected]);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      apply(await api("printers/discovered", { timeoutMs: 10000 }));
    } catch (reason) {
      setError(reason.code === "timeout" ? "Looking for printers took too long. Retry." : (reason.message || "Printers could not be loaded. Retry."));
    } finally {
      setLoading(false);
    }
  };

  const scan = async () => {
    if (scanLock.current) return;
    scanLock.current = true;
    setScanning(true);
    setError("");
    const started = Date.now();
    const budget = () => 10000 - (Date.now() - started);
    try {
      await api("printers/scan", { method: "POST", body: "{}", timeoutMs: Math.max(1000, budget()) });
      let latest = apply(await api("printers/discovered", { timeoutMs: Math.max(300, budget()) }));
      if (!latest.online || (latest.next.length && !latest.pending)) {
        if (reload) reload().catch(() => {});
        return;
      }
      while (budget() > 200) {
        latest = apply(await api("printers/discovered", { timeoutMs: Math.max(300, budget()) }));
        if (latest.next.length && !latest.pending) break;
        const pause = Math.min(1200, budget());
        if (pause <= 200) break;
        await new Promise((resolve) => setTimeout(resolve, pause));
      }
      if (!latest.next.length && latest.online) setError("No printers came back within 10 seconds. Retry.");
      if (reload) reload().catch(() => {});
    } catch (reason) {
      setError(reason.code === "timeout" || reason.code === "network"
        ? (reason.code === "timeout" ? "The scan took too long. Retry." : reason.message)
        : (reason.message || "The scan could not be requested. Retry."));
    } finally {
      scanLock.current = false;
      setScanning(false);
    }
  };

  const showSpinner = (loading || scanning) && printers.length === 0;
  const known = printers.some((item) => item.name === selected);
  return <div data-testid={ids.root}>
    {showSpinner && <p className="route-spinner" data-testid={ids.spinner}><i />Looking for printers. This stops after 10 seconds.</p>}
    {online && !!printers.length && <label>Printer
      <select value={known ? selected : ""} onChange={(event) => onSelect(event.target.value)} disabled={user?.role !== "admin"} data-testid={ids.select}>
        <option value="">Choose a printer</option>
        {printers.map((printer) => <option key={`${printer.name}-${printer.address || printer.port || ""}`} value={printer.name}>{printerLabel(printer)}</option>)}
      </select>
    </label>}
    {online && !printers.length && !showSpinner && <p data-testid={ids.empty}>No printers yet. Scan again, or check that the press is turned on.</p>}
    {!online && <div className="notice warning" data-testid={ids.offline}>
      <p>The shop connector is not connected, so Myraana cannot see printer names. Use Connect this computer at the top of the page. A Mac or Linux shop computer can use Other ways to connect. As a last resort, type the press name below.</p>
      {onOpenSettings && <button type="button" className="button" onClick={onOpenSettings} data-testid={`${testPrefix}-open-settings`}>Open shop settings</button>}
    </div>}
    {!online && user?.role === "admin" && <label>Printer name<input value={selected} onChange={(event) => onSelect(event.target.value)} data-testid={ids.manual} /></label>}
    {user?.role === "admin" && <div className="action-row">
      <button type="button" className="button" onClick={scan} disabled={scanning} data-testid={ids.scan}>{scanning ? "Scanning…" : "Scan again"}</button>
      {error && <button type="button" className="button" onClick={load} data-testid={ids.retry}>Retry</button>}
    </div>}
    {error && <p className="notice warning" data-testid={ids.error}>{error}</p>}
  </div>;
}

function RouteAction({ job, settings, user, act, busy, error, errorCode, openSettings }) {
  const [printer, setPrinter] = useState(settings?.printer || "");
  const [localError, setLocalError] = useState("");
  const [working, setWorking] = useState(false);
  useEffect(() => {
    setPrinter((current) => current || settings?.printer || "");
  }, [settings?.printer]);
  const stocks = settings?.stocks || [];
  const verified = settings?.verifiedPrinters || [];
  const stockListed = stocks.includes(job.stock);
  const savedPrinter = (settings?.printer || "").trim();
  const printerOk = Boolean(printer.trim()) && printer.trim() === savedPrinter && (verified.length === 0 || verified.includes(printer.trim()));
  const needsSetup = !stockListed || !printerOk;
  const printOrder = isPrintOrder(job);
  const verifyAndRoute = async () => {
    const name = printer.trim();
    if (name.length < 2) {
      setLocalError("Choose the press Myraana found. Virtual printers such as Print to PDF cannot be used.");
      return;
    }
    setWorking(true);
    setLocalError("");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      await api("printers/verify", { method: "POST", body: JSON.stringify({ name, use: true }), signal: controller.signal });
      await api("settings", {
        method: "POST",
        body: JSON.stringify({
          shopName: settings?.shopName || "Print2Go",
          printer: name,
          stocks: [...new Set([...stocks, job.stock])],
          sides: [1, 2],
          instructions: settings?.instructions || "",
        }),
        signal: controller.signal,
      });
      const outcome = await act("route", { mode: "production" }, { signal: controller.signal });
      if (outcome && outcome.ok === false) setLocalError(routeFailureMessage(outcome.error));
    } catch (reason) {
      setLocalError(routeFailureMessage(reason));
    } finally {
      clearTimeout(timer);
      setWorking(false);
    }
  };
  const choose = (mode) => {
    setLocalError("");
    return act("route", { mode }, { timeoutMs: 10000 });
  };
  return <div data-testid="route-step">
    <p className="notice">
      {printOrder && needsSetup
        ? `${job.stock} stays on the production route. Download the PRINT_READY file and send it to Fiery yourself, or pair the connector and it can be sent to HOLD.`
        : needsSetup
        ? `${job.stock} ${stockListed ? "is on the press list" : "is not on the press list yet"}. ${printerOk ? `${printer} can run it.` : "Choose the press Myraana found and verify it here. You do not need to leave this job."}`
        : `${printer} can run ${job.stock}. Production stages the file. Proof only stops before the press.`}
    </p>
    <PrinterPicker settings={settings} selected={printer} onSelect={setPrinter} user={user} testPrefix="route" onOpenSettings={openSettings} />
    {working && <p className="route-spinner" data-testid="route-step-spinner"><i />Checking the printer. This stops after 10 seconds if the shop does not answer.</p>}
    <div className="action-row">
      <button className="primary" onClick={() => choose("production")} disabled={busy || working || (needsSetup && !printOrder)} data-testid="select-route-button">Use production route</button>
      {user?.role === "admin" && needsSetup && <button className="button" onClick={verifyAndRoute} disabled={busy || working || printer.trim().length < 2} data-testid="inline-verify-printer-button">{working ? "Checking…" : "Verify printer and add this stock"}</button>}
      <button className="button" onClick={() => choose("proof-only")} disabled={busy || working} data-testid="proof-only-route-button">Proof only</button>
    </div>
    {user?.role !== "admin" && needsSetup && !printOrder && <p className="notice warning" data-testid="route-admin-needed">A shop admin needs to verify a printer for this stock. You can choose Proof only now.</p>}
    {user?.role !== "admin" && needsSetup && printOrder && <p className="notice" data-testid="route-stays-production">This job stays on the production route. Proof only is a separate choice.</p>}
    {(localError || errorCode === "machine-required" || errorCode === "conflict" || errorCode === "timeout" || errorCode === "network") && <p className="notice warning" data-testid="machine-required-notice">{localError || error || "Verify the printer above, or choose Proof only. Nothing is sent to a press until you do."}</p>}
  </div>;
}

function StepKind({ kind }) {
  const labels = {
    ask: "Ask the operator",
    photoshop: "Photoshop/auto-fix",
    fiery: "Fiery",
    decision: "Decision",
    stop: "Stop for review",
    start: "Start / finish",
  };
  return <span className={`kind-badge kind-${kind || "decision"}`}>{labels[kind] || kind}</span>;
}

function KindLegend() {
  const kinds = ["ask", "photoshop", "fiery", "decision", "stop", "start"];
  return <div className="kind-legend" data-testid="step-kind-legend">{kinds.map((kind) => <span key={kind} data-testid={`london-kind-${kind}`}><StepKind kind={kind} /></span>)}</div>;
}

function LondonChecklist({ job, action, busy }) {
  const steps = job.productionChecklist || [];
  const current = steps.find((step) => step.status !== "done");
  const cutter = job.recipe?.production?.cutter;
  const coating = knownFinish(job.finish);
  const stockSent = useRef(false);
  useEffect(() => {
    if (current?.id !== "stock" || !coating || job.productionStop || stockSent.current) return;
    stockSent.current = true;
    action("production-step", {
      step: "stock",
      ok: true,
      finish: coating,
      preset: job.recipe?.production?.preset || "London BC",
      held: true,
      file: job.cardRoute?.outputName,
      sheet: { stretched: false, cropped: false, missingCards: false },
    });
  }, [current?.id, coating, job.productionStop, job.id]);
  const advance = (extra = {}) => action("production-step", {
    step: current.id,
    ok: true,
    preset: job.recipe?.production?.preset || "London BC",
    held: true,
    file: job.cardRoute?.outputName,
    sheet: { stretched: false, cropped: false, missingCards: false },
    ...extra,
  });
  return <div data-testid="london-checklist">
    <KindLegend />
    {job.productionStop && <p className="notice warning" data-testid="london-stop">{job.productionStop}</p>}
    <ol className="london-steps">{steps.map((step) => <li key={step.id} data-testid={`london-step-${step.id}`} className={step.status}><StepKind kind={step.kind} /><strong>{step.title}</strong><p>{step.detail}</p></li>)}</ol>
    {cutter && <p data-testid="duplo-job">Duplo {cutter.model} job no. {cutter.jobNumber}, {cutter.jobName}. Slitter slots {(cutter.slitterSlots || []).join(" and ")}.</p>}
    {current?.id === "stock" && coating && !job.productionStop ? <p data-testid="london-stock-known">Finish is {coating}. Answering the Fiery stock step.</p> : current?.id === "stock" ? <div className="action-row">
      <button type="button" className="primary" disabled={busy} data-testid="london-stock-matte" onClick={() => advance({ finish: "Matte" })}>Select Matte cardstock</button>
      <button type="button" className="button" disabled={busy} data-testid="london-stock-glossy" onClick={() => advance({ finish: "Glossy" })}>Select Glossy cardstock</button>
    </div> : current && <button type="button" className="primary" disabled={busy} data-testid="london-step-advance" onClick={() => advance()}>{current.title}</button>}
  </div>;
}

function RIPAction({ action, busy }) {
  const [note, setNote] = useState("");
  return <div><label>RIP job name and imposition settings<input value={note} onChange={(event) => setNote(event.target.value)} minLength="5" data-testid="rip-note-input" /></label><button className="primary" disabled={busy || note.length < 5} onClick={() => action("handoff", { note })} data-testid="confirm-rip-staging-button">Confirm RIP staging</button></div>;
}

function QCAction({ action, busy }) {
  const labels = {
    quantity: "Quantity matches the order",
    alignment: "Alignment matches the proof",
    appearance: "Colour and type look right",
    finishing: "Fold, cut, and finish match the order",
  };
  const [checks, setChecks] = useState({ quantity: false, alignment: false, appearance: false, finishing: false });
  return <div><div className="qc-grid">{Object.keys(checks).map((key) => <label className="check-label" key={key}><input type="checkbox" checked={checks[key]} onChange={(event) => setChecks({ ...checks, [key]: event.target.checked })} data-testid={`qc-${key}-checkbox`} />{labels[key]}</label>)}</div><button className="primary" disabled={busy} onClick={() => action("qc", { checks })} data-testid="record-qc-button">Record quality check</button></div>;
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
    const body = { ...form, product: productId };
    if (recipe?.production) {
      body.production = {
        preset: form.presetName || recipe.production.preset,
        cutter: {
          jobNumber: Number(form.cutterJobNumber || recipe.production.cutter?.jobNumber || 2),
          jobName: recipe.production.cutter?.jobName,
          slitterSlots: recipe.production.cutter?.slitterSlots,
        },
      };
    }
    try {
      await api("recipes", { method: "POST", body: JSON.stringify(body) });
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
        <form key={`${productId}-${recipe?.version || 0}`} onSubmit={save} data-testid="recipe-form">
          <fieldset disabled={user.role !== "admin"}>
            <label>Recipe name<input name="name" defaultValue={recipe?.name || preset?.name || ""} data-testid="recipe-name-input" /></label>
            <div className="form-grid">{["width", "height", "bleed", "safe", "minDpi"].map((key) => <label key={key}>{key}<input name={key} type="number" step="0.001" defaultValue={recipe?.[key] ?? (key === "minDpi" ? 300 : "")} data-testid={`recipe-${key}-input`} /></label>)}</div>
            <label>Cutting instructions<textarea name="cutInstructions" defaultValue={recipe?.cutInstructions || ""} data-testid="recipe-instructions-input" /></label>
            {recipe?.production && <div data-testid="london-recipe">
              <h3>{recipe.workflow || "Business card workflow: file to Fiery"}</h3>
              <KindLegend />
              <p data-testid="london-orientations">Portrait cards: 2 × 3.5 in trim, 2.25 × 3.75 in with bleed. Same steps. Both orientations are accepted.</p>
              <p data-testid="london-safe-area">Safe area is 1/8 in inside the trim. The original file stays untouched. Fiery imports the PRINT_READY file, never the original.</p>
              <p data-testid="london-sheet">{recipe.production.preset} · {recipe.production.imposition?.sheetWidthIn} × {recipe.production.imposition?.sheetHeightIn} in · {recipe.production.imposition?.columns} × {recipe.production.imposition?.rows} = {recipe.production.imposition?.up} up</p>
              <p data-testid="london-cutter">{recipe.production.cutter?.model} job no. {recipe.production.cutter?.jobNumber}. Slitter slots {(recipe.production.cutter?.slitterSlots || []).join(" and ")}.</p>
              <div className="form-grid">
                <label>Fiery preset<input name="presetName" defaultValue={recipe.production.preset || "London BC"} data-testid="fiery-preset-name" /></label>
                <label>Cutter job number<input name="cutterJobNumber" type="number" min="1" max="999" defaultValue={recipe.production.cutter?.jobNumber ?? 2} data-testid="cutter-job-number" /></label>
              </div>
              <ol className="london-steps">{(recipe.production.steps || []).map((step) => <li key={step.id}><StepKind kind={step.kind} />{step.title}</li>)}</ol>
            </div>}
            <button className="primary" data-testid="save-recipe-button">Save a new version</button>
          </fieldset>
        </form>
      </section>
      <aside className="settings-aside"><Layers size={25} /><h3>Version history</h3>{versions.length ? versions.map((item) => <div className="version-row" key={`${item.id}-${item.version}`}><strong>{item.name} v{item.version}</strong><span>{date(item.created)}</span></div>) : <p>No saved version for this product yet. Jobs use the catalog preset.</p>}</aside>
    </div>
  </main>;
}

const PAIRING_POLL_MS = 3000;
const OPEN_PAIRING_KEY = "myraanaOpenPairing";

function readOpenPairing() {
  try {
    const raw = sessionStorage.getItem(OPEN_PAIRING_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && parsed.id ? parsed : null;
  } catch (error) {
    return null;
  }
}

function writeOpenPairing(value) {
  try {
    if (!value) sessionStorage.removeItem(OPEN_PAIRING_KEY);
    else sessionStorage.setItem(OPEN_PAIRING_KEY, JSON.stringify({ id: value.id, code: value.code || "" }));
  } catch (error) {
    /* A private window can block storage. This tab still holds the code. */
  }
}

function pairingStillValid(item, now = Date.now()) {
  if (!item || !item.id) return false;
  if (item.status !== "Searching" && item.status !== "Found") return false;
  const expires = Date.parse(item.expires_at || "");
  return !Number.isFinite(expires) || expires > now;
}

function newestFoundPairing(pairings, now = Date.now()) {
  const found = (pairings || []).filter((item) => item.status === "Found" && pairingStillValid(item, now));
  found.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
  return found[0] || null;
}

function lastSeenAgo(value, now = Date.now()) {
  const seen = Date.parse(value || "");
  if (!Number.isFinite(seen)) return "";
  const seconds = Math.max(0, Math.round((now - seen) / 1000));
  if (seconds < 60) return `${seconds} ${seconds === 1 ? "second" : "seconds"} ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} ${minutes === 1 ? "minute" : "minutes"} ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
}

function readinessDevice(settings) {
  const devices = (settings?.pairedDevices || []).filter((item) => item && (item.inventory?.hostname || item.lastSeen));
  const connected = devices.filter((item) => item.status === "Connected");
  const pool = connected.length ? connected : devices;
  return pool.slice().sort((a, b) => String(b.lastSeen || "").localeCompare(String(a.lastSeen || "")))[0] || null;
}

function readinessNotice(settings, now = Date.now()) {
  const device = readinessDevice(settings);
  if (!device) {
    return "The shop computer must be connected before this file can be staged. Open MyraanaConnector. It runs in the tray. This step does not print.";
  }
  const host = device.inventory?.hostname || "The shop computer";
  const ago = lastSeenAgo(device.lastSeen, now);
  const when = ago ? `Last seen ${ago}.` : "It has not checked in.";
  if (device.status === "Connected") {
    return `${host} is connected. ${when} This step does not print.`;
  }
  return `${host} is not connected. ${when} Open MyraanaConnector on ${host}. It runs in the tray.`;
}

function connectorTrayHint(device) {
  const host = device?.inventory?.hostname || "this computer";
  return `Open MyraanaConnector on ${host}. It runs in the tray.`;
}

function ConnectorPairing({ settings, openPairing, onStart }) {
  return <section className="settings-card" data-testid="connector-pairing-panel">
    <div className="section-heading"><h3>Connect Windows Connector</h3><Link2 /></div>
    <p data-testid="connector-pairing-scope">This code pairs a connector for this shop only. It finds your printers and can place approved PRINT_READY files on your Fiery HOLD queue. It never prints or releases jobs.</p>
    <div className="action-row">
      <a className="button" href="https://github.com/faiyaz2139-del/P2GL-Myraana/releases/download/windows-connector-preview/MyraanaConnector.zip" data-testid="download-windows-connector-link">
        <Download size={16} />Download Windows Connector
      </a>
      <a className="button" href="/setup/myraana-connector.py" download data-testid="download-connector-script-link">
        <Download size={16} />Mac or Linux script
      </a>
    </div>
    <ol className="muted"><li>On Windows, download and extract the ZIP, then open MyraanaConnector.exe. Closing that window leaves it running in the system tray. On a Mac or Linux computer that can see the press, download the script and run it with Python 3.</li><li>Click Pair connector here. Enter this website and the code in the connector window: <strong>{window.location.origin}</strong></li><li>Click Connect. A code created on this page a moment ago is approved for you. An older code, or a different computer, needs Approve next to that computer. The connector finds printers by itself.</li></ol>
    <p className="muted">Windows 10/11 only · No Python or PowerShell setup required. After pairing, opening the connector again reconnects with no code.</p>
    <button type="button" className="primary" onClick={onStart} data-testid="start-connector-pairing-button">
      Pair connector
    </button>
    {openPairing?.code && <p className="notice" data-testid="connector-pairing-code">
      One-time code: <strong>{openPairing.code}</strong>
    </p>}
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
    {!rows.length && <p data-testid="printers-empty">{connectorOnline(settings) ? "No physical printers reported yet. Use Scan again above. A job can still use a proof-only route." : "No printers yet. Start the shop connector and it will report them. A job can still use a proof-only route."}</p>}
    {rows.map((printer) => {
      const slug = printer.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "printer";
      return <div className="version-row" key={`${printer.name}-${printer.address || printer.port}`} data-testid={`printer-row-${slug}`}>
        <span><strong>{printer.name}{printer.isFiery ? " · Fiery" : ""}</strong><br />{[printer.model, printer.address, printer.protocol, printer.deviceStatus, printer.productionStatus].filter(Boolean).join(" · ")}</span>
        {user.role === "admin" && printer.productionStatus !== "Verified"
          ? <button className="button" onClick={() => verify(printer)} data-testid={`verify-printer-${slug}`}>Verify</button>
          : <Badge status={printer.productionStatus} />}
      </div>;
    })}
  </section>;
}

function Settings({ settings, user, reload }) {
  const location = useLocation();
  const [message, setMessage] = useState("");
  const [otherWays, setOtherWays] = useState(location.hash === "#other-ways");
  const [pairingMessage, setPairingMessage] = useState("");
  const [approveError, setApproveError] = useState("");
  const [openPairing, setOpenPairing] = useState(readOpenPairing);
  const [build, setBuild] = useState(null);
  const [printer, setPrinter] = useState(settings?.printer || "");
  const approving = useRef("");
  const reloadRef = useRef(reload);
  const approveRef = useRef(null);
  reloadRef.current = reload;
  const online = connectorOnline(settings);
  const offlineDevices = (settings.pairedDevices || []).filter((item) => item.status === "Offline");
  const pendingClaims = (settings.pairings || [])
    .filter((item) => item.status === "Found" && pairingStillValid(item))
    .slice()
    .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
  const newestClaim = newestFoundPairing(settings.pairings);
  const codeOpen = Boolean(openPairing?.id) || (settings.pairings || []).some((item) => pairingStillValid(item));
  useEffect(() => { api("build-info").then(setBuild).catch(() => setBuild(null)); }, []);
  useEffect(() => { if (location.hash === "#other-ways") setOtherWays(true); }, [location.hash]);
  useEffect(() => {
    if (!codeOpen) return undefined;
    const timer = setInterval(() => { reloadRef.current(); }, PAIRING_POLL_MS);
    return () => clearInterval(timer);
  }, [codeOpen]);
  const approve = async (id) => {
    setApproveError("");
    const target = id || newestClaim?.id;
    if (!target) {
      setApproveError("No pending connector was found.");
      return;
    }
    try {
      await api(`connector-pairings/${target}/approve`, { method: "POST", body: "{}" });
      const claim = (settings.pairings || []).find((item) => item.id === target) || newestClaim;
      const host = claim?.inventory?.hostname || "the shop computer";
      setPairingMessage(`Connected to ${host}`);
      if (openPairing?.id === target) {
        writeOpenPairing(null);
        setOpenPairing(null);
      }
      await reload();
    } catch (reason) {
      const text = reason?.message || "No pending connector was found.";
      setApproveError(text);
      setPairingMessage(text);
    }
  };
  const startPairing = async () => {
    setApproveError("");
    approving.current = "";
    try {
      const result = await api("connector-pairings", { method: "POST", body: "{}" });
      const next = { id: result.id, code: result.code };
      writeOpenPairing(next);
      setOpenPairing(next);
      setPairingMessage("Enter this one-time code in the installed Windows Connector.");
      await reload();
    } catch (reason) {
      setPairingMessage(reason?.message || "The pairing code could not be created.");
    }
  };
  approveRef.current = approve;
  useEffect(() => {
    if (user.role !== "admin" || !openPairing?.id) return undefined;
    const claim = (settings.pairings || []).find((item) => item.id === openPairing.id && item.status === "Found" && pairingStillValid(item));
    if (!claim || claim.manualApproval !== false || approving.current === claim.id) return undefined;
    approving.current = claim.id;
    approveRef.current(claim.id);
    return undefined;
  }, [settings.pairings, openPairing, user.role]);
  const save = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api("settings", {
        method: "POST",
        body: JSON.stringify({
          shopName: form.get("shopName"),
          printer,
          stocks: String(form.get("stocks")).split("\n").filter(Boolean),
          sides: [1, 2],
          instructions: form.get("instructions"),
          fieryAutoSend: form.get("fieryAutoSend") === "on",
          automaticMode: form.get("automaticMode") === "on",
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
      <Badge status={online ? "Connected" : "Offline"} />
    </div>
    {offlineDevices.map((item) => <p className="notice warning" key={item.id} data-testid={`connector-offline-hint-${item.id}`}>{connectorTrayHint(item)}</p>)}
    {user.role === "admin" && approveError && <p className="notice warning" data-testid="connector-approve-error">{approveError}</p>}
    {user.role === "admin" && pairingMessage && <p className="notice" data-testid="connector-pairing-message">{pairingMessage}</p>}
    {user.role === "admin" && pendingClaims.map((item) => <div className="notice pending-claim" key={item.id} data-testid={`pending-connector-${item.id}`}>
      <div>
        <strong>{item.inventory?.hostname || "Windows connector"}</strong>
        <p>This computer claimed the pairing code and is waiting.</p>
      </div>
      <button type="button" className="primary approve-claim" onClick={() => approve(item.id)} data-testid={`approve-connector-${item.id}`}>Approve</button>
    </div>)}
    <div className="settings-layout"><div>
      <section className="settings-card">
        <div className="section-heading"><h3>Production route</h3><Printer /></div>
        {message && <p className="notice" data-testid="settings-message">{message}</p>}
        <form onSubmit={save} data-testid="settings-form">
          <fieldset disabled={user.role !== "admin"}>
            <label>Shop name<input name="shopName" defaultValue={settings.shopName || "Print2Go"} maxLength="80" data-testid="shop-name-input" /></label>
            <PrinterPicker settings={settings} selected={printer} onSelect={setPrinter} user={user} reload={reload} testPrefix="settings" />
            <label>Supported stocks<textarea name="stocks" defaultValue={(settings.stocks || []).join("\n")} data-testid="stocks-input" /></label>
            <label>Handoff instructions<textarea name="instructions" defaultValue={settings.instructions} data-testid="handoff-instructions-input" /></label>
            <label className="check-label"><input type="checkbox" name="automaticMode" defaultChecked={settings.automaticMode !== false} data-testid="automatic-mode-toggle" />Automatic mode. Myraana runs the steps and stops for customer approval. Turn this off to use each step yourself.</label>
            <label className="check-label"><input type="checkbox" name="fieryAutoSend" defaultChecked={settings.fieryAutoSend === true} data-testid="fiery-auto-send-toggle" />After proof approval, send the PRINT_READY file to the Fiery hold queue. The job stays on HOLD and is never printed automatically.</label>
            <button className="primary" data-testid="save-settings-button">Save shop settings</button>
          </fieldset>
        </form>
      </section>
      <ArtworkRules settings={settings} user={user} reload={reload} />
      <DiscoveredPrinters settings={settings} user={user} reload={reload} />
      <section className="settings-card">
        <div className="section-heading"><h3>Connect shop</h3><Link2 /></div>
        <p data-testid="connector-status">{online ? "The shop connector is connected. It reports printers on this network, and Scan again asks it to look now." : offlineDevices.length ? offlineDevices.map(connectorTrayHint).join(" ") : "This computer is not connected. Use Connect this computer at the top of the page. Other ways to connect stays available for a pairing code."}</p>
        <p data-testid="connector-shop-note">Each shop pairs its own Windows Connector from this page. The pairing code belongs to this shop only.</p>
        {settings.legacyConnector && <a className="button" href="/setup/print2go-connector.py" download data-testid="download-connector-link"><Download size={16} />Download Print2Go legacy connector</a>}
        <details className="technical"><summary data-testid="connector-setup-summary">Connection setup</summary><ol><li>Pair this shop’s Windows Connector with the one-time code below. No shared secret is required.</li><li>The original Print2Go installation can keep using its server connector secret. That secret does not open another shop.</li><li>The connector stages authorized PDFs only. It never prints.</li></ol></details>
      </section>
      <section className="settings-card" id="other-ways">
        <button type="button" className="text-button" data-testid="other-ways-to-connect" onClick={() => setOtherWays((value) => !value)}>Other ways to connect</button>
        {otherWays && user.role === "admin" && <ConnectorPairing settings={settings} openPairing={openPairing} onStart={startPairing} />}
        {otherWays && user.role !== "admin" && <p className="muted">Ask an administrator for a pairing code, or use Connect this computer.</p>}
      </section>
      {user.role === "admin" && <CostProfiles />}
      {user.role === "admin" && <Operators user={user} />}
    </div>
    <aside className="settings-aside">
      <ShieldCheck size={26} />
      <h3>A shop you can trust.</h3>
      <p data-testid="assistant-status">Assistant: {settings.aiConnected ? "configured; first request verifies access" : "server setup needed"}</p>
      <p>Local shop: {online ? "Connected" : "Offline"}</p>
      <p>Billing: {settings.billing?.enabled ? "configured" : "off"}</p>
      <p>RIP integration: operator-assisted.</p>
      {build && <p data-testid="build-info">Build {build.commit} · {build.builtAt}</p>}
    </aside>
    </div>
  </main>;
}

function Operators({ user }) {
  const [message, setMessage] = useState("");
  const [inviteMessage, setInviteMessage] = useState("");
  const [inviteLink, setInviteLink] = useState("");
  const [pending, setPending] = useState([]);
  const [people, setPeople] = useState([]);
  const [busy, setBusy] = useState(false);
  const loadInvites = async () => {
    try {
      setPending(await api("invites"));
    } catch (reason) {
      setInviteMessage(reason.message);
    }
  };
  const loadPeople = async () => {
    try {
      setPeople(await api("users"));
    } catch (reason) {
      setMessage(reason.message);
    }
  };
  useEffect(() => { loadInvites(); loadPeople(); }, []);
  const removePerson = async (person) => {
    setBusy(true);
    setMessage("");
    try {
      await api(`users/${person.id}/remove`, { method: "POST", body: "{}" });
      setMessage(`${person.name} was removed. Their session has ended.`);
      await loadPeople();
    } catch (reason) {
      setMessage(reason.message);
    } finally {
      setBusy(false);
    }
  };
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
      await loadPeople();
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
    <div className="section-heading"><h3>People</h3><Users size={21} /></div>
    {message && <p className="notice" data-testid="operator-message">{message}</p>}
    <ul className="plain-list" data-testid="shop-users">
      {people.map((person) => <li key={person.id} data-testid={`shop-user-${person.id}`}>
        <span>{person.name} · {person.email} · {person.role}</span>
        {person.id !== user.id && <button type="button" className="text-button" disabled={busy} data-testid={`remove-user-${person.id}`} onClick={() => removePerson(person)}>Remove</button>}
      </li>)}
    </ul>
    <h3>Add someone</h3>
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

function PlatformScreen({ onSignedOut }) {
  const [shops, setShops] = useState([]);
  const [leads, setLeads] = useState([]);
  const [message, setMessage] = useState("");
  const [inviteLink, setInviteLink] = useState("");
  const [busy, setBusy] = useState(false);
  const load = async () => {
    const [shopRows, leadRows] = await Promise.all([api("platform/shops"), api("platform/leads")]);
    setShops(shopRows);
    setLeads(leadRows);
  };
  useEffect(() => { load().catch((reason) => setMessage(reason.message)); }, []);
  const run = async (path, created) => {
    setBusy(true);
    setMessage("");
    try {
      const result = await api(path, { method: "POST", body: "{}" });
      if (created && result.token) {
        setInviteLink(`${window.location.origin}/login?invite=${result.token}`);
        setMessage(result.emailed
          ? "Shop created and the owner invite was emailed."
          : "Shop created. Email was logged or not configured, so copy the owner invite.");
      } else if (created && result.already) {
        setInviteLink("");
        setMessage("That request already has a shop.");
      } else {
        setInviteLink("");
        setMessage("Shop updated.");
      }
      await load();
    } catch (reason) {
      setMessage(reason.message);
    } finally {
      setBusy(false);
    }
  };
  return <div className="auth-shell platform-shell" data-testid="platform-screen">
    <main className="platform-main">
      <div className="page-heading">
        <div>
          <span className="eyebrow">PLATFORM</span>
          <h1>Shops</h1>
          <p className="muted">Status and counts only. Job files, customers, and messages stay inside each shop.</p>
        </div>
        <button className="text-button" data-testid="platform-sign-out-button" onClick={onSignedOut}><LogOut size={16} />Sign out</button>
      </div>
      {message && <p className="notice" data-testid="platform-message">{message}</p>}
      {inviteLink && <label>Owner invite
        <input readOnly value={inviteLink} data-testid="platform-invite-link" onFocus={(event) => event.target.select()} />
      </label>}
      <div className="table-wrap">
        <table className="data-table" data-testid="platform-shops">
          <thead>
            <tr><th>Shop</th><th>Status</th><th>Created</th><th>Users</th><th>Jobs</th><th>Last activity</th><th></th></tr>
          </thead>
          <tbody>
            {shops.map((shop) => <tr key={shop.id} data-testid={`platform-shop-${shop.id}`}>
              <td><strong>{shop.name}</strong><div className="tiny">{shop.slug}</div></td>
              <td data-testid={`platform-status-${shop.id}`}>{shop.status}</td>
              <td>{shop.created ? String(shop.created).slice(0, 10) : ""}</td>
              <td>{shop.users}</td>
              <td>{shop.jobs}</td>
              <td>{shop.lastActivity ? String(shop.lastActivity).slice(0, 10) : ""}</td>
              <td className="row-actions">
                {shop.status !== "active" && <button type="button" className="button" disabled={busy} data-testid={`platform-approve-${shop.id}`} onClick={() => run(`platform/shops/${shop.id}/approve`)}>Approve</button>}
                {shop.status === "active" && <button type="button" className="button" disabled={busy} data-testid={`platform-suspend-${shop.id}`} onClick={() => run(`platform/shops/${shop.id}/suspend`)}>Suspend</button>}
              </td>
            </tr>)}
          </tbody>
        </table>
      </div>
      <h2>Requests</h2>
      <p className="muted">Turn a signup request into a shop. The owner receives an invite and chooses their own password.</p>
      {!leads.length && <p data-testid="platform-leads-empty">No open requests.</p>}
      {!!leads.length && <ul className="plain-list" data-testid="platform-leads">
        {leads.map((lead) => <li key={lead.id} data-testid={`platform-lead-${lead.id}`}>
          <span><strong>{lead.shop}</strong> · {lead.name} · {lead.email}{lead.city ? ` · ${lead.city}` : ""}</span>
          <button type="button" className="button" disabled={busy} data-testid={`platform-create-shop-${lead.id}`} onClick={() => run(`platform/leads/${lead.id}/approve`, true)}>Create shop</button>
        </li>)}
      </ul>}
    </main>
  </div>;
}

const THIS_COMPUTER_KEY = "myraana.thisComputer";

function onWindows() {
  return typeof navigator !== "undefined" && /Windows/i.test(navigator.userAgent || "");
}

function rememberedComputer() {
  try {
    return localStorage.getItem(THIS_COMPUTER_KEY) || "";
  } catch (error) {
    return "";
  }
}

function rememberComputer(id) {
  try {
    if (id) localStorage.setItem(THIS_COMPUTER_KEY, id);
  } catch (error) {
    return;
  }
}

function fieryBannerName(settings) {
  const printers = settings?.discoveredPrinters || [];
  const names = printers.map((item) => item?.name || "").join(" ");
  const printer = settings?.printer || "";
  const text = `${names} ${printer}`;
  if (/EX-Li PX300/i.test(text)) return "EX-Li PX300";
  const fiery = printers.find((item) => item?.isFiery && item.name);
  return fiery?.name || printer;
}

function connectedDevices(settings) {
  return (settings?.pairedDevices || []).filter((item) => item?.status === "Connected");
}

function connectBannerState(settings, user, pending) {
  if (!user || !onWindows()) return null;
  if (user.role !== "admin" && user.role !== "operator") return null;
  if (!settings) return null;
  const connected = connectedDevices(settings);
  const remembered = rememberedComputer();
  const mine = connected.find((item) => item.id === remembered);
  const fiery = fieryBannerName(settings);
  if (mine && fiery && !pending) return { kind: "ready", fiery };
  return { kind: "connect" };
}

async function downloadConnectorSetup() {
  const response = await fetch(`${API}/connector-enrollments`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!response.ok) {
    let message = "The setup file could not be downloaded.";
    try {
      const data = await response.json();
      if (data?.error) message = data.error;
    } catch (error) {
      message = "The setup file could not be downloaded.";
    }
    throw new Error(message);
  }
  const header = response.headers.get("Content-Disposition") || "";
  const match = /filename="([^"]+)"/.exec(header);
  const filename = match ? match[1] : "";
  if (!filename.startsWith("MyraanaConnector-Setup-") || !filename.toLowerCase().endsWith(".exe")) {
    throw new Error("Download Connect this computer again. Open that file. Do not rename it.");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function ConnectComputerBanner({ settings, user, pending, hint, onConnect, onOther }) {
  const state = connectBannerState(settings, user, pending);
  if (!state) return null;
  if (state.kind === "ready") {
    return <div className="connect-banner ready" data-testid="connect-this-computer-ready">This computer is connected · Fiery {state.fiery} ready</div>;
  }
  return <div className="connect-banner" data-testid="connect-this-computer-banner">
    <div>
      <h2>Connect this computer to your printers</h2>
      <button type="button" className="text-button" data-testid="banner-other-ways" onClick={onOther}>Other ways to connect</button>
    </div>
    <button type="button" className="primary" data-testid="connect-this-computer-button" onClick={onConnect}>Connect this computer</button>
    {hint && <p className="download-hint" data-testid="connect-download-hint">Open the file that just downloaded. That's it.<span className="download-arrow" aria-hidden="true">↓</span></p>}
  </div>;
}

function Studio() {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams();
  const jobId = params.jobId || location.pathname.match(/^\/jobs\/([^/]+)/)?.[1];
  const [auth, setAuth] = useState(null);
  const authEpoch = useRef(0);
  const [queue, setQueue] = useState({ group: "needs-you", counts: {}, jobs: [], nextCursor: null });
  const queueGroup = useRef("needs-you");
  const [recipes, setRecipes] = useState([]);
  const [settings, setSettings] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [job, setJob] = useState(null);
  const [newJob, setNewJob] = useState(false);
  const [setupHint, setSetupHint] = useState(false);
  const [setupSnapshot, setSetupSnapshot] = useState({});
  const [setupError, setSetupError] = useState("");
  const [theme, setTheme] = useState("light");
  const [error, setError] = useState("");
  const view = location.pathname.startsWith("/settings")
    ? "settings"
    : location.pathname.startsWith("/recipes")
      ? "recipes"
      : "jobs";
  const load = async (group, cursor, append) => {
    const selected = group || queueGroup.current || "needs-you";
    try {
      const params = new URLSearchParams({ group: selected, limit: "50" });
      if (cursor) params.set("cursor", cursor);
      const [page, foundRecipes, foundSettings, foundCatalog] = await Promise.all([
        api(`jobs?${params}`), api("recipes"), api("settings"), api("products"),
      ]);
      const nextGroup = page.group || selected;
      queueGroup.current = nextGroup;
      setQueue((current) => ({
        group: nextGroup,
        counts: page.counts || {},
        jobs: append ? [...current.jobs, ...(page.jobs || [])] : (page.jobs || []),
        nextCursor: page.nextCursor || null,
      }));
      setRecipes(foundRecipes);
      setSettings(foundSettings);
      setCatalog(foundCatalog);
    } catch (reason) {
      setError(reason.message);
    }
  };
  useEffect(() => {
    const epoch = ++authEpoch.current;
    api("auth").then((session) => {
      if (epoch !== authEpoch.current) return;
      setAuth((current) => (current?.user ? current : session));
    }).catch((reason) => {
      if (epoch === authEpoch.current) setError(reason.message);
    });
  }, []);
  const shopOpen = !auth?.user?.shop_status || auth.user.shop_status === "active";
  useEffect(() => { if (auth?.user && auth.user.role !== "superadmin" && shopOpen) load(); }, [auth?.user, shopOpen]);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => {
    if (!auth?.user || !shopOpen || auth.user.role === "superadmin" || view !== "jobs") return undefined;
    if (!jobId) {
      setJob(null);
      return undefined;
    }
    let cancelled = false;
    api(`jobs/${jobId}`).then((detail) => { if (!cancelled) setJob(detail); }).catch((reason) => setError(reason.message));
    return () => { cancelled = true; };
  }, [auth?.user, jobId, view, shopOpen]);
  const reloadJob = async () => {
    const id = job?.id || jobId;
    if (!id) return null;
    const detail = await api(`jobs/${id}`);
    setJob(detail);
    await load();
    return detail;
  };
  const banner = connectBannerState(settings, auth?.user, setupHint);
  useEffect(() => {
    if (!banner || banner.kind === "ready") return undefined;
    const timer = setInterval(() => { load(); }, PAIRING_POLL_MS);
    return () => clearInterval(timer);
  }, [banner?.kind, auth?.user, shopOpen]);
  useEffect(() => {
    if (!setupHint) return;
    const fiery = fieryBannerName(settings);
    const connected = connectedDevices(settings);
    const arrived = connected.filter((item) => !(item.id in setupSnapshot));
    const updated = connected.filter((item) => item.id in setupSnapshot && item.lastSeen !== setupSnapshot[item.id]);
    const chosen = arrived[0] || updated.slice().sort((left, right) => String(right.lastSeen || "").localeCompare(String(left.lastSeen || "")))[0];
    if (!chosen || !fiery) return;
    rememberComputer(chosen.id);
    setSetupHint(false);
  }, [setupHint, settings, setupSnapshot]);
  const connectThisComputer = async () => {
    setSetupError("");
    const snapshot = {};
    connectedDevices(settings).forEach((item) => { snapshot[item.id] = item.lastSeen || ""; });
    try {
      await downloadConnectorSetup();
      setSetupSnapshot(snapshot);
      setSetupHint(true);
    } catch (reason) {
      setSetupError(reason.message || "The setup file could not be downloaded.");
    }
  };
  const nav = useMemo(() => [["jobs", "Jobs", FileText], ["recipes", "Recipes", Layers], ["settings", "Shop settings", Settings2]], []);
  if (!auth) return <div className="auth-shell" data-testid="loading-screen"><p>{error || "Opening your shop…"}</p></div>;
  if (!auth.user) {
    if (location.pathname !== "/login") return <Navigate to="/login" replace />;
    return <Auth auth={auth} onSignedIn={(user) => { authEpoch.current += 1; setAuth({ user, needsSetup: false }); navigate("/jobs"); }} />;
  }
  const signOut = async () => {
    await api("auth/logout", { method: "POST", body: "{}" });
    setAuth({ user: null, needsSetup: false });
    navigate("/login");
  };
  if (auth.user.role === "superadmin") {
    return <PlatformScreen onSignedOut={signOut} />;
  }
  if (!shopOpen) {
    return <div className="auth-shell" data-testid="suspended-screen">
      <main className="auth-form">
        <h2>This shop is suspended</h2>
        <p className="muted">Sign-in is blocked until a platform administrator turns the shop back on. Job files stay in the shop.</p>
        <button className="primary wide" data-testid="suspended-sign-out-button" onClick={signOut}>Sign out</button>
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
    <ConnectComputerBanner settings={settings} user={auth.user} pending={setupHint} hint={setupHint} onConnect={connectThisComputer} onOther={() => navigate("/settings#other-ways")} />
    {setupError && <div className="error-bar" data-testid="connect-setup-error">{setupError}</div>}
    {error && <div className="error-bar" data-testid="global-error"><AlertTriangle />{error}<button className="icon-button" onClick={() => setError("")} data-testid="dismiss-error-button"><X /></button></div>}
    {view === "jobs" && !job && <main className="jobs-page" data-testid="jobs-page">
      <div className="page-heading"><div><span className="eyebrow">YOUR PRODUCTION WORKSPACE</span><h1>Jobs</h1><p className="muted">Needs you, waiting, ready to print, and done. One next action at a time.</p></div><button className="primary" onClick={() => setNewJob(true)} data-testid="start-job-button"><Plus />Start a job</button></div>
      <div className="queue-tabs" data-testid="job-queue">{QUEUE_GROUPS.map(([id, label]) => <button type="button" key={id} className={queue.group === id ? "selected" : ""} data-testid={`queue-${id}`} onClick={() => load(id)}>{label} <span>{queue.counts?.[id] || 0}</span></button>)}</div>
      {QUEUE_GROUPS.every(([id]) => !(queue.counts?.[id]))
        ? <div className="empty-state" data-testid="jobs-empty-state"><FileText size={36} /><h2>Your first great print starts here.</h2><p>Create a job from a product preset or custom specs, upload artwork, and follow a clear path to an approved proof.</p><button className="primary" onClick={() => setNewJob(true)} data-testid="empty-start-job-button"><Plus />Start a job</button></div>
        : <div className="job-list" data-testid="job-list">{queue.jobs.map((item) => {
          const task = item.tasks?.find((entry) => entry.status !== "Completed");
          return <button className="job-card" key={item.id} onClick={() => navigate(`/jobs/${item.id}`)} data-testid={`job-card-${item.id}`}><div className="product-icon"><FileText /></div><div className="job-card-main"><strong>{item.customer}</strong><p>{productLine(item)}</p></div><div className="job-card-status"><Badge status={displayStatus(item, task)} /></div></button>;
        })}{!queue.jobs.length && <p className="notice" data-testid="queue-empty">Nothing in this group.</p>}{queue.nextCursor && <button type="button" className="button" data-testid="queue-more" onClick={() => load(queue.group, queue.nextCursor, true)}>More jobs</button>}</div>}
      <footer className="page-foot"><ShieldCheck size={15} />Approvals stay tied to the exact production file.</footer>
    </main>}
    {view === "jobs" && job && <JobView job={job} settings={settings} user={auth.user} reload={reloadJob} back={() => navigate("/jobs")} openSettings={() => navigate("/settings")} onArchived={async () => { setJob(null); navigate("/jobs"); await load(); }} />}
    {view === "recipes" && <Recipes recipes={recipes} catalog={catalog} reload={load} user={auth.user} />}
    {view === "settings" && settings && <Settings settings={settings} user={auth.user} reload={load} />}
    {newJob && <JobModal catalog={catalog} settings={settings} close={() => setNewJob(false)} created={(created, defaults) => { setSettings((current) => ({ ...(current || {}), jobDefaults: defaults })); setJob(created); setNewJob(false); navigate(`/jobs/${created.id}`); load(); }} />}
  </div>;
}

function ProofApproval() {
  const { token } = useParams();
  const [proof, setProof] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(`${API}/proofs/${token}`, { credentials: "include" })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || "This approval link is invalid or expired.");
        setProof(data);
      })
      .catch((reason) => setError(reason.message));
  }, [token]);
  const approve = async () => {
    setError("");
    const response = await fetch(`${API}/proofs/${token}/approve`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      setError(data.error || "This approval link is invalid or expired.");
      return;
    }
    setMessage("Approved. Nothing was printed.");
    setProof((current) => ({ ...(current || {}), status: "approved" }));
  };
  return <main className="auth-shell" data-testid="proof-approval-page">
    <section className="auth-form">
      <h2>Approve this proof</h2>
      {error && <p className="notice warning" data-testid="proof-approval-error">{error}</p>}
      {proof && <p data-testid="proof-approval-summary">{proof.customer} · {proof.product}</p>}
      {message && <p className="notice" data-testid="proof-approval-done">{message}</p>}
      {proof?.status !== "approved" && <button className="primary" data-testid="proof-approve-button" onClick={approve}>Approve</button>}
      <p className="muted">Approving does not print the job.</p>
    </section>
  </main>;
}

function App() {
  return <BrowserRouter>
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/proof/:token" element={<ProofApproval />} />
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