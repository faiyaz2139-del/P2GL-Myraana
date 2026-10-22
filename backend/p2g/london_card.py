"""Print2Go London business-card recipe: file to Fiery.

The shop chart is the source of truth. Portrait and landscape use the same
steps. The original file stays untouched. Fiery imports the PRINT_READY PDF.
"""
import copy
import io
import re
from datetime import datetime, timezone
from pathlib import Path

import pymupdf
from PIL import Image


WORKFLOW_NAME = "Business card workflow: file to Fiery"
PRESET_NAME = "London BC"
SEED_SLUGS = ("print2go", "print2go-london")
SAFE_IN = 0.125
BLEED_IN = 0.125
SIZE_TOLERANCE = 0.015
PT = 72.0

STOP_FILE = "The file isn't where you were told, or may be the wrong customer."
STOP_SIZE = "STOP: size error, artwork needs re-design. Never resize or stretch it."
STOP_STRETCH = "Fixing it would stretch the art or change customer info."
STOP_CUT = "Text, logo or QR code sits too close to the cut."
STOP_BLEED = "STOP: human review. The bleed is not real."
STOP_PRESET = "London BC is missing or lays the sheet out wrong."
STOP_HOLD = "The job won't save to HOLD."
STOP_STOCK = "The stock is unknown or not in Properties."
STOP_ORIGINAL = "Fiery must import the PRINT_READY file, never the original."

STOPS = (
    STOP_FILE,
    STOP_SIZE,
    STOP_STRETCH,
    STOP_CUT,
    STOP_PRESET,
    STOP_HOLD,
    STOP_STOCK,
)

KIND_LABELS = {
    "ask": "Ask the operator",
    "photoshop": "Photoshop/auto-fix",
    "fiery": "Fiery",
    "decision": "Decision",
    "stop": "Stop for review",
    "start": "Start / finish",
}

_WEIGHT = re.compile(
    r"^(\d+(?:\.\d+)?)\s*-?\s*pt(?:\s+paper(?:\s+weight)?)?$",
    re.IGNORECASE,
)
_OLD_CUT = "Cut to 3.5 × 2 inches using the verified trim box."


def chart_file_rules():
    return {
        "source": "operator-or-order",
        "neverSearch": True,
        "neverGuess": True,
        "confirmCustomer": True,
        "keepOriginal": True,
        "fieryImports": "PRINT_READY",
        "exportName": "filename_PRINT_READY.pdf",
    }


