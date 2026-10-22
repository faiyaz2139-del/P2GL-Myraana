"""One tenant shop and one real PDF pass per Print2Go catalog item.

Keep the job defaults in step with defaultsFromPreset in frontend/src/JobForm.js.
This module does not import the API, Motor, or the workflow runner. CI can
collect it with PyMuPDF, pypdf, Pillow, and reportlab only.
"""
import asyncio
import csv
import hashlib
import io
import os
import re
from collections import Counter

from PIL import Image
from reportlab.lib.colors import CMYKColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from p2g.catalog_seed import SpecError, load_presets
from p2g.pdfcheck import inspect, make_print_ready, prepare, verify
from p2g.products import UNIT_TO_INCH, resolve_spec
from p2g.tenancy import TenantDatabase, new_shop_records, shop_scope, signup_is_open
from test_tenancy import MemoryDB


STARTER_IDS = {"business-card", "flyer", "custom"}
FONT_NAME = "DejaVuReadiness"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FIX_VERBS = (
    "export", "upload", "move", "replace", "flatten", "outline", "embed",
    "choose", "accept", "check", "look", "confirm", "start", "verify", "add",
)
FINISHING = {
    "3 Hole Punch",
    "Cerlox (Comb) Binding",
    "Coil (Spiral) Binding",
    "Folding",
    "Perfect Binding",
    "Saddle Stitch Binding",
    "Scoring & Perforation",
    "Stapling",
    "Wire-O Binding",
}
# Flat prints whose pages say any/custom/various and publish no numbers.
# The size below is a stand-in for the check. It is not a catalog measurement.
CUSTOMER_SIZES = {
    "Store Front Signs": (4, 2, "ft"),
    "Fabric Banners": (24, 36, "in"),
    "Blue Backed Posters": (24, 36, "in"),
    "Clear Labels & Stickers": (4, 4, "in"),
    "Kiss-Cut Sticker Singles": (3, 3, "in"),
    "Perforated Window Stickers": (12, 12, "in"),
    "UV DTF Image Transfer Stickers": (3, 3, "in"),
    "Custom Gift Wrap": (24, 36, "in"),
}
NO_TRIM = {
    "Wall Flags",
    "Sold Key Sign",
    "Office & Store Branding Signs",
    "Custom Tab Printing",
}
_IMAGE_BYTES = {}
_FONT_READY = False


def catalog_items():
    return [item for item in load_presets()["presets"] if item["id"] not in STARTER_IDS]


def display_name(preset, items):
    twins = [item for item in items if item["name"] == preset["name"]]
    if len(twins) > 1:
        source = preset.get("sourceId") or preset["id"]
        return f"{preset['name']} (source {source})"
    return preset["name"]


def _inches(value, unit):
    return float(value) * UNIT_TO_INCH[unit]


def _in_range(width, height, unit):
    width_in, height_in = _inches(width, unit), _inches(height, unit)
    return 0.4 <= width_in <= 150 and 0.4 <= height_in <= 150


def first_size(preset):
    """First listed size that survives the 0.4–150 inch job limit."""
    for size in preset.get("sizes") or []:
        if _in_range(size["width"], size["height"], size["unit"]):
            return size
    return None


def custom_minimum(preset):
    custom = preset.get("customSize") or {}
    width, height, unit = custom.get("width_min"), custom.get("height_min"), custom.get("unit") or "in"
    if width in (None, "") or height in (None, ""):
        return None
    if not _in_range(width, height, unit):
        return None
    return {"width": width, "height": height, "unit": unit}


def default_shape(preset):
    """Keep in step with defaultShape in JobForm.js."""
    shapes = preset.get("shapes") or []
    name = (preset.get("name") or "").lower()
    for item in shapes:
        head = str(item).lower().split(" ")[0]
        if head and head in name:
            return item
    if len(shapes) == 1:
        return shapes[0]
    return "rectangle"


def default_grommets(preset):
    for item in preset.get("hardware") or []:
        match = re.search(r"(\d+)\s*grommet", str(item), re.I)
        if match:
            return int(match.group(1))
    return 0


def form_prefills_size(preset):
    if preset.get("sizes"):
        return True
    custom = preset.get("customSize") or {}
    return custom.get("width_min") not in (None, "") and custom.get("height_min") not in (None, "")


def _size_text(width, height, unit):
    return f"{_trim(width)} × {_trim(height)} {unit}"


