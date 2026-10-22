import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API, api } from "@/api";
import "@/site/site.css";

function SiteHeader({ signedIn }) {
  return <header className="site-header">
    <Link to="/" className="site-brand" data-testid="site-brand">
      <img src="/myraana-mark.svg" alt="" />
      <span><strong>Myraana</strong><small>PRODUCTION STUDIO</small></span>
    </Link>
    <nav className="site-nav" aria-label="Public">
      <Link to="/signup">Early access</Link>
      <Link to="/contact">Contact</Link>
      {signedIn
        ? <Link to="/jobs" className="site-signin" data-testid="open-studio-link">Open studio</Link>
        : <Link to="/login" className="site-signin" data-testid="sign-in-link">Sign in</Link>}
    </nav>
  </header>;
}

function SiteFooter() {
  return <footer className="site-footer">
    <span>Myraana · Print production studio</span>
    <nav aria-label="Legal">
      <Link to="/privacy">Privacy</Link>
      <Link to="/terms">Terms</Link>
      <Link to="/contact">Contact</Link>
    </nav>
  </footer>;
}

function useSignedIn() {
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => {
    fetch(`${API}/auth`, { credentials: "include" })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => setSignedIn(Boolean(data?.user)))
      .catch(() => setSignedIn(false));
  }, []);
  return signedIn;
}

function LeadForm({ intentDefault }) {
  const [intent, setIntent] = useState(intentDefault || "early-access");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api("public/leads", {
        method: "POST",
        body: JSON.stringify({ ...form, intent }),
      });
      event.currentTarget.reset();
      setMessage(intent === "demo"
        ? "Request saved. We will use this email to arrange a demo."
        : "Request saved. We will reply to this email about early access.");
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };
  return <form className="site-card" onSubmit={submit} data-testid="lead-form">
    <p className="site-kicker">EARLY ACCESS</p>
    <h2 style={{ fontFamily: "Fraunces, Georgia, serif", fontSize: 32, margin: "8px 0 8px" }}>Tell us about the shop.</h2>
    <p>Myraana stores the request. It does not create a login or a second workspace.</p>
    {error && <p className="site-note" role="alert" data-testid="lead-error">{error}</p>}
    {message && <p className="site-ok" data-testid="lead-success">{message}</p>}
    <div className="site-row">
      <label>Shop name<input name="shop" required minLength="2" maxLength="120" data-testid="lead-shop-input" /></label>
      <label>Email<input name="email" type="email" required maxLength="200" data-testid="lead-email-input" /></label>
    </div>
    <div className="site-row">
      <label>Your name<input name="name" maxLength="80" data-testid="lead-name-input" /></label>
      <label>City<input name="city" maxLength="80" data-testid="lead-city-input" /></label>
    </div>
    <label>What should we know?<textarea name="message" rows="4" maxLength="2000" data-testid="lead-message-input" /></label>
    <div className="site-form-actions">
      <button className="site-button solid" type="submit" disabled={busy} data-testid="lead-submit-button" onClick={() => setIntent("early-access")}>
        {busy && intent === "early-access" ? "Saving…" : "Request early access"}
      </button>
      <button className="site-button ghost" type="submit" disabled={busy} data-testid="demo-submit-button" onClick={() => setIntent("demo")}>
        {busy && intent === "demo" ? "Saving…" : "Book a demo"}
      </button>
    </div>
  </form>;
}

export function Home() {
  const signedIn = useSignedIn();
  return <div className="site" data-testid="marketing-home">
    <SiteHeader signedIn={signedIn} />
    <section className="site-hero">
      <p className="site-kicker">PRINT PRODUCTION STUDIO</p>
      <h1>From artwork to an approved proof, then to the press.</h1>
      <p className="lede">Myraana runs the path a print shop already knows: the file, the proof, and the press. Built inside Print2Go, a working print shop in London, Ontario.</p>
      <div className="site-actions">
        <a className="site-button solid" href="#early-access">Request early access</a>
        <a className="site-button ghost" href="#early-access" data-testid="book-demo-link">Book a demo</a>
      </div>
    </section>
    <section className="site-steps" aria-label="How it works">
      <article className="site-step">
        <span>1</span>
        <h2>Specify the job</h2>
        <p>Size, stock, finish, sides, and quantity. A catalog preset fills the usual choice. A custom size is still a normal job.</p>
      </article>
      <article className="site-step">
        <span>2</span>
        <h2>Check the artwork</h2>
        <p>Bleed, resolution, and colour are checked against the shop’s rules. A person approves the proof that matches the production file.</p>
      </article>
      <article className="site-step">
        <span>3</span>
        <h2>Choose the route</h2>
        <p>Send the approved PDF to a verified press, or stop on a proof-only route when the shop is not ready to print.</p>
      </article>
    </section>
    <section className="site-founder">
      <div className="site-founder-inner">
        <div>
          <p className="site-kicker">THE SHOP</p>
          <h2>Built inside Print2Go, a working print shop in London, Ontario.</h2>
          <p>Faiyaz runs the Print2Go shop at 201 Queens Ave and built Myraana on the jobs that shop prints. print2go.com is a shared site for the Ontario franchise. Myraana is the studio for this shop, and the product other shops can run for themselves.</p>
        </div>
        <div className="site-panel">
          <h3>What stays with the shop</h3>
          <p>Artwork rules, stocks, and verified printers are shop settings. Business cards and flyers are ready presets. The rest of a catalog can prefill a job without becoming a hard limit.</p>
        </div>
      </div>
    </section>
    <section className="site-form" id="early-access">
      <LeadForm intentDefault="early-access" />
    </section>
    <SiteFooter />
  </div>;
}