def _steps():
    return [
        {
            "id": "start",
            "kind": "start",
            "title": "Start: new business card job",
            "detail": "Business card workflow: file to Fiery. Portrait cards use the same steps.",
        },
        {
            "id": "ask-file",
            "kind": "ask",
            "title": "Ask for the design file location",
            "detail": "Don't search for or guess the file. The location comes from the operator or the order.",
        },
        {
            "id": "confirm-customer",
            "kind": "ask",
            "title": "Open the file from that location",
            "detail": "Confirm it belongs to the right customer.",
        },
        {
            "id": "size",
            "kind": "decision",
            "title": "What size is the file?",
            "detail": (
                "3.5 × 2 in with no bleed goes to Photoshop. "
                "3.75 × 2.25 in with real bleed goes to Fiery. "
                "Portrait is 2 × 3.5 in trim and 2.25 × 3.75 in with bleed. "
                "Any other size stops for re-design and is never resized or stretched."
            ),
        },
        {
            "id": "canvas",
            "kind": "photoshop",
            "title": "Canvas size to the bleed size",
            "detail": "Anchor the artwork at the centre. Enlarge the canvas only, never the image.",
        },
        {
            "id": "background",
            "kind": "photoshop",
            "title": "Extend the background into the bleed",
            "detail": "Background only. Never regenerate text, logo or QR.",
        },
        {
            "id": "safe",
            "kind": "decision",
            "title": "Customer info unchanged and inside the 1/8 in safe area?",
            "detail": "The safe area is 1/8 in inside the trim. No means stop for human review.",
        },
        {
            "id": "export",
            "kind": "photoshop",
            "title": "Export filename_PRINT_READY.pdf",
            "detail": "Keep the original file untouched.",
        },
        {
            "id": "import",
            "kind": "fiery",
            "hook": "fiery.import",
            "title": "Import the file and put the job on HOLD",
            "detail": "Use the PRINT_READY file, never the original.",
        },
        {
            "id": "impose",
            "kind": "fiery",
            "hook": "fiery.impose",
            "preset": PRESET_NAME,
            "title": "Impose with preset London BC",
            "detail": "Right-click the job, choose Impose, then preset London BC.",
        },
        {
            "id": "sheet",
            "kind": "decision",
            "hook": "fiery.check-sheet",
            "title": "London BC found and the sheet looks right?",
            "detail": "No stretching, cropping or missing cards.",
        },
        {
            "id": "save",
            "kind": "fiery",
            "hook": "fiery.save-hold",
            "title": "Save the imposed job on HOLD",
            "detail": "Close the Impose window and click Save.",
        },
        {
            "id": "stock",
            "kind": "ask",
            "hook": "fiery.properties.stock",
            "title": "Ask: Matte or Glossy?",
            "detail": "Select Matte or Glossy cardstock in Properties. The stock must be on the shop list.",
        },
        {
            "id": "summary",
            "kind": "start",
            "hook": "fiery.summary",
            "title": "Job summary",
            "detail": "Ready to print after approval.",
        },
        {
            "id": "ready",
            "kind": "start",
            "hook": "fiery.ready",
            "title": "Ready to print after approval",
            "detail": "Ready to print after approval.",
        },
        {
            "id": "cutter",
            "kind": "ask",
            "hook": "duplo.load",
            "title": "Load Duplo DC-618 job no. 2, London BC",
            "detail": "Slitter modules in slots 2 and 3. Portrait cards use the same steps.",
        },
    ]


def _cut_instructions():
    return (
        "Cut to 3.5 × 2 inches on the Duplo DC-618, job no. 2, London BC. "
        "Slitter modules in slots 2 and 3. "
        "Portrait cards are 2 × 3.5 inches trim and 2.25 × 3.75 inches with bleed, and use the same steps. "
        "Never resize or stretch the file."
    )


def london_business_card_recipe():
    """Editable per-shop recipe. Callers may change cutter, preset, and instructions."""
    return {
        "id": "business-card",
        "product": "business-card",
        "version": 1,
        "name": "Business card",
        "workflow": WORKFLOW_NAME,
        "width": 3.5,
        "height": 2.0,
        "bleed": BLEED_IN,
        "safe": SAFE_IN,
        "minDpi": 300,
        "cutInstructions": _cut_instructions(),
        "fileRules": chart_file_rules(),
        "production": {
            "preset": PRESET_NAME,
            "safe": SAFE_IN,
            "trim": {
                "width": 3.5,
                "height": 2.0,
                "portrait": {"width": 2.0, "height": 3.5},
            },
            "withBleed": {
                "width": 3.75,
                "height": 2.25,
                "portrait": {"width": 2.25, "height": 3.75},
            },
            "orientations": ["landscape", "portrait"],
            "imposition": {
                "name": PRESET_NAME,
                "sheetWidthIn": 12,
                "sheetHeightIn": 18,
                "sheetWidthMm": 304.8,
                "sheetHeightMm": 457.2,
                "columns": 3,
                "rows": 8,
                "up": 24,
            },
            "cutter": {
                "model": "Duplo DC-618",
                "jobNumber": 2,
                "jobName": PRESET_NAME,
                "slitterSlots": [2, 3],
            },
            "steps": _steps(),
            "stops": list(STOPS),
            "kinds": dict(KIND_LABELS),
        },
    }