def _trim(value):
    return f"{float(value):.3f}".rstrip("0").rstrip(".")


def _join(parts):
    return " ".join(part.strip() for part in parts if part and part.strip())


def classify(preset):
    """Decide whether this catalog row is run, unsupported, or n/a."""
    name = preset["name"]
    lowered = name.lower()
    if preset.get("kind") == "service":
        return _skip("n/a", "service", f"{name} is a service. No print file is produced.")
    if name == "Print2Go Studio":
        return _skip("n/a", "studio", "Print2Go Studio is a booking, not a print product.")
    if (preset.get("category") or "").startswith("Clothing") or re.search(r"t-shirt|hoodie|polo", lowered):
        return _skip(
            "n/a",
            "apparel",
            "Apparel. A decoration size may be listed, and Myraana does not manufacture the garment.",
        )
    if re.search(r"mug|tumbler|water bottle|wine cup|flask", lowered):
        return _skip(
            "n/a",
            "drinkware",
            "Drinkware. A decoration size may be listed, and Myraana does not manufacture the item.",
        )
    if name in FINISHING:
        return _skip(
            "n/a",
            "finishing-only",
            "Finishing operation with no print file. Punching, binding, folding, and scoring are not imposed.",
        )
    if lowered == "booklets":
        return _skip(
            "unsupported",
            "booklet imposition",
            "Saddle-stitched booklet. Multi-page imposition is not generated. Sides stay 1 or 2.",
        )
    if "12 months" in lowered:
        return _skip(
            "unsupported",
            "multi-page calendar",
            "12-month wall calendar. The parsed size is one sheet. A 12-page calendar is not imposed.",
        )
    if lowered.endswith("labels sheet"):
        safe_note = ""
        if any(min(size["width"], size["height"]) <= 0.5 and size.get("unit") == "in" for size in preset.get("sizes") or []):
            safe_note = " The 0.5 in side cannot fit the 0.25 in safe zone."
        return _skip(
            "unsupported",
            "n-up labels",
            "The sizes are one label, and the product is many labels on a sheet. N-up imposition is not generated."
            + safe_note,
        )
    if name in {"NFC Contactless Google Review Card", "Custom Pro Stamp", "Legal & Notary Seal", "Popup Counter", "Snap Frame"}:
        extra = ""
        if name == "Custom Pro Stamp":
            extra = " Some listed sizes are under the 0.4 in floor, including 0.8 × 0.8 cm."
        if name == "Legal & Notary Seal":
            extra = " The listed faces start at 0.5625 in, which is above the floor, and the seal is still not made."
        if name == "NFC Contactless Google Review Card":
            extra = " The 3.5 × 2 in face can be described. The chip is not produced."
        return _skip(
            "unsupported",
            "manufactured",
            f"{name} is a manufactured object, not a flat PDF.{extra}",
        )
    if name in {"Feather Flags", "Tear Drop Flags"}:
        return _skip(
            "unsupported",
            "height-only flag",
            "Only a height is published (8 ft, 11 ft, and 13 ft). Width is not a trim the PDF pipeline can pin.",
        )
    if name == "NCR Forms":
        return _skip(
            "unsupported",
            "carbonless",
            "Multi-part carbonless set. A flat flyer pass would hide the parts. The set is not generated.",
        )
    if name == "Business Laser Cheques" and not preset.get("sizes") and str(preset.get("sourceId")) == "321":
        return _skip(
            "unsupported",
            "no published trim",
            "No size is published on this duplicate listing (source 321). "
            "The other Business Laser Cheques listing has sizes and is checked separately.",
        )
    chosen = _choose_size(preset)
    if chosen is None:
        if name in NO_TRIM:
            reason = "No finished width and height are published, and this row is not a flat print with a known customer size. Nothing was invented."
        else:
            reason = "No in-range finished size is published. Nothing was invented."
        return _skip("unsupported", "no published trim", reason)
    return {"action": "run", "choice": chosen}


def _skip(result, cause, reason):
    return {"action": "skip", "result": result, "cause": cause, "reason": reason}


def _choose_size(preset):
    size = first_size(preset)
    if size is not None:
        return {
            "width": size["width"],
            "height": size["height"],
            "unit": size["unit"],
            "sizeId": size["id"],
            "source": "preset",
        }
    custom = custom_minimum(preset)
    if custom is not None:
        return {**custom, "sizeId": "custom", "source": "custom-min"}
    stand_in = CUSTOMER_SIZES.get(preset["name"])
    if stand_in and not preset.get("sizes"):
        width, height, unit = stand_in
        return {
            "width": width,
            "height": height,
            "unit": unit,
            "sizeId": "custom",
            "source": "customer",
        }
    return None


