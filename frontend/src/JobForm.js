import { useMemo, useState } from "react";
import { ShieldCheck, X } from "lucide-react";
import { api } from "@/api";

const LOCAL_KEY = "myraana.jobDefaults";
const FOLDS = [
  ["none", "No fold"],
  ["half", "Half fold"],
  ["tri", "Tri-fold"],
  ["z", "Z-fold"],
  ["gate", "Gate fold"],
  ["accordion", "Accordion fold"],
];

const FALLBACK = [
  {
    id: "business-card", name: "Business card", category: "Business Cards", kind: "product",
    sizes: [{ id: "3.5x2-in", label: "3.5 × 2 in", width: 3.5, height: 2, unit: "in" }],
    stocks: ["14pt matte", "16pt"], finishes: ["Matte", "Gloss", "Soft touch", "Uncoated"],
    folds: [], shapes: [], binding: [], hardware: [], priority: true,
  },
  {
    id: "flyer", name: "Flyer", category: "Marketing & Business", kind: "product",
    sizes: [
      { id: "4x6-in", label: "4 × 6 in", width: 4, height: 6, unit: "in" },
      { id: "5x7-in", label: "5 × 7 in", width: 5, height: 7, unit: "in" },
      { id: "5.5x8.5-in", label: "5.5 × 8.5 in", width: 5.5, height: 8.5, unit: "in" },
      { id: "8.5x11-in", label: "US Letter 8.5 × 11 in", width: 8.5, height: 11, unit: "in" },
    ],
    stocks: ["100lb Gloss Text", "28lb Smooth Text"], finishes: ["Gloss"],
    folds: ["half", "tri", "z", "gate", "accordion"], shapes: [], binding: [], hardware: [], priority: true,
  },
  {
    id: "custom", name: "Custom product", category: "Custom", kind: "product",
    sizes: [], stocks: [], finishes: [],
    folds: ["half", "tri", "z", "gate", "accordion"], shapes: [], binding: [], hardware: [], priority: true,
  },
];

function readLocal() {
  try {
    return JSON.parse(localStorage.getItem(LOCAL_KEY) || "null");
  } catch {
    return null;
  }
}

function groups(presets) {
  const featured = ["business-card", "flyer", "custom"]
    .map((id) => presets.find((item) => item.id === id))
    .filter(Boolean);
  const rest = presets.filter((item) => !featured.includes(item) && item.kind !== "service");
  const services = presets.filter((item) => item.kind === "service");
  const byCategory = new Map();
  rest.forEach((item) => {
    const key = item.category || "Other";
    byCategory.set(key, [...(byCategory.get(key) || []), item]);
  });
  return { featured, byCategory, services };
}