def is_london_card(recipe):
    if not isinstance(recipe, dict):
        return False
    production = recipe.get("production") or {}
    if production.get("preset") == PRESET_NAME:
        return True
    return recipe.get("workflow") == WORKFLOW_NAME


def layout_ok(recipe):
    production = (recipe or {}).get("production") or {}
    imposition = production.get("imposition") or {}
    card = production.get("withBleed") or {}
    try:
        columns = int(imposition["columns"])
        rows = int(imposition["rows"])
        up = int(imposition["up"])
        sheet_w = float(imposition["sheetWidthIn"])
        sheet_h = float(imposition["sheetHeightIn"])
        sheet_wm = float(imposition["sheetWidthMm"])
        sheet_hm = float(imposition["sheetHeightMm"])
        card_w = float(card["width"])
        card_h = float(card["height"])
    except (KeyError, TypeError, ValueError):
        return False
    if imposition.get("name") != PRESET_NAME:
        return False
    if columns != 3 or rows != 8 or up != columns * rows or up != 24:
        return False
    if abs(sheet_w - 12) > 0.01 or abs(sheet_h - 18) > 0.01:
        return False
    if abs(sheet_wm - sheet_w * 25.4) > 0.05 or abs(sheet_hm - sheet_h * 25.4) > 0.05:
        return False
    return columns * card_w <= sheet_w + 0.01 and rows * card_h <= sheet_h + 0.01


def print_ready_name(filename):
    stem = Path(str(filename or "")).stem
    if stem.lower().endswith("_print_ready"):
        stem = stem[: -len("_print_ready")]
    if not stem:
        stem = "artwork"
    return f"{stem}_PRINT_READY.pdf"


def _number(value):
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text


def normalise_stock_name(name):
    text = " ".join(str(name or "").split())
    match = _WEIGHT.match(text)
    if not match:
        return text
    return f"{_number(match.group(1))}pt matte"


def normalise_stock_list(names):
    found = []
    for name in names or []:
        canon = normalise_stock_name(name)
        if canon and canon not in found:
            found.append(canon)
    return found


_CARDSTOCK = re.compile(r"\b\d+(?:\.\d+)?\s*-?\s*pt\b|\bcard|\bcover\b", re.IGNORECASE)


def is_cardstock(name):
    """Business cards print on cardstock: a pt weight, or a card or cover stock. Text weights never match."""
    return bool(_CARDSTOCK.search(str(name or "")))


def match_finish(finish, shop_stocks):
    text = str(finish or "").strip().lower()
    if "matte" in text or text == "matt":
        needle = "matte"
    elif "gloss" in text:
        needle = "gloss"
    else:
        return None
    for stock in shop_stocks or []:
        canon = normalise_stock_name(stock)
        if needle in canon.lower() and is_cardstock(canon):
            return canon
    return None


def _near(width, height, target_w, target_h):
    return abs(width - target_w) <= SIZE_TOLERANCE and abs(height - target_h) <= SIZE_TOLERANCE


def classify_page(width, height, recipe=None):
    production = (recipe or london_business_card_recipe()).get("production") or {}
    trim = production.get("trim") or {}
    full = production.get("withBleed") or {}
    portrait_trim = trim.get("portrait") or {}
    portrait_full = full.get("portrait") or {}
    if _near(width, height, float(trim.get("width", 3.5)), float(trim.get("height", 2))):
        return "trim", "landscape"
    if _near(width, height, float(portrait_trim.get("width", 2)), float(portrait_trim.get("height", 3.5))):
        return "trim", "portrait"
    if _near(width, height, float(full.get("width", 3.75)), float(full.get("height", 2.25))):
        return "bleed", "landscape"
    if _near(width, height, float(portrait_full.get("width", 2.25)), float(portrait_full.get("height", 3.75))):
        return "bleed", "portrait"
    return "other", None