def _payload(preset, choice):
    sides = 1 if preset.get("sides") == [1] else 2
    folds = preset.get("folds") or []
    binding = preset.get("binding") or []
    hardware = preset.get("hardware") or []
    payload = {
        "product": preset["id"],
        "sizeId": choice["sizeId"],
        "sides": sides,
        "options": {
            "fold": folds[0] if len(folds) == 1 else "none",
            "shape": default_shape(preset),
            "dieCut": bool(re.search(r"die-?\s*cut|kiss-?\s*cut", preset["name"], re.I)),
            "grommets": default_grommets(preset),
            "binding": binding[0] if len(binding) == 1 else "",
            "hardware": hardware[0] if len(hardware) == 1 else "",
        },
    }
    if preset.get("stocks"):
        payload["stock"] = preset["stocks"][0]
    if preset.get("finishes"):
        payload["finish"] = preset["finishes"][0]
    if choice["sizeId"] == "custom":
        payload["width"] = choice["width"]
        payload["height"] = choice["height"]
        payload["unit"] = choice["unit"]
    short = min(_inches(choice["width"], choice["unit"]), _inches(choice["height"], choice["unit"]))
    safe_override = None
    if 0.25 * 2 >= short:
        safe_override = round((short - 0.08) / 2, 4)
        payload["safe"] = safe_override
    return payload, sides, safe_override


def _font():
    global _FONT_READY
    if not _FONT_READY:
        pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))
        _FONT_READY = True


def _tiff(pixels):
    cached = _IMAGE_BYTES.get(pixels)
    if cached is None:
        image = Image.new("CMYK", (pixels, pixels), (0, 200, 180, 0))
        buffer = io.BytesIO()
        image.save(buffer, format="TIFF")
        cached = buffer.getvalue()
        _IMAGE_BYTES[pixels] = cached
    return cached


def build_pdf(media_w, media_h, pages, kind):
    """Synthetic artwork. kind is pass, nobleed (same builder), rgb, or lowdpi."""
    _font()
    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=(media_w * 72, media_h * 72))
    for _ in range(pages):
        if kind == "rgb":
            document.setFillColorRGB(0.1, 0.25, 0.8)
        else:
            document.setFillColor(CMYKColor(0.15, 0.05, 0, 0))
        document.rect(0, 0, media_w * 72, media_h * 72, fill=1, stroke=0)
        if kind == "lowdpi":
            placed = 0.3
            pixels = 12
        elif kind != "rgb":
            placed = min(0.45, max(0.2, min(media_w, media_h) * 0.3))
            pixels = 180
        else:
            placed = None
            pixels = None
        if placed is not None:
            document.drawImage(
                ImageReader(io.BytesIO(_tiff(pixels))),
                6,
                6,
                width=placed * 72,
                height=placed * 72,
                preserveAspectRatio=True,
                mask=None,
                anchor="sw",
            )
        if kind == "rgb":
            document.setFillColorRGB(0, 0, 0)
        else:
            document.setFillColor(CMYKColor(0, 0, 0, 1))
        document.setFont(FONT_NAME, 6)
        document.drawCentredString(media_w * 36, media_h * 36, "OK")
        document.showPage()
    document.save()
    return output.getvalue()


def _clear(text):
    lowered = text.lower()
    return any(verb in lowered for verb in FIX_VERBS)