export function Signup() {
  const signedIn = useSignedIn();
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api("public/signup", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))),
      });
      event.currentTarget.reset();
      setMessage(result.message);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };
  return <div className="site" data-testid="signup-page">
    <SiteHeader signedIn={signedIn} />
    <main className="site-form">
      <form className="site-card" onSubmit={submit} data-testid="signup-form">
        <p className="site-kicker">SHOP SIGNUP</p>
        <h1>Request a shop workspace.</h1>
        <p>Myraana saves this request and does not open a separate shop. Shops are not isolated from each other yet, so a new login would see the same jobs. There is no password on this form.</p>
        {error && <p className="site-note" role="alert" data-testid="signup-error">{error}</p>}
        {message && <p className="site-ok" data-testid="signup-success">{message}</p>}
        <label>Shop name<input name="shop" required minLength="2" maxLength="120" data-testid="signup-shop-input" /></label>
        <div className="site-row">
          <label>Your name<input name="name" maxLength="80" data-testid="signup-name-input" /></label>
          <label>Email<input name="email" type="email" required data-testid="signup-email-input" /></label>
        </div>
        <label>City<input name="city" maxLength="80" data-testid="signup-city-input" /></label>
        <label>What do you print?<textarea name="message" rows="4" maxLength="2000" data-testid="signup-message-input" /></label>
        <button className="site-button solid" disabled={busy} data-testid="signup-submit-button">{busy ? "Saving…" : "Request a shop workspace"}</button>
      </form>
    </main>
    <SiteFooter />
  </div>;
}

export function Contact() {
  const signedIn = useSignedIn();
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api("public/leads", {
        method: "POST",
        body: JSON.stringify({ ...Object.fromEntries(new FormData(event.currentTarget)), intent: "contact" }),
      });
      event.currentTarget.reset();
      setMessage("Message saved. We will reply to the email you entered.");
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };
  return <div className="site" data-testid="contact-page">
    <SiteHeader signedIn={signedIn} />
    <main className="site-form">
      <form className="site-card" onSubmit={submit} data-testid="contact-form">
        <p className="site-kicker">CONTACT</p>
        <h1>Write to Myraana.</h1>
        <p>This form stores a message with the other shop requests. Myraana does not publish a separate support address yet. Print2Go London’s own store details stay on print2go.com.</p>
        {error && <p className="site-note" role="alert">{error}</p>}
        {message && <p className="site-ok" data-testid="contact-success">{message}</p>}
        <div className="site-row">
          <label>Your name<input name="name" maxLength="80" data-testid="contact-name-input" /></label>
          <label>Email<input name="email" type="email" required data-testid="contact-email-input" /></label>
        </div>
        <label>Shop<input name="shop" maxLength="120" data-testid="contact-shop-input" /></label>
        <label>Message<textarea name="message" required rows="5" maxLength="2000" data-testid="contact-message-input" /></label>
        <button className="site-button solid" disabled={busy} data-testid="contact-submit-button">{busy ? "Saving…" : "Send message"}</button>
      </form>
    </main>
    <SiteFooter />
  </div>;
}

const LEGAL = {
  privacy: {
    title: "Privacy",
    body: [
      "This draft describes how the Myraana studio at myraana.com handles information. It is not a finished privacy policy. A lawyer should replace it before the product is offered to other shops.",
      "Shop staff accounts store a name, an email address, a password hash, and a role. Jobs store the customer name, product specs, due date, artwork files, proof approvals, and the production record. Early-access, demo, contact, and signup forms store the shop name, email, city, and message you submit. Those forms do not ask for or keep a password.",
      "Artwork files stay in the shop database so the proof can be tied to the file that was approved. Session cookies keep you signed in. The studio does not sell this information. Billing, if a shop turns it on later, would be handled by Stripe and is off unless the operator configures it.",
      "Public marketing pages are separate from the Print2Go shop workspace. A signup request does not create an account.",
    ],
  },
  terms: {
    title: "Terms",
    body: [
      "This draft is a placeholder for the terms of using Myraana. It is not a contract. The founder needs to replace it with reviewed terms before other shops rely on it.",
      "Myraana is a production studio for print shops. The current workspace belongs to the Print2Go shop that operates it. Self-serve creation of a separate shop is not available. Approvals, printer verification, and the decision to print stay with people at the shop.",
      "Catalog presets prefill common products. They do not promise that every print2go.com product is imposed, priced, or produced automatically. Output is a print-ready PDF for the shop to review.",
      "The software is provided for the shop’s own production work. Do not upload artwork you do not have the right to print.",
    ],
  },
};

export function Legal({ kind }) {
  const signedIn = useSignedIn();
  const page = LEGAL[kind];
  return <div className="site" data-testid={`${kind}-page`}>
    <SiteHeader signedIn={signedIn} />
    <main className="site-narrow">
      <article className="site-card site-copy">
        <p className="site-draft">DRAFT</p>
        <h1>{page.title}</h1>
        {page.body.map((paragraph) => <p key={paragraph.slice(0, 24)}>{paragraph}</p>)}
      </article>
    </main>
    <SiteFooter />
  </div>;
}

export function NotFound() {
  const signedIn = useSignedIn();
  return <div className="site" data-testid="not-found-page">
    <SiteHeader signedIn={signedIn} />
    <main className="site-narrow">
      <article className="site-card">
        <p className="site-kicker">404</p>
        <h1>That page is not on Myraana.</h1>
        <p>The address does not match a public page or a studio route.</p>
        <div className="site-actions">
          <Link className="site-button solid" to="/">Back to the homepage</Link>
          <Link className="site-button ghost" to="/login">Sign in</Link>
        </div>
      </article>
    </main>
    <SiteFooter />
  </div>;
}