def _safe_inches(recipe):
    production = (recipe or {}).get("production") or {}
    if production.get("safe") is not None:
        return float(production["safe"])
    if recipe and recipe.get("safe") is not None:
        return float(recipe["safe"])
    return SAFE_IN


def _bleed_inches(recipe):
    if recipe and recipe.get("bleed") is not None:
        return float(recipe["bleed"])
    return BLEED_IN


def _trim_for(orientation, recipe):
    production = recipe.get("production") or london_business_card_recipe()["production"]
    trim = production["trim"]
    if orientation == "portrait":
        return {"width": float(trim["portrait"]["width"]), "height": float(trim["portrait"]["height"])}
    return {"width": float(trim["width"]), "height": float(trim["height"])}


def _target_for(orientation, recipe):
    production = recipe.get("production") or london_business_card_recipe()["production"]
    full = production["withBleed"]
    if orientation == "portrait":
        return float(full["portrait"]["width"]), float(full["portrait"]["height"])
    return float(full["width"]), float(full["height"])


def _customer_conflict(filename, document, customer):
    wanted = " ".join(str(customer or "").split()).lower()
    if not wanted:
        return False
    parts = [str(filename or "")]
    for page in document:
        parts.append(page.get_text("text") or "")
    for line in "\n".join(parts).splitlines():
        if "customer:" not in line.lower():
            continue
        named = " ".join(line.split(":", 1)[1].split()).lower().strip(" .")
        if wanted not in named and named not in wanted:
            return True
    return False


def _content_too_close(document, safe_in, bleed_in):
    bleed_pt = bleed_in * PT
    safe_pt = safe_in * PT
    for page in document:
        rect = page.rect
        trim = pymupdf.Rect(
            rect.x0 + bleed_pt,
            rect.y0 + bleed_pt,
            rect.x1 - bleed_pt,
            rect.y1 - bleed_pt,
        )
        inner = pymupdf.Rect(
            trim.x0 + safe_pt,
            trim.y0 + safe_pt,
            trim.x1 - safe_pt,
            trim.y1 - safe_pt,
        )
        if inner.width <= 1 or inner.height <= 1:
            return True
        trim_area = max(trim.width * trim.height, 1)
        for word in page.get_text("words"):
            if not str(word[4]).strip():
                continue
            x0, y0, x1, y1 = word[:4]
            if x0 < inner.x0 - 0.6 or y0 < inner.y0 - 0.6 or x1 > inner.x1 + 0.6 or y1 > inner.y1 + 0.6:
                return True
        for info in page.get_image_info():
            x0, y0, x1, y1 = info.get("bbox") or (0, 0, 0, 0)
            area = max(0, x1 - x0) * max(0, y1 - y0)
            if area >= 0.9 * trim_area:
                continue
            if x0 < inner.x0 - 0.6 or y0 < inner.y0 - 0.6 or x1 > inner.x1 + 0.6 or y1 > inner.y1 + 0.6:
                return True
        for drawing in page.get_drawings():
            box = drawing.get("rect")
            if box is None:
                continue
            area = max(0, box.width) * max(0, box.height)
            if area < 8 or area >= 0.9 * trim_area:
                continue
            if box.x0 < inner.x0 - 0.6 or box.y0 < inner.y0 - 0.6 or box.x1 > inner.x1 + 0.6 or box.y1 > inner.y1 + 0.6:
                return True
    return False


def _white_edges(document, bleed_in):
    ring = max(2, round(bleed_in * PT))
    for page in document:
        pix = page.get_pixmap(dpi=72, alpha=False)
        data = pix.samples
        channels = pix.n
        width, height = pix.width, pix.height
        white = 0
        total = 0
        for y in range(height):
            edge_row = y < ring or y >= height - ring
            row = y * width * channels
            for x in range(width):
                if not edge_row and ring <= x < width - ring:
                    continue
                index = row + x * channels
                total += 1
                if data[index] >= 245 and data[index + 1] >= 245 and data[index + 2] >= 245:
                    white += 1
        if total and white / total > 0.6:
            return True
    return False