def _pipeline(recipe, sides):
    media_w = recipe["width"] + 2 * recipe["bleed"]
    media_h = recipe["height"] + 2 * recipe["bleed"]
    good = build_pdf(media_w, media_h, sides, "pass")
    report = inspect(good, recipe, sides)
    if report["errors"]:
        return {"ok": False, "detail": "Positive file: " + " ".join(report["errors"])}
    if report["bleed"] != "correct":
        return {"ok": False, "detail": f"Positive file bleed is {report['bleed']}."}
    if report["colourMode"]["status"] != "pass":
        return {"ok": False, "detail": f"Positive file colour is {report['colourMode']['status']}."}
    if any(check["name"] == "dpi" and check["status"] != "pass" for check in report["artworkChecks"]):
        return {"ok": False, "detail": "Positive file did not pass the image DPI check."}
    prepared = prepare(good, recipe, False)
    ready = make_print_ready(prepared, recipe, "readiness-job", 1)
    digest = hashlib.sha256(ready).hexdigest()
    verified = verify(ready, recipe, sides, digest)
    if verified["errors"]:
        return {"ok": False, "detail": "PRINT_READY verify: " + " ".join(verified["errors"])}
    if not any("boxes ok" in item for item in verified.get("checks") or []):
        return {"ok": False, "detail": "PRINT_READY verify did not report boxes ok."}

    trim = build_pdf(recipe["width"], recipe["height"], sides, "pass")
    missing = inspect(trim, recipe, sides)
    if missing["errors"] or missing["bleed"] != "missing":
        return {
            "ok": False,
            "detail": "Trim-only file should stop for a bleed decision with no errors. "
            + " ".join(missing["errors"])
            + f" bleed={missing['bleed']}.",
        }

    rgb = build_pdf(media_w, media_h, sides, "rgb")
    rgb_report = inspect(rgb, recipe, sides)
    rgb_notes = " ".join(rgb_report["warnings"])
    if rgb_report["errors"] or "DeviceRGB" not in rgb_notes or "not converted" not in rgb_notes:
        return {
            "ok": False,
            "detail": "RGB file should warn, name DeviceRGB, and say it is not converted. "
            + " ".join(rgb_report["errors"])
            + " "
            + rgb_notes,
        }
    if not _clear(rgb_notes):
        return {"ok": False, "detail": "RGB warning does not say how to fix it."}

    low = build_pdf(media_w, media_h, sides, "lowdpi")
    low_report = inspect(low, recipe, sides)
    low_errors = " ".join(low_report["errors"])
    if "minimum is 300 dpi" not in low_errors:
        return {"ok": False, "detail": "Low-dpi file should block with the 300 dpi minimum. " + low_errors}
    if not _clear(low_errors):
        return {"ok": False, "detail": "Low-dpi error does not say how to fix it."}
    return {"ok": True, "verified_errors": verified["errors"]}


def _pass_reason(preset, choice, recipe, safe_override):
    parts = [
        f"Verified {_size_text(recipe['width'], recipe['height'], 'in')} trim, "
        f"{'1 side' if preset.get('sides') == [1] else '2 sides'}, {recipe['bleed']} in bleed, CMYK, "
        "an image at or above 300 dpi, text inside the safe zone, and PRINT_READY boxes.",
        "A trim-only file stops for a decision and is not stretched.",
        "An RGB file warns (DeviceRGB, not converted) and is not rejected.",
        "A low-dpi image is blocked (minimum is 300 dpi).",
    ]
    if choice["source"] == "customer":
        parts.append(
            f"The catalog page does not publish a number. This job uses a stand-in customer size of "
            f"{_size_text(choice['width'], choice['height'], choice['unit'])}. That size was not read from the catalog."
        )
    elif choice["source"] == "custom-min":
        custom = preset.get("customSize") or {}
        parts.append(
            f"The job uses the published minimum {_size_text(choice['width'], choice['height'], choice['unit'])}."
        )
        for key, label in (("width_max", "width"), ("height_max", "height")):
            raw = custom.get(key)
            if raw in (None, ""):
                continue
            unit = custom.get("unit") or "in"
            if _inches(raw, unit) > 150:
                parts.append(
                    f"The page lists a maximum {label} of {_trim(raw)} {unit}. "
                    "That is above the 150 in cap and is not sent to the PDF builder."
                )
    elif len(preset.get("sizes") or []) > 1:
        parts.append(
            f"The job uses the first in-range preset size, {_size_text(choice['width'], choice['height'], choice['unit'])}."
        )
    if safe_override is not None:
        parts.append(
            f"The 0.25 in safe zone does not fit this trim, so this job uses {safe_override} in. The shop default is unchanged."
        )
    lowered = preset["name"].lower()
    if any(token in lowered for token in ("foil", "spot uv", "fluorescent")):
        parts.append("The foil, spot UV, or fluorescent plate is not separated. The CMYK file is what was checked.")
    if "cheque" in lowered and "giant" not in lowered:
        parts.append("MICR, numbering, and 2-up imposition are not generated. The 1-up PDF is what was checked.")
    if lowered.endswith("labels sheet"):
        parts.append("N-up is not generated.")
    if any(token in lowered for token in ("step & repeat", "step and repeat", "gang")):
        parts.append("Myraana does not build the repeating or ganged layout. The supplied sheet is what was checked.")
    if preset.get("folds") or any(token in lowered for token in ("brochure", "menu", "folder", "door hanger", "table tent")):
        parts.append("Fold, pockets, and the die are cut instructions. They are not imposed.")
    elif re.search(r"die-?\s*cut|kiss-?\s*cut", preset["name"], re.I):
        parts.append("Die-cut or kiss-cut is a cut instruction. The PDF is the trim rectangle plus bleed.")
    return _join(parts)