export function JobModal({ catalog, settings, close, created }) {
  const presets = catalog?.presets?.length ? catalog.presets : FALLBACK;
  const saved = useMemo(() => ({ ...(readLocal() || {}), ...(settings?.jobDefaults || {}) }), [settings]);
  const rules = settings?.artworkRules || {};
  const starting = presets.find((item) => item.id === (saved.product || "business-card")) || presets[0];
  const startingSize = saved.sizeId === "custom"
    ? null
    : ((starting?.sizes || []).find((item) => item.id === saved.sizeId) || starting?.sizes?.[0]);
  const [productId, setProductId] = useState(starting?.id || "custom");
  const [sizeId, setSizeId] = useState(saved.sizeId || startingSize?.id || "custom");
  const [width, setWidth] = useState(saved.width ?? startingSize?.width ?? "");
  const [height, setHeight] = useState(saved.height ?? startingSize?.height ?? "");
  const [unit, setUnit] = useState(saved.unit || startingSize?.unit || "in");
  const [quantity, setQuantity] = useState(saved.quantity ?? 500);
  const [sides, setSides] = useState(String(saved.sides ?? 2));
  const [stock, setStock] = useState(saved.stock || starting?.stocks?.[0] || "14pt matte");
  const [finish, setFinish] = useState(saved.finish || starting?.finishes?.[0] || "Matte");
  const [bleed, setBleed] = useState(saved.bleed ?? rules.bleedInches ?? 0.125);
  const [safe, setSafe] = useState(saved.safe ?? rules.safeInches ?? 0.25);
  const [fold, setFold] = useState(saved.options?.fold || "none");
  const [shape, setShape] = useState(saved.options?.shape || "");
  const [dieCut, setDieCut] = useState(Boolean(saved.options?.dieCut));
  const [grommets, setGrommets] = useState(saved.options?.grommets ?? 0);
  const [binding, setBinding] = useState(saved.options?.binding || "");
  const [hardware, setHardware] = useState(saved.options?.hardware || "");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const preset = presets.find((item) => item.id === productId) || starting;
  const { featured, byCategory, services } = groups(presets);
  const stockOptions = [...new Set([...(settings?.stocks || []), ...(preset?.stocks || []), ...(catalog?.vocabulary?.stocks || [])])];
  const finishOptions = [...new Set([...(preset?.finishes || []), ...(catalog?.vocabulary?.finishes || []), "Matte", "Gloss", "Soft touch", "Uncoated"])];
  const shapeOptions = [...new Set([...(preset?.shapes || []), ...(catalog?.vocabulary?.shapes || [])])];
  const bindingOptions = [...new Set([...(preset?.binding || []), ...(catalog?.vocabulary?.binding || [])])];
  const hardwareOptions = [...new Set([...(preset?.hardware || []), ...(catalog?.vocabulary?.hardware || [])])];

  const chooseProduct = (id) => {
    const next = presets.find((item) => item.id === id);
    setProductId(id);
    const size = next?.sizes?.[0];
    setSizeId(size?.id || "custom");
    if (size) {
      setWidth(size.width);
      setHeight(size.height);
      setUnit(size.unit || "in");
    }
    if (next?.stocks?.length) setStock(next.stocks[0]);
    if (next?.finishes?.length) setFinish(next.finishes[0]);
    setFold("none");
  };

  const chooseSize = (id) => {
    setSizeId(id);
    const size = (preset?.sizes || []).find((item) => item.id === id);
    if (size) {
      setWidth(size.width);
      setHeight(size.height);
      setUnit(size.unit || "in");
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!confirmed) {
      setError("Confirm the order details before creating the job.");
      return;
    }
    const payload = {
      customer: event.currentTarget.customer.value,
      due: event.currentTarget.due.value,
      product: productId,
      sizeId,
      width: width === "" ? undefined : Number(width),
      height: height === "" ? undefined : Number(height),
      unit,
      bleed: bleed === "" ? undefined : Number(bleed),
      safe: safe === "" ? undefined : Number(safe),
      quantity: Number(quantity),
      sides: Number(sides),
      stock,
      finish,
      confirmed: true,
      options: {
        fold,
        shape: shape || "rectangle",
        dieCut,
        grommets: Number(grommets || 0),
        binding,
        hardware,
      },
    };
    setBusy(true);
    setError("");
    try {
      const job = await api("jobs", { method: "POST", body: JSON.stringify(payload) });
      const defaults = {
        product: payload.product,
        sizeId: payload.sizeId,
        width: payload.width,
        height: payload.height,
        unit: payload.unit,
        bleed: payload.bleed,
        safe: payload.safe,
        quantity: payload.quantity,
        sides: payload.sides,
        stock: payload.stock,
        finish: payload.finish,
        options: payload.options,
      };
      localStorage.setItem(LOCAL_KEY, JSON.stringify(defaults));
      created(job, defaults);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  return <div className="modal-backdrop" data-testid="new-job-modal">
    <section className="modal job-modal" role="dialog" aria-modal="true" aria-labelledby="new-job-title">
      <div className="section-heading">
        <div><span className="eyebrow">NEW JOB</span><h2 id="new-job-title">Start a job</h2></div>
        <button className="icon-button" onClick={close} data-testid="new-job-close-button"><X /></button>
      </div>
      <p className="muted">A preset fills the usual specs. Anything you type replaces it. Services cannot become print jobs.</p>
      {error && <p className="notice warning" data-testid="new-job-error">{error}</p>}
      <form onSubmit={submit} data-testid="new-job-form">
        <label>Customer or company<input name="customer" required maxLength="180" data-testid="job-customer-input" /></label>
        <label>Product
          <select value={productId} onChange={(event) => chooseProduct(event.target.value)} data-testid="job-product-select">
            <optgroup label="Featured">
              {featured.map((item) => <option key={item.id} value={item.id}>{item.name}{item.tested ? " · tested" : ""}</option>)}
            </optgroup>
            {[...byCategory.entries()].map(([category, items]) => <optgroup key={category} label={category}>
              {items.map((item) => <option key={item.id} value={item.id}>{item.name}{item.pipeline === "custom" ? " · custom specs" : ""}</option>)}
            </optgroup>)}
            {services.length > 0 && <optgroup label="Services, not print jobs">
              {services.map((item) => <option key={item.id} value={item.id} disabled>{item.name}</option>)}
            </optgroup>}
          </select>
        </label>
        {preset?.summary && <p className="tiny">{preset.summary}</p>}
        <div className="form-grid">
          <label>Preset size
            <select value={sizeId} onChange={(event) => chooseSize(event.target.value)} data-testid="job-size-select">
              <option value="custom">Custom size</option>
              {(preset?.sizes || []).map((size) => <option key={size.id} value={size.id}>{size.label}</option>)}
            </select>
          </label>
          <label>Unit
            <select value={unit} onChange={(event) => { setUnit(event.target.value); setSizeId("custom"); }} data-testid="job-unit-select">
              <option value="in">in</option>
              <option value="mm">mm</option>
              <option value="cm">cm</option>
              <option value="ft">ft</option>
            </select>
          </label>
          <label>Finished width<input value={width} onChange={(event) => { setWidth(event.target.value); setSizeId("custom"); }} inputMode="decimal" required data-testid="job-width-input" /></label>
          <label>Finished height<input value={height} onChange={(event) => { setHeight(event.target.value); setSizeId("custom"); }} inputMode="decimal" required data-testid="job-height-input" /></label>
          <label>Bleed (inches)<input value={bleed} onChange={(event) => setBleed(event.target.value)} inputMode="decimal" data-testid="job-bleed-input" /></label>
          <label>Safe zone (inches)<input value={safe} onChange={(event) => setSafe(event.target.value)} inputMode="decimal" data-testid="job-safe-input" /></label>
          <label>Quantity<input value={quantity} onChange={(event) => setQuantity(event.target.value)} type="number" min="1" max="1000000" required data-testid="job-quantity-input" /></label>
          <label>Sides
            <select value={sides} onChange={(event) => setSides(event.target.value)} data-testid="job-sides-select">
              <option value="2">Front and back</option>
              <option value="1">Front only</option>
            </select>
          </label>
          <label>Stock
            <input value={stock} onChange={(event) => setStock(event.target.value)} list="stock-options" required maxLength="120" data-testid="job-stock-select" />
            <datalist id="stock-options">{stockOptions.map((item) => <option key={item} value={item} />)}</datalist>
          </label>
          <label>Finish
            <input value={finish} onChange={(event) => setFinish(event.target.value)} list="finish-options" required maxLength="120" data-testid="job-finish-select" />
            <datalist id="finish-options">{finishOptions.map((item) => <option key={item} value={item} />)}</datalist>
          </label>
          <label>Fold
            <select value={fold} onChange={(event) => setFold(event.target.value)} data-testid="job-fold-select">
              {FOLDS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <label>Due date<input name="due" type="date" required aria-label="Due date, YYYY-MM-DD" data-testid="job-due-input" /></label>
          <label>Shape
            <input value={shape} onChange={(event) => setShape(event.target.value)} list="shape-options" maxLength="140" placeholder="rectangle" data-testid="job-shape-input" />
            <datalist id="shape-options">{shapeOptions.map((item) => <option key={item} value={item} />)}</datalist>
          </label>
          <label>Grommets<input value={grommets} onChange={(event) => setGrommets(event.target.value)} type="number" min="0" max="100" data-testid="job-grommets-input" /></label>
          <label>Binding
            <input value={binding} onChange={(event) => setBinding(event.target.value)} list="binding-options" maxLength="140" data-testid="job-binding-input" />
            <datalist id="binding-options">{bindingOptions.map((item) => <option key={item} value={item} />)}</datalist>
          </label>
          <label>Hardware
            <input value={hardware} onChange={(event) => setHardware(event.target.value)} list="hardware-options" maxLength="140" data-testid="job-hardware-input" />
            <datalist id="hardware-options">{hardwareOptions.map((item) => <option key={item} value={item} />)}</datalist>
          </label>
        </div>
        <label className="check-label">
          <input type="checkbox" checked={dieCut} onChange={(event) => setDieCut(event.target.checked)} data-testid="job-diecut-checkbox" />
          Die-cut as specified
        </label>
        {preset?.customSize && <p className="tiny">Catalog size hint: {preset.customSize.width_min}–{preset.customSize.width_max} × {preset.customSize.height_min}–{preset.customSize.height_max} {preset.customSize.unit}. The job still accepts another size inside the shop limit of 150 inches.</p>}
        <label className="check-label">
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} required data-testid="job-confirm-checkbox" />
          I confirm these order details.
        </label>
        <div className="modal-footer">
          <span><ShieldCheck size={14} />The shop’s artwork rules travel with this job</span>
          <button className="primary" disabled={busy} data-testid="create-job-button">{busy ? "Saving…" : "Create job"}</button>
        </div>
      </form>
    </section>
  </div>;
}
