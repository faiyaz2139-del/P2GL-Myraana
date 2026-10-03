"""Measured PDF inspection, preparation and independent verification (PyMuPDF + pypdf)."""
import io
import hashlib
from datetime import datetime, timezone
import pymupdf
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject, NameObject, TextStringObject
from pypdf.generic import ContentStream

PT = 72.0
LIMITS = (
    "Font-embedding checks cover fonts referenced by page text. Image measurements cover placed raster images "
    "found by the renderer. Nested forms, masks, vector logos, transparency and overprint need visual review. "
    "Colour operators are reported as found; no colour conversion is applied and colour suitability is not "
    "certified. Text bounds come from the text extractor and are approximate. This is not a certified PDF/X preflight."
)


class PdfError(Exception):
    pass


def close(a, b):
    return abs(a - b) < 0.75


def _box(page, name):
    raw = page.get("/" + name)
    value = getattr(page, name.lower().replace("box", "box"))
    return {"explicit": raw is not None, "box": [round(float(v), 3) for v in value]}


def _colours(page, reader):
    found = set()
    try:
        contents = page.get_contents()
        if contents is None:
            return []
        ops = ContentStream(contents, reader).operations
    except Exception:
        return ["unreadable content stream"]
    for operands, op in ops:
        if op in (b"rg", b"RG"):
            found.add("DeviceRGB")
        elif op in (b"k", b"K"):
            found.add("DeviceCMYK")
        elif op in (b"g", b"G"):
            found.add("DeviceGray")
        elif op in (b"cs", b"CS") and operands:
            found.add(str(operands[0]))
    return sorted(found)


def _open(data):
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        count = len(reader.pages)
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:
        raise PdfError("The PDF could not be read. Export a fresh PDF and upload it again.") from e
    if reader.is_encrypted or doc.needs_pass:
        raise PdfError("The PDF is password-protected. Upload an unprotected PDF.")
    if count == 0 or doc.page_count != count:
        raise PdfError("The PDF page structure is damaged. Export a fresh PDF and upload it again.")
    return reader, doc


def inspect(data, r, sides):
    reader, doc = _open(data)
    errors, warnings, pages = [], [], []
    n = len(reader.pages)
    if n != sides:
        errors.append(f"Expected {sides} page(s), found {n}. Upload one PDF with the front, then the back.")
    if n > 2:
        errors.append("Business cards support at most two PDF pages.")
    try:
        if reader.get_fields():
            errors.append("Interactive form fields must be flattened by the artwork designer before upload.")
    except Exception:
        warnings.append("Form field structure could not be read; review the proof carefully.")
    fw, fh = (r["width"] + 2 * r["bleed"]) * PT, (r["height"] + 2 * r["bleed"]) * PT
    tw, th = r["width"] * PT, r["height"] * PT
    bleed = "correct"
    for i in range(min(n, 2)):
        p, mp = reader.pages[i], doc[i]
        mb = p.mediabox
        w, h = float(mb.width), float(mb.height)
        full, trim = close(w, fw) and close(h, fh), close(w, tw) and close(h, th)
        if not full and not trim:
            errors.append(f"Page {i+1}: {w/PT:.3f} × {h/PT:.3f} inches does not match the recipe. No stretching is allowed.")
            bleed = "unsuitable"
        elif trim and bleed != "unsuitable":
            bleed = "missing"
        if int(p.get("/Rotate", 0) or 0) % 360 != 0:
            errors.append(f"Page {i+1}: rotated page. Export an unrotated PDF.")
        annots = p.get("/Annots")
        if annots is not None and len(annots.get_object()) > 0:
            errors.append(f"Page {i+1}: annotations detected. Flatten comments, links and annotations before upload.")
        boxes = {name: _box(p, name) for name in ("MediaBox", "CropBox", "BleedBox", "TrimBox", "ArtBox")}
        cb = boxes["CropBox"]["box"]
        if boxes["CropBox"]["explicit"] and [round(v, 1) for v in cb] != [round(float(v), 1) for v in mb]:
            warnings.append(f"Page {i+1}: CropBox differs from MediaBox; the prepared file resets boxes to the recipe.")
        offset, safe = (r["bleed"] * PT if full else 0.0), r["safe"] * PT
        unsafe, used_fonts = [], set()
        for block in mp.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                angled = abs(line["dir"][1]) > 0.01
                for span in line["spans"]:
                    if not span["text"].strip():
                        continue
                    used_fonts.add(span["font"].split("+")[-1])
                    if angled:
                        warnings.append(f"Page {i+1}: angled text needs visual safe-area review.")
                        continue
                    x0, y0, x1, y1 = span["bbox"]
                    if x0 < offset + safe or y0 < offset + safe or x1 > w - offset - safe or y1 > h - offset - safe:
                        unsafe.append({"text": span["text"][:40], "bounds": [round(v, 2) for v in span["bbox"]]})
        if unsafe:
            errors.append(f"Page {i+1}: {len(unsafe)} text span(s) detected inside the protected safe margin. Move essential text inward and upload a revised PDF.")
        fonts = []
        for xref, ext, ftype, basefont, name, *_ in mp.get_fonts(full=True):
            base = (basefont or "").split("+")[-1]
            embedded = ext != "n/a" or ftype == "Type3"
            used = base in used_fonts
            fonts.append({"name": basefont, "type": ftype, "embedded": embedded, "used": used})
            if used and not embedded:
                errors.append(f"Page {i+1}: font {base} is not embedded. Embed fonts or outline text before uploading.")
        images = []
        for info in mp.get_image_info():
            x0, y0, x1, y1 = info["bbox"]
            pw, ph = (x1 - x0) / PT, (y1 - y0) / PT
            if info.get("width") and info.get("height") and pw > 0 and ph > 0:
                dpi = min(info["width"] / pw, info["height"] / ph)
                cs = {1: "Gray", 3: "RGB", 4: "CMYK"}.get(info.get("colorspace"), str(info.get("colorspace")))
                images.append({"pixels": [info["width"], info["height"]], "placedInches": [round(pw, 3), round(ph, 3)], "dpi": round(dpi, 1), "colourSpace": cs})
                if dpi < r["minDpi"]:
                    warnings.append(f"Page {i+1}: an image measures {dpi:.0f} dpi at its placed size; target is {r['minDpi']} dpi.")
        forms = [x for x in mp.get_xobjects()]
        if forms:
            warnings.append(f"Page {i+1}: {len(forms)} form XObject(s) (nested content). Text and images inside were traced, but nested artwork needs visual review.")
        pages.append({
            "page": i + 1, "widthInches": round(w / PT, 4), "heightInches": round(h / PT, 4), "boxes": boxes,
            "rotation": int(p.get("/Rotate", 0) or 0), "fonts": fonts, "images": images, "unsafeText": unsafe,
            "colourOperators": _colours(p, reader),
        })
    doc.close()
    warnings.append(LIMITS)
    if bleed == "correct":
        warnings.append("Page size includes bleed. This cannot prove the design extends to every bleed edge; confirm visually.")
    return {"pages": pages, "errors": list(dict.fromkeys(errors)), "warnings": list(dict.fromkeys(warnings)), "bleed": bleed,
            "engine": "PyMuPDF (MuPDF) text/image tracing + pypdf structure inspection", "at": datetime.now(timezone.utc).isoformat()}