def _fix_text(preset):
    notes = " ".join(preset.get("notes") or [])
    fixes = []
    if preset["name"] == "Giant Cheques":
        fixes.append("Parsed doubled apostrophes in 24'' x 48'' as 24 × 48 in.")
    if "was read from the product page" in notes:
        fixes.append("Read the page's up-to size range into the custom size hint.")
    return " ".join(fixes) if fixes else "—"


def _friction(preset, choice, safe_override):
    """Operator path: create, edit, upload, preflight, proof, PRINT_READY, press, finish."""
    name = preset["name"]
    lowered = name.lower()
    if preset.get("kind") == "service":
        return (
            "The service is disabled in the product menu, so it cannot become a job. "
            "No fields to fill and no dead end on Create."
        )
    fields = (
        "The new-job form has 20 fields (customer, product, size, unit, width, height, bleed, safe, "
        "quantity, sides, stock, finish, fold, due date, shape, grommets, binding, hardware, die-cut, confirm)."
    )
    if preset.get("kind") == "service":
        return fields
    notices = {
        "apparel": "The form shows that the garment is not produced. A decoration size can be stored. There is no print-ready step.",
        "drinkware": "The form shows that the item is not produced. A decoration size can be stored. There is no print-ready step.",
        "finishing-only": "The form says this is a finishing step, not a print file. Width and height stay blank, and Create waits until someone types a size the catalog never published.",
        "studio": "No size is published. The row is a studio booking, so there is nothing to preflight.",
        "booklet imposition": "The form says booklets are not imposed yet. Creating a 2-page job would not be the booklet.",
        "multi-page calendar": "The form says a 12-page calendar is not imposed. The listed sheet size would only be a single page.",
        "n-up labels": "The form says these sizes are one label and the sheet is not built.",
        "manufactured": "The form says this object is not manufactured. A face size can be stored, and there is no print-ready file for it.",
        "height-only flag": "The form says only a flag height is listed. Width and height stay blank. Nothing is invented.",
        "carbonless": "The form says a one-sheet PDF would not be the carbonless set.",
        "no published trim": "Width and height stay blank because the catalog published no trim. The operator is told to type them only when the order has them. Nothing is invented.",
    }
    if choice is None:
        kind_note = notices.get(_cause_for_notice(preset), notices["no published trim"])
        return f"{fields} Customer is the typed field. Due date is already two days out. {kind_note}"

    typed = ["customer"]
    gaps = []
    if not form_prefills_size(preset):
        typed.extend(["width", "height"])
        gaps.append("Width and height stay blank because the preset has no number, so the operator types the order size.")
    else:
        gaps.append(
            f"Size, sides, quantity, bleed, and safe are prefilled"
            f" ({_size_text(choice['width'], choice['height'], choice['unit'])}, "
            f"{'front only' if preset.get('sides') == [1] else 'front and back'})."
        )
    if not preset.get("stocks"):
        gaps.append("Stock says Shop stock because the preset lists none.")
    else:
        gaps.append(f"Stock is prefilled with {preset['stocks'][0]}.")
    if len(preset.get("folds") or []) > 1:
        gaps.append(
            "Fold stays none until the operator picks one. The form lists "
            + ", ".join(preset["folds"])
            + "."
        )
    elif len(preset.get("folds") or []) == 1:
        gaps.append(f"Fold is prefilled as {preset['folds'][0]}.")
    if len(preset.get("sizes") or []) > 1:
        gaps.append("Other preset sizes stay in the menu and are not selected.")
    if safe_override is not None:
        gaps.append(f"Safe zone is tightened to {safe_override} in on this small trim so the job can open.")
    slow = ""
    long_edge = max(_inches(choice["width"], choice["unit"]), _inches(choice["height"], choice["unit"]))
    if long_edge >= 36:
        slow = (
            f" This sheet is about {_trim(long_edge)} in on the long edge. "
            "The proof image is capped near 1400 pixels so the preview stays quick."
        )
    route = (
        " Upload starts the check with no extra click. Confirming bleed builds and verifies PRINT_READY. "
        "Proof approval stays a human click. On the press step an admin types the press, verifies it, and adds this stock "
        "without leaving the job. An operator can choose Proof only, with a note that an admin must verify the press. "
        "Readiness runs once when that step opens. The shop computer still has to be on. "
        "About 28 clicks from New job through packed when the preset fills the specs, and "
        f"{len(typed)} typed field(s): {', '.join(typed)}."
    )
    return fields + " " + " ".join(gaps) + slow + route


