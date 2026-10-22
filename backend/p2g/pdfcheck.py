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
    "This check looks at page size, fonts, placed images, and colour. "
    "It does not certify PDF/X, transparency, or overprint. "
    "Look at the proof before you approve."
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
    max_pages = int(r.get("maxPages") or 2)
    if n != sides:
        errors.append(
            f"This job needs {sides} page(s), and this file has {n}. "
            "Export one PDF with the front first, then the back if the job is double-sided, and upload it again."
        )
    if n > max_pages:
        errors.append(
            f"This file has {n} pages. This job allows {max_pages}. "
            "Export a PDF with only the front and, if needed, the back."
        )
    try:
        if reader.get_fields():
            errors.append(
                "This PDF still has form fields. Flatten them in the design app, then upload the PDF again."
            )
    except Exception:
        warnings.append("The form fields could not be read. Open the proof and confirm the page looks finished.")
    fw, fh = (r["width"] + 2 * r["bleed"]) * PT, (r["height"] + 2 * r["bleed"]) * PT
    tw, th = r["width"] * PT, r["height"] * PT
    bleed = "correct"
    for i in range(min(n, 2)):
        p, mp = reader.pages[i], doc[i]
        mb = p.mediabox
        w, h = float(mb.width), float(mb.height)
        full, trim = close(w, fw) and close(h, fh), close(w, tw) and close(h, th)
        if not full and not trim:
            errors.append(
                f"Page {i+1} is {w/PT:.3f} × {h/PT:.3f} inches, which does not match the finished size "
                f"of {r['width']:.3f} × {r['height']:.3f} inches plus {r['bleed']:.3f} inch bleed. "
                "Export the PDF at that size and upload it again. Myraana will not stretch it."
            )
            bleed = "unsuitable"
        elif trim and bleed != "unsuitable":
            bleed = "missing"
        if int(p.get("/Rotate", 0) or 0) % 360 != 0:
            errors.append(
                f"Page {i+1} is rotated. Export the PDF with rotation set to zero, then upload it again."
            )
        annots = p.get("/Annots")
        if annots is not None and len(annots.get_object()) > 0:
            errors.append(
                f"Page {i+1} still has comments or links. Flatten them in the design app, then upload the PDF again."
            )
        boxes = {name: _box(p, name) for name in ("MediaBox", "CropBox", "BleedBox", "TrimBox", "ArtBox")}
        cb = boxes["CropBox"]["box"]
        if boxes["CropBox"]["explicit"] and [round(v, 1) for v in cb] != [round(float(v), 1) for v in mb]:
            warnings.append(
                f"Page {i+1} has a crop box that does not match the page. "
                "The prepared file resets the boxes to this job. Check the proof."
            )
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
            errors.append(
                f"Page {i+1}: {len(unsafe)} text span(s) sit inside the protected safe margin "
                f"({r['safe']:.3f} inches inside the trim). "
                "Move essential text inward and upload a revised PDF."
            )
        fonts = []
        for xref, ext, ftype, basefont, name, *_ in mp.get_fonts(full=True):
            base = (basefont or "").split("+")[-1]
            embedded = ext != "n/a" or ftype == "Type3"
            used = base in used_fonts
            fonts.append({"name": basefont, "type": ftype, "embedded": embedded, "used": used})
            if used and not embedded:
                errors.append(
                    f"Page {i+1}: font {base} is not embedded. "
                    "Embed the font or convert the text to outlines, then upload the PDF again."
                )
        images = []
        for info in mp.get_image_info():
            x0, y0, x1, y1 = info["bbox"]
            pw, ph = (x1 - x0) / PT, (y1 - y0) / PT
            if info.get("width") and info.get("height") and pw > 0 and ph > 0:
                dpi = min(info["width"] / pw, info["height"] / ph)
                cs = {1: "Gray", 3: "RGB", 4: "CMYK"}.get(info.get("colorspace"), str(info.get("colorspace")))
                images.append({"pixels": [info["width"], info["height"]], "placedInches": [round(pw, 3), round(ph, 3)], "dpi": round(dpi, 1), "colourSpace": cs})
                if dpi < float(r["minDpi"]) - 0.5:
                    errors.append(
                        f"Page {i+1}: an image measures {dpi:.0f} dpi at its placed size; "
                        f"minimum is {r['minDpi']} dpi. "
                        "Replace it with a higher-resolution image and upload the PDF again."
                    )
        forms = [x for x in mp.get_xobjects()]
        if forms:
            warnings.append(
                f"Page {i+1} has {len(forms)} grouped object(s). "
                "Text and images inside were checked. Open the proof and look at that artwork before you approve."
            )
        pages.append({
            "page": i + 1, "widthInches": round(w / PT, 4), "heightInches": round(h / PT, 4), "boxes": boxes,
            "rotation": int(p.get("/Rotate", 0) or 0), "fonts": fonts, "images": images, "unsafeText": unsafe,
            "colourOperators": _colours(p, reader),
        })
    doc.close()
    warnings.append(LIMITS)
    if bleed == "correct":
        warnings.append(
            "The page includes bleed. Myraana cannot prove the design reaches every bleed edge. "
            "Look at the proof and confirm the background extends past the trim."
        )
    colour = _colour_check(pages, r, errors, warnings)
    raster = r.get("rasterTextDpi")
    if raster and float(raster) > float(r["minDpi"]):
        warnings.append(
            f"Raster text and logos should be {int(float(raster))} dpi. "
            f"Photos below {int(r['minDpi'])} dpi are blocked. "
            "Myraana cannot tell a logo from a photo, so check logos on the proof."
        )
    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))
    actions = []
    for error in errors:
        if "page(s)" in error:
            actions.append("Export the front and back as one PDF with the required page count.")
        elif "does not match the finished size" in error or "does not match the recipe" in error:
            actions.append("Export at the exact finished size plus bleed. Myraana will not scale the artwork.")
        elif "safe margin" in error:
            actions.append("Move essential text and logos inward, then upload a revised PDF.")
        elif "not embedded" in error:
            actions.append("Embed fonts or convert approved text to outlines before export.")
        elif "annotations" in error or "comments or links" in error:
            actions.append("Flatten comments, links, and annotations before export.")
        elif "dpi at its placed size" in error:
            actions.append("Replace low-resolution images with artwork meeting the recipe minimum DPI at final print size.")
        elif "DeviceRGB" in error:
            actions.append("Export CMYK artwork, or change the shop RGB policy if RGB files should be accepted.")
    size_fail = any("does not match" in item for item in errors)
    dpi_fail = any("dpi at its placed size" in item for item in errors)
    artwork_checks = [
        {"name": "size", "status": "fail" if size_fail else "pass"},
        {"name": "bleed", "status": {"correct": "pass", "missing": "warn", "unsuitable": "fail"}.get(bleed, "warn")},
        {"name": "dpi", "status": "fail" if dpi_fail else "pass"},
        {"name": "colour", "status": colour["status"]},
    ]
    return {"pages": pages, "errors": errors, "warnings": warnings, "actions": list(dict.fromkeys(actions)), "bleed": bleed,
            "colourMode": colour, "artworkChecks": artwork_checks,
            "engine": "PyMuPDF (MuPDF) text/image tracing + pypdf structure inspection", "at": datetime.now(timezone.utc).isoformat()}