def _uses_cmyk(document, page):
    """True when the page draws in CMYK, so the bleed is built in CMYK too and matches the art."""
    try:
        streams = [page.read_contents() or b""]
        for xref, *_ in page.get_xobjects():
            try:
                streams.append(document.xref_stream(xref) or b"")
            except Exception:
                continue
        for item in page.get_images(full=True):
            if "CMYK" in str(item[5]).upper():
                return True
        for data in streams:
            if b"DeviceCMYK" in data or re.search(rb"(?:^|\s)[kK](?:\s|$)", data):
                return True
    except Exception:
        return False
    return False


def _edge_image(page, pad, dpi, cmyk=False):
    """Page render with its outer pixel row and column repeated into a pad on every side."""
    if cmyk:
        pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csCMYK)
        image = Image.frombytes("CMYK", (pix.width, pix.height), pix.samples)
        mode = "CMYK"
    else:
        image = Image.open(io.BytesIO(page.get_pixmap(dpi=dpi, alpha=False).tobytes("png"))).convert("RGB")
        mode = "RGB"
    width, height = image.size
    canvas = Image.new(mode, (width + 2 * pad, height + 2 * pad))
    canvas.paste(image, (pad, pad))
    left = image.crop((0, 0, 1, height)).resize((pad, height))
    right = image.crop((width - 1, 0, width, height)).resize((pad, height))
    top = image.crop((0, 0, width, 1)).resize((width, pad))
    bottom = image.crop((0, height - 1, width, height)).resize((width, pad))
    canvas.paste(left, (0, pad))
    canvas.paste(right, (pad + width, pad))
    canvas.paste(top, (pad, 0))
    canvas.paste(bottom, (pad, pad + height))
    corners = (
        ((0, 0), (0, 0)),
        ((width - 1, 0), (width + pad, 0)),
        ((0, height - 1), (0, height + pad)),
        ((width - 1, height - 1), (width + pad, height + pad)),
    )
    for origin, position in corners:
        tile = Image.new(mode, (pad, pad), image.getpixel(origin))
        canvas.paste(tile, position)
    return canvas


def _edge_png(page, pad, dpi):
    buffer = io.BytesIO()
    _edge_image(page, pad, dpi).save(buffer, format="PNG")
    return buffer.getvalue()


def _insert_edge(new_page, document, page, pad, dpi):
    if _uses_cmyk(document, page):
        canvas = _edge_image(page, pad, dpi, cmyk=True)
        pixmap = pymupdf.Pixmap(pymupdf.csCMYK, canvas.width, canvas.height, canvas.tobytes(), False)
        new_page.insert_image(new_page.rect, pixmap=pixmap)
    else:
        new_page.insert_image(new_page.rect, stream=_edge_png(page, pad, dpi))


def extend_document(document, bleed_in, target_w, target_h):
    """New PDF. The source document is not modified. Artwork is placed at scale 1."""
    produced = pymupdf.open()
    pad = max(1, round(bleed_in * 300))
    try:
        for page in document:
            src_w = float(page.rect.width)
            src_h = float(page.rect.height)
            new_page = produced.new_page(width=target_w * PT, height=target_h * PT)
            _insert_edge(new_page, document, page, pad, 300)
            x = (new_page.rect.width - src_w) / 2
            y = (new_page.rect.height - src_h) / 2
            dest = pymupdf.Rect(x, y, x + src_w, y + src_h)
            if abs(dest.width - src_w) > 0.5 or abs(dest.height - src_h) > 0.5:
                raise ValueError("canvas placement changed the artwork scale")
            new_page.show_pdf_page(dest, document, page.number)
        return produced.tobytes()
    finally:
        produced.close()