def _cause_for_notice(preset):
    decision = classify(preset)
    return decision.get("cause")


def preset_spec(preset, choice):
    bits = [preset.get("pipeline") or preset.get("kind") or ""]
    if preset.get("sizes"):
        shown = ", ".join(
            _size_text(size["width"], size["height"], size["unit"]) for size in preset["sizes"][:4]
        )
        extra = len(preset["sizes"]) - 4
        bits.append(f"sizes {shown}" + (f" (+{extra} more)" if extra > 0 else ""))
    custom = preset.get("customSize") or {}
    if custom.get("width_min") not in (None, "") and custom.get("height_min") not in (None, ""):
        bits.append(
            "custom "
            + _size_text(custom["width_min"], custom["height_min"], custom.get("unit") or "in")
            + " minimum"
        )
    if choice is not None:
        bits.append("job " + _size_text(choice["width"], choice["height"], choice["unit"]))
    if preset.get("stocks"):
        bits.append("stock " + preset["stocks"][0])
    if preset.get("finishes"):
        bits.append("finish " + preset["finishes"][0])
    sides = preset.get("sides") or [1, 2]
    bits.append("sides " + "/".join(str(side) for side in sides))
    return "; ".join(bits)


async def _prove_shop(preset, spec):
    raw = MemoryDB()
    shop_id = "shop-" + re.sub(r"[^a-z0-9-]", "", preset["id"])[:48]
    rival_id = shop_id + "-b"
    created = "2026-10-22T00:00:00+00:00"
    bundle = new_shop_records(
        shop_id=shop_id,
        name="Readiness Shop",
        slug="readiness-" + shop_id[-12:],
        email="owner@readiness.test",
        owner_name="Ada",
        owner_id="user-" + shop_id[-8:],
        password_hash="not-a-real-hash",
        created=created,
    )
    rival = new_shop_records(
        shop_id=rival_id,
        name="Rival Shop",
        slug="rival-" + shop_id[-12:],
        email="owner@readiness.test",
        owner_name="Bea",
        owner_id="user-b-" + shop_id[-6:],
        password_hash="not-a-real-hash",
        created=created,
    )
    await raw.shops.insert_one(bundle["shop"])
    await raw.shops.insert_one(rival["shop"])
    database = TenantDatabase(raw)
    job_id = "job-" + shop_id[-20:]
    with shop_scope(shop_id):
        await database.users.insert_one(bundle["user"])
        await database.settings.insert_one(bundle["settings"])
        for recipe in bundle["recipes"]:
            await database.recipes.insert_one(recipe)
        await database.jobs.insert_one({
            "id": job_id,
            "customer": "Readiness",
            "product": preset["id"],
            "spec": spec,
            "state": "active",
        })
        seen = await database.jobs.find_one({"id": job_id})
        if not seen or seen.get("shop_id") != shop_id:
            raise RuntimeError(f"{preset['name']} job was not stored in its shop")
    with shop_scope(rival_id):
        hidden = await database.jobs.find_one({"id": job_id})
        if hidden is not None:
            raise RuntimeError(f"{preset['name']} job was visible to another shop")