def _colour_check(pages, recipe, errors, warnings):
    found = sorted({
        colour
        for page in pages
        for colour in page.get("colourOperators") or []
        if colour != "unreadable content stream"
    })
    expected = str(recipe.get("colourMode") or "CMYK").upper()
    policy = recipe.get("rgbPolicy") or "warn"
    status = "pass"
    if not found:
        status = "unknown"
        warnings.append("No colour operators were found. Colour mode was not certified.")
    elif expected == "CMYK" and "DeviceRGB" in found:
        message = (
            "This file uses RGB colour (DeviceRGB). This shop prints CMYK. "
            "RGB uploads are not converted to CMYK here. "
        )
        if policy == "reject":
            errors.append(message + "Export the file as CMYK, or ask an admin to allow RGB with a warning.")
            status = "fail"
        else:
            warnings.append(message + "The file is accepted with a warning. Check the colours on the proof.")
            status = "warn"
    if recipe.get("allowSpotColours", True) and any("Separation" in item or "DeviceN" in item for item in found):
        warnings.append(
            "A Pantone or other spot colour is in this file. "
            "Confirm it separates the way you expect. Myraana does not convert it."
        )
    return {"expected": expected, "found": found, "status": status, "rgbPolicy": policy}


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
        "/Producer": "Myraana",
        "/Print2GoRecipe": f"{r['id']} v{r['version']}",
        "/MyraanaProduct": f"{r.get('product') or r['id']} v{r['version']}",
        "/MyraanaOutputDpi": str(int(r.get("outputDpi") or 300)),
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
            raise PdfError("That page is not in the file. Refresh the proof and try again.")
        page = doc[index]
        long_inches = max(float(page.rect.width), float(page.rect.height)) / PT
        if long_inches > 0:
            dpi = min(int(dpi), max(36, int(1400 / long_inches)))
        return page.get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()