def _words(document):
    return [word[4] for page in document for word in page.get_text("words") if str(word[4]).strip()]


def _artwork_unchanged(source, extended):
    before = _words(source)
    opened = pymupdf.open(stream=extended, filetype="pdf")
    try:
        if _words(opened) != before:
            return False
        for index, page in enumerate(source):
            old_words = [word for word in page.get_text("words") if str(word[4]).strip()]
            new_words = [word for word in opened[index].get_text("words") if str(word[4]).strip()]
            if not old_words:
                continue
            old_width = old_words[0][2] - old_words[0][0]
            new_width = new_words[0][2] - new_words[0][0]
            if abs(old_width - new_width) > 0.8:
                return False
        return True
    finally:
        opened.close()


def _halt(message):
    return {
        "proceed": False,
        "stop": message,
        "pdf": None,
        "outputName": None,
        "trim": None,
        "public": {
            "route": "stop",
            "orientation": None,
            "proceed": False,
            "stop": message,
            "outputName": None,
            "kind": "stop",
            "message": message,
        },
    }


def _go(route, orientation, pdf, filename, trim, message):
    name = print_ready_name(filename)
    kind = "photoshop" if route == "extend" else "fiery"
    return {
        "proceed": True,
        "stop": None,
        "pdf": pdf,
        "outputName": name,
        "trim": trim,
        "public": {
            "route": route,
            "orientation": orientation,
            "proceed": True,
            "stop": None,
            "outputName": name,
            "kind": kind,
            "message": message,
        },
    }


def assess_london_card(data, recipe, filename="", customer="", file_location=None):
    """Route one business-card file. Never searches a disk and never resizes other sizes."""
    if file_location is not None and not str(file_location).strip():
        return _halt(STOP_FILE)
    if not data:
        return _halt(STOP_FILE)
    try:
        document = pymupdf.open(stream=bytes(data), filetype="pdf")
    except Exception:
        return _halt(STOP_FILE)
    try:
        if document.needs_pass or document.page_count == 0:
            return _halt(STOP_FILE)
        if _customer_conflict(filename, document, customer):
            return _halt(STOP_FILE)
        classes = [classify_page(page.rect.width / PT, page.rect.height / PT, recipe) for page in document]
        kinds = {item[0] for item in classes}
        orientations = {item[1] for item in classes}
        if kinds != {"trim"} and kinds != {"bleed"}:
            return _halt(STOP_SIZE)
        if len(orientations) != 1:
            return _halt(STOP_SIZE)
        orientation = classes[0][1]
        safe = _safe_inches(recipe)
        bleed = _bleed_inches(recipe)
        trim = _trim_for(orientation, recipe)
        if classes[0][0] == "trim":
            if _content_too_close(document, safe, 0):
                return _halt(STOP_CUT)
            try:
                target_w, target_h = _target_for(orientation, recipe)
                extended = extend_document(document, bleed, target_w, target_h)
            except Exception:
                return _halt(STOP_STRETCH)
            if not _artwork_unchanged(document, extended):
                return _halt(STOP_STRETCH)
            opened = pymupdf.open(stream=extended, filetype="pdf")
            try:
                if _content_too_close(opened, safe, bleed):
                    return _halt(STOP_CUT)
            finally:
                opened.close()
            return _go(
                "extend",
                orientation,
                extended,
                filename,
                trim,
                "No bleed. The canvas was enlarged from the centre and the artwork was not scaled. "
                "Only the background was extended. The original file is unchanged.",
            )
        if _white_edges(document, bleed):
            return _halt(STOP_BLEED)
        if _content_too_close(document, safe, bleed):
            return _halt(STOP_CUT)
        return _go(
            "check-bleed",
            orientation,
            None,
            filename,
            trim,
            "Bleed is real, with no white edges. Fiery imports the PRINT_READY file, never the original.",
        )
    finally:
        document.close()