def evaluate_item(preset, items):
    decision = classify(preset)
    product = display_name(preset, items)
    category = preset.get("category") or "Other"
    if decision["action"] == "skip":
        return {
            "product": product,
            "category": category,
            "preset_spec": preset_spec(preset, None),
            "result": decision["result"],
            "reason": decision["reason"],
            "fix": _fix_text(preset),
            "friction": _friction(preset, None, None),
            "cause": decision["cause"],
        }
    choice = decision["choice"]
    payload, sides, safe_override = _payload(preset, choice)
    try:
        spec, recipe = resolve_spec(payload)
    except SpecError as error:
        return _row(preset, items, choice, "fail", error.message, "pipeline error", safe_override)
    if spec["sides"] != sides:
        return _row(preset, items, choice, "fail", "Resolved sides did not match the preset default.", "pipeline error", safe_override)
    outcome = _pipeline(recipe, spec["sides"])
    if not outcome["ok"]:
        return _row(preset, items, choice, "fail", outcome["detail"], "pipeline error", safe_override, spec=spec)
    return _row(
        preset,
        items,
        choice,
        "pass",
        _pass_reason(preset, choice, recipe, safe_override),
        "pass",
        safe_override,
        spec=spec,
    )


def _row(preset, items, choice, result, reason, cause, safe_override, spec=None):
    return {
        "product": display_name(preset, items),
        "category": preset.get("category") or "Other",
        "preset_spec": preset_spec(preset, choice),
        "result": result,
        "reason": reason,
        "fix": _fix_text(preset),
        "friction": _friction(preset, choice, safe_override),
        "cause": cause,
        "spec": spec,
    }


async def evaluate_all():
    previous = {key: os.environ.get(key) for key in ("SAAS_TENANT_ISOLATION", "SAAS_SIGNUP_ENABLED")}
    os.environ["SAAS_TENANT_ISOLATION"] = "on"
    os.environ["SAAS_SIGNUP_ENABLED"] = "true"
    try:
        if not signup_is_open():
            raise RuntimeError("Tenant signup did not open for the readiness shops.")
        items = catalog_items()
        rows = []
        for preset in items:
            row = evaluate_item(preset, items)
            if row["result"] == "pass":
                await _prove_shop(preset, row.get("spec") or {"product": preset["id"]})
            elif classify(preset)["action"] == "run":
                # A failed runnable item still has to prove the shop wall.
                await _prove_shop(preset, row.get("spec") or {"product": preset["id"]})
            else:
                await _prove_shop(preset, {"product": preset["id"], "note": row["result"]})
            row.pop("spec", None)
            rows.append(row)
        return rows
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def counts_for(rows):
    return dict(Counter(row["result"] for row in rows))


def grouped(rows, result):
    buckets = {}
    for row in rows:
        if row["result"] != result:
            continue
        buckets.setdefault(row["cause"], []).append(row["product"])
    return buckets


def _cell(value):
    return " ".join(str(value).replace("|", "/").split())