def prepare(data, r, blank_border):
    reader, _ = _open(data)
    writer = PdfWriter(clone_from=reader)
    b, fw, fh = r["bleed"] * PT, (r["width"] + 2 * r["bleed"]) * PT, (r["height"] + 2 * r["bleed"]) * PT
    for page in writer.pages:
        mb = page.mediabox
        x0, y0 = float(mb.left), float(mb.bottom)
        if blank_border and close(float(mb.width), r["width"] * PT) and close(float(mb.height), r["height"] * PT):
            page.add_transformation(Transformation().translate(b - x0, b - y0))
            x0, y0 = 0.0, 0.0
        full = RectangleObject([x0, y0, x0 + fw, y0 + fh])
        page.mediabox = full
        page.cropbox = RectangleObject(list(full))
        page.bleedbox = RectangleObject(list(full))
        page.trimbox = RectangleObject([x0 + b, y0 + b, x0 + b + r["width"] * PT, y0 + b + r["height"] * PT])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def make_print_ready(data, r, job_id, generation):
    reader, _ = _open(data)
    writer = PdfWriter(clone_from=reader)
    writer.add_metadata({
        "/Title": f"PRINT_READY {job_id} g{generation}",
        "/Producer": "Print2Go Production Studio",
        "/Print2GoRecipe": f"{r['id']} v{r['version']}",
    })
    writer._info.get_object()[NameObject("/Print2GoStage")] = TextStringObject("PRINT_READY")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def verify(data, r, sides, expected_sha):
    report = inspect(data, r, sides)
    checks = []
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha:
        report["errors"].append("Reopened file checksum does not match the recorded PRINT_READY checksum.")
    checks.append(f"sha256 {actual}")
    reader, doc = _open(data)
    if len(reader.pages) != sides:
        report["errors"].append("Generated page count does not match the order sides.")
    checks.append(f"pages {len(reader.pages)}")
    b, fw, fh = r["bleed"] * PT, (r["width"] + 2 * r["bleed"]) * PT, (r["height"] + 2 * r["bleed"]) * PT
    for i, p in enumerate(reader.pages):
        mb, t, bl = p.mediabox, p.trimbox, p.bleedbox
        ok = (p.get("/TrimBox") is not None and p.get("/BleedBox") is not None
              and close(float(mb.width), fw) and close(float(mb.height), fh)
              and close(float(t.left) - float(mb.left), b) and close(float(t.bottom) - float(mb.bottom), b)
              and close(float(t.width), r["width"] * PT) and close(float(t.height), r["height"] * PT)
              and close(float(bl.width), fw) and close(float(bl.height), fh))
        if not ok:
            report["errors"].append("Generated page boxes do not match the pinned recipe.")
        try:
            doc[i].get_pixmap(dpi=36)
            checks.append(f"page {i+1} boxes {'ok' if ok else 'mismatch'}, renders")
        except Exception:
            report["errors"].append(f"Generated page {i+1} could not be rendered.")
    doc.close()
    report["errors"] = list(dict.fromkeys(report["errors"]))
    report["checks"] = checks
    report["pdfx"] = "Not certified PDF/X. Recipe size, boxes, page count, checksum and renderability verified."
    return report


def render_page(data, index, dpi=150):
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        if index < 0 or index >= doc.page_count:
            raise PdfError("Page not found.")
        return doc[index].get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()