def fresh_checklist(recipe, output_name=None):
    production = (recipe or {}).get("production") or {}
    cutter = production.get("cutter") or {}
    steps = []
    for source in production.get("steps") or _steps():
        step = copy.deepcopy(source)
        step["status"] = "pending"
        if step["id"] == "import" and output_name:
            step["detail"] = f"Import {output_name} and put the job on HOLD. Use the PRINT_READY file, never the original."
        if step["id"] == "cutter" and cutter:
            slots = ", ".join(str(slot) for slot in cutter.get("slitterSlots") or [])
            step["title"] = (
                f"Load {cutter.get('model', 'Duplo DC-618')} job no. {cutter.get('jobNumber')}, "
                f"{cutter.get('jobName', PRESET_NAME)}"
            )
            step["detail"] = f"Slitter modules in slots {slots}. Portrait cards use the same steps."
        steps.append(step)
    return steps


def _current_step(checklist):
    return next((step for step in checklist if step.get("status") != "done"), None)


def apply_production_event(checklist, event, recipe, shop_stocks):
    current = _current_step(checklist)
    if current is None:
        return {"stop": None, "done": True, "checklist": checklist}
    requested = event.get("step")
    if requested and requested != current["id"]:
        return {"stop": "Finish the current step first.", "done": False, "checklist": checklist}
    stop = None
    step_id = current["id"]
    if step_id == "import":
        name = str(event.get("file") or "")
        if name and "PRINT_READY" not in name.upper():
            stop = STOP_ORIGINAL
    elif step_id == "impose":
        preset = str(event.get("preset") or "")
        if preset != PRESET_NAME or not layout_ok(recipe):
            stop = STOP_PRESET
    elif step_id == "sheet":
        sheet = event.get("sheet") or {}
        if sheet.get("stretched"):
            stop = STOP_STRETCH
        elif sheet.get("cropped") or sheet.get("missingCards") or not layout_ok(recipe):
            stop = STOP_PRESET
    elif step_id == "save":
        if event.get("held") is not True:
            stop = STOP_HOLD
    elif step_id == "stock":
        matched = match_finish(event.get("finish") or event.get("stock"), shop_stocks)
        if not matched:
            stop = STOP_STOCK
        else:
            current["stock"] = matched
    elif event.get("ok") is False and step_id in {"ask-file", "confirm-customer"}:
        stop = STOP_FILE
    elif event.get("ok") is False and step_id == "size":
        stop = STOP_SIZE
    if stop:
        current["status"] = "stopped"
        current["stop"] = stop
        return {"stop": stop, "done": False, "checklist": checklist}
    current["status"] = "done"
    done = _current_step(checklist) is None
    return {"stop": None, "done": done, "checklist": checklist}


def connector_production_hook(job):
    recipe = (job or {}).get("recipe") or {}
    if not is_london_card(recipe):
        return None
    production = recipe.get("production") or {}
    route = (job or {}).get("cardRoute") or {}
    output = route.get("outputName") or print_ready_name("artwork.pdf")
    return {
        "workflow": recipe.get("workflow") or WORKFLOW_NAME,
        "file": output,
        "importRule": "Import the PRINT_READY file, never the original.",
        "fieryImports": "PRINT_READY",
        "imposition": production.get("imposition"),
        "cutter": production.get("cutter"),
        "steps": [step.get("id") for step in production.get("steps") or []],
        "stops": production.get("stops") or list(STOPS),
    }