def render_markdown(rows):
    counts = counts_for(rows)
    order = ["pass", "fail", "unsupported", "n/a"]
    lines = [
        "# Product readiness",
        "",
        "Each of the 139 print2go.com catalog items was opened as a job inside its own shop, "
        "with tenant isolation on, and checked against the print-ready pipeline. "
        "Featured presets (Business card, Flyer, Custom product) are not part of the 139. "
        "A pass means a synthetic CMYK PDF at the preset size, with bleed, an embedded font, "
        "and a 300 dpi image, went through inspect, prepare, PRINT_READY, and verify. "
        "The same item also had to warn on RGB, block low dpi, and stop a trim-only file for a bleed decision.",
        "",
        "## Counts",
        "",
        "| Result | Count |",
        "| --- | --- |",
    ]
    for key in order:
        lines.append(f"| {key} | {counts.get(key, 0)} |")
    lines.append(f"| Total | {len(rows)} |")
    lines += [
        "",
        "## How this was checked",
        "",
        "For every catalog item the harness creates a shop with `new_shop_records`, stores the job through `TenantDatabase`, "
        "and reads it back from a second shop, which must see nothing. Runnable items call `resolve_spec` with the same defaults "
        "the new-job form uses, then `inspect`, `prepare`, `make_print_ready`, and `verify` in `backend/p2g/pdfcheck.py`. "
        "Those are the functions the job workflow calls. The harness does not import the API server.",
        "",
        "Shop artwork rules used on every job: 0.125 in bleed, 0.25 in safe zone (tightened only when the trim cannot hold it), "
        "CMYK, RGB policy warn, spot colour allowed, 300 dpi images, 1200 dpi raster text as a warning only.",
        "",
        "Negative cases, every runnable item: a trim-only PDF sets bleed to missing and does not error; "
        "an RGB PDF warns with DeviceRGB and says it is not converted; an image near 40 dpi errors with the 300 dpi minimum. "
        "PRINT_READY is built only for the good file.",
        "",
        "## Design guide",
        "",
        "Print2Go's published rules are the shop defaults: 1/8 in bleed, 1/4 in safe zone, CMYK with Pantone kept as spot, "
        "RGB warned and not rejected, 300 dpi images, 1200 dpi for raster text and logos, and JPG, JPEG, GIF, PNG, EPS, AI, PDF, PSD up to about 150 MB. "
        "The pipeline does not convert RGB to CMYK, does not separate a foil or spot-UV plate, and does not tell a logo from a photo, "
        "so 1200 dpi stays a warning.",
        "",
        "## What is still not built",
        "",
        "- Booklet and multi-page imposition. Sides stay 1 or 2.",
        "- N-up and step-and-repeat construction. A supplied sheet can pass. Myraana does not lay out the repeats.",
        "- RGB to CMYK conversion.",
        "- Manufactured goods, apparel, drinkware, and hardware.",
        "- MICR, numbering, and cheque imposition.",
        "- A connector that prints by itself. The press step stages a file after a person verifies the printer.",
        "",
        "## Fixes in this pass",
        "",
        "- Doubled apostrophe inch marks (`24'' x 48''`) now parse, so Giant Cheques is 24 × 48 in.",
        "- A page that says `1\" up to 60\"` now fills the custom size hint. Die-Cut Stickers uses that range.",
        "- Preflight errors and warnings say what is wrong and what to do next.",
        "- Upload starts the artwork check. Confirming bleed, or accepting a blank border, builds and verifies PRINT_READY.",
        "- The press step verifies a printer and adds the job stock inline. An operator who cannot do that can choose Proof only.",
        "- Production route stays disabled until a verified printer and the job stock are in place, so the step does not end on an error with nowhere to go.",
        "- New jobs prefill size, sides, quantity, stock, finish, bleed, safe, due date (two days out), die-cut, a named shape, and a single binding, hardware, or grommet count.",
        "- Datalists list that product's options, not the whole catalog.",
        "- Proof images cap the long edge near 1400 pixels.",
        "- Apparel, drinkware, finishing, manufactured goods, booklets, label sheets, carbonless sets, and height-only flags say so on the form.",
        "- Quality-check labels are plain language. Readiness checks once and says how to fix a missing printer or a stopped connector.",
        "",
        "## Top friction",
        "",
        "1. Preset specs were empty until someone retyped them. Size, sides, quantity, stock, finish, bleed, safe, and the due date now start filled when the catalog has a number.",
        "2. Preflight text named PDF internals and stopped. Messages now include the fix (export, move, replace, flatten, embed).",
        "3. The press step blocked when no printer was verified, and the fix lived on another screen. An admin verifies the press and adds the stock on the job. An operator gets Proof only, with a sentence that says an admin must verify the press.",
        "4. Upload and bleed confirmation each needed extra clicks for checks that had no decision. Those steps advance on their own. Proof approval does not.",
        "5. A large sheet rendered a full-resolution preview. The long edge is capped near 1400 pixels.",
        "6. Still manual, on purpose: the customer name, a fold when several are offered, width and height when the catalog published none, proof approval, and the physical print.",
        "",
        "## Unsupported and n/a by cause",
        "",
    ]
    for result in ("unsupported", "n/a", "fail"):
        buckets = grouped(rows, result)
        if not buckets:
            lines.append(f"No {result} rows.")
            lines.append("")
            continue
        lines.append(f"### {result}")
        lines.append("")
        for cause, names in sorted(buckets.items()):
            lines.append(f"- **{cause}** ({len(names)}): " + "; ".join(names))
        lines.append("")
    lines += [
        "## Results",
        "",
        "| Product | Category | Preset spec | Result | Reason | Fix | Friction |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                _cell(row[key])
                for key in ("product", "category", "preset_spec", "result", "reason", "fix", "friction")
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def render_csv(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["product", "category", "preset_spec", "result", "reason", "fix", "friction"],
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row[key] for key in writer.fieldnames})
    return buffer.getvalue()


def write_docs(rows, root):
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(rows)
    csv_text = render_csv(rows)
    (docs / "PRODUCT_READINESS.md").write_text(markdown, encoding="utf-8")
    (docs / "PRODUCT_READINESS.csv").write_text(csv_text, encoding="utf-8")
    return markdown, csv_text