def merge_production(base_recipe, edits):
    source = base_recipe if isinstance(base_recipe, dict) and base_recipe.get("production") else london_business_card_recipe()
    production = copy.deepcopy(source["production"])
    if not isinstance(edits, dict):
        return production
    preset = str(edits.get("preset") or "").strip()
    if preset:
        production["preset"] = preset[:80]
        if isinstance(production.get("imposition"), dict):
            production["imposition"]["name"] = production["preset"]
    cutter = edits.get("cutter") if isinstance(edits.get("cutter"), dict) else {}
    if "jobNumber" in cutter:
        number = int(cutter["jobNumber"])
        if not 1 <= number <= 999:
            raise ValueError("cutter job number")
        production["cutter"]["jobNumber"] = number
    if cutter.get("jobName"):
        production["cutter"]["jobName"] = str(cutter["jobName"])[:80]
    if isinstance(cutter.get("slitterSlots"), list) and cutter["slitterSlots"]:
        production["cutter"]["slitterSlots"] = [int(slot) for slot in cutter["slitterSlots"]]
    return production


def pin_job_recipe(recipe, shop_recipe):
    """Copy the shop's business-card production block onto the pinned job recipe."""
    product = str((recipe or {}).get("product") or (recipe or {}).get("id") or "")
    if product != "business-card":
        return recipe
    shop = shop_recipe if isinstance(shop_recipe, dict) else {}
    fallback = london_business_card_recipe()
    source = shop if isinstance(shop.get("production"), dict) else fallback
    pinned = dict(recipe)
    pinned["production"] = copy.deepcopy(source["production"])
    pinned["workflow"] = source.get("workflow") or WORKFLOW_NAME
    pinned["fileRules"] = copy.deepcopy(source.get("fileRules") or chart_file_rules())
    pinned["cutInstructions"] = shop.get("cutInstructions") or source.get("cutInstructions") or fallback["cutInstructions"]
    if isinstance(shop.get("production"), dict) and shop.get("safe") is not None:
        pinned["safe"] = float(shop["safe"])
    else:
        pinned["safe"] = float(fallback["safe"])
    if isinstance(shop.get("production"), dict) and shop.get("bleed") is not None:
        pinned["bleed"] = float(shop["bleed"])
    else:
        pinned["bleed"] = float(fallback["bleed"])
    if pinned.get("production") is not None:
        pinned["production"]["safe"] = pinned["safe"]
    return pinned


def _stamp():
    return datetime.now(timezone.utc).isoformat()


async def seed_london_card_shops(database, slugs=SEED_SLUGS):
    """Insert or upgrade the London card recipe for the named shops. Safe to repeat."""
    from p2g.tenancy import shop_scope, unscoped

    raw = database.raw if hasattr(database, "raw") else database
    summary = {}
    for slug in slugs:
        with unscoped():
            shop = await raw.shops.find_one({"slug": slug})
            if not shop:
                shop_id = slug
                await raw.shops.insert_one(
                    {
                        "_id": shop_id,
                        "name": "Print2Go London" if slug == "print2go-london" else "Print2Go",
                        "slug": slug,
                        "created": _stamp(),
                        "status": "active",
                        "billing": {"enabled": False, "provider": "stripe"},
                    }
                )
            else:
                shop_id = shop["_id"]
        with shop_scope(str(shop_id)):
            rows = await database.recipes.find({"id": "business-card"}).to_list(50)
            if any((row.get("production") or {}).get("preset") == PRESET_NAME for row in rows):
                summary[slug] = "present"
                continue
            if not rows:
                recipe = london_business_card_recipe()
                recipe["created"] = _stamp()
                await database.recipes.insert_one(recipe)
                summary[slug] = "inserted"
                continue
            latest = max(rows, key=lambda row: row.get("version") or 0)
            fresh = london_business_card_recipe()
            updates = {
                "production": fresh["production"],
                "workflow": WORKFLOW_NAME,
                "fileRules": fresh["fileRules"],
            }
            if latest.get("safe") == 0.25 and latest.get("cutInstructions") == _OLD_CUT:
                updates["safe"] = SAFE_IN
                updates["cutInstructions"] = fresh["cutInstructions"]
            await database.recipes.update_one(
                {"id": "business-card", "version": latest.get("version")},
                {"$set": updates},
            )
            summary[slug] = "upgraded"
    return summary
