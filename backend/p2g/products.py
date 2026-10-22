"""Resolve a job spec into the inch-based recipe the PDF pipeline already uses.

Shop artwork rules supply bleed, safe zone, DPI and colour policy.
A catalog preset only prefills. Explicit job fields always win.
"""
from p2g.catalog_seed import SpecError, load_presets


FOLD_LABELS = {
    "none": "No fold.",
    "half": "Finish with a half fold.",
    "tri": "Finish with a tri-fold.",
    "z": "Finish with a Z-fold.",
    "gate": "Finish with a gate fold.",
    "accordion": "Finish with an accordion fold.",
}

UNIT_TO_INCH = {"in": 1, "mm": 1 / 25.4, "cm": 1 / 2.54, "ft": 12}
# Finished size is capped so a bad catalog value (one poster page lists 1200 inches)
# cannot request an unbounded PDF. The raw catalog range is still stored on the preset.
MAX_INCHES = 150


def default_artwork_rules():
    """Print2Go design guide and FAQ. Other shops edit these in settings."""
    return {
        "bleedInches": 0.125,
        "safeInches": 0.25,
        "colourMode": "CMYK",
        "rgbPolicy": "warn",
        "allowSpotColours": True,
        "imageDpi": 300,
        "rasterTextDpi": 1200,
        "outputDpi": 300,
        "acceptedTypes": ["jpg", "jpeg", "gif", "png", "eps", "ai", "pdf", "psd"],
        "maxUploadBytes": 150_000_000,
    }


def normalize_artwork_rules(payload):
    base = default_artwork_rules()
    if not isinstance(payload, dict):
        raise SpecError("Artwork rules must be an object.")
    data = dict(base)
    data["bleedInches"] = _bounded(payload.get("bleedInches", base["bleedInches"]), "Bleed", 0, 1)
    data["safeInches"] = _bounded(payload.get("safeInches", base["safeInches"]), "Safe zone", 0, 1)
    data["imageDpi"] = int(_bounded(payload.get("imageDpi", base["imageDpi"]), "Image DPI", 72, 1200))
    data["rasterTextDpi"] = int(
        _bounded(payload.get("rasterTextDpi", base["rasterTextDpi"]), "Raster text DPI", 72, 2400)
    )
    data["outputDpi"] = int(_bounded(payload.get("outputDpi", base["outputDpi"]), "Output DPI", 72, 1200))
    if data["rasterTextDpi"] < data["imageDpi"]:
        raise SpecError("Raster text DPI cannot be lower than the image DPI.")
    colour = str(payload.get("colourMode", base["colourMode"]) or "").upper()
    if colour not in {"CMYK", "RGB", "ANY"}:
        raise SpecError("Colour mode must be CMYK, RGB, or ANY.")
    policy = str(payload.get("rgbPolicy", base["rgbPolicy"]) or "").lower()
    if policy not in {"warn", "reject"}:
        raise SpecError("RGB policy must be warn or reject.")
    types = payload.get("acceptedTypes", base["acceptedTypes"])
    allowed = set(base["acceptedTypes"])
    if not isinstance(types, list) or not types or any(item not in allowed for item in types):
        raise SpecError("Accepted file types must be chosen from JPG, PNG, GIF, EPS, AI, PDF and PSD.")
    data["colourMode"] = colour
    data["rgbPolicy"] = policy
    data["acceptedTypes"] = [item for item in base["acceptedTypes"] if item in types]
    data["allowSpotColours"] = bool(payload.get("allowSpotColours", True))
    megabytes = payload.get("maxUploadMb", data["maxUploadBytes"] / 1_000_000)
    data["maxUploadBytes"] = int(_bounded(megabytes, "Max upload", 1, 150) * 1_000_000)
    return data


def artwork_rules_from_settings(settings):
    raw = (settings or {}).get("artworkRules")
    if not raw:
        return default_artwork_rules()
    try:
        return normalize_artwork_rules(raw)
    except SpecError:
        return default_artwork_rules()


def public_catalog():
    loaded = load_presets()
    return {
        "source": loaded["source"],
        "crawled": loaded["crawled"],
        "report": loaded["report"],
        "vocabulary": loaded["vocabulary"],
        "artworkDefaults": default_artwork_rules(),
        "presets": loaded["presets"],
    }


def preset_by_id(preset_id):
    for item in load_presets()["presets"]:
        if item["id"] == preset_id:
            return item
    return None


def resolve_spec(payload, rules=None, recipe_doc=None):
    """Return (customer spec in entered units, inch recipe for pdfcheck)."""
    payload = payload or {}
    rules = rules or default_artwork_rules()
    preset_id = str(payload.get("product") or payload.get("presetId") or "business-card")
    preset = preset_by_id(preset_id)
    if preset is None:
        raise SpecError("Choose a catalog preset or Custom product.")
    if preset["kind"] == "service":
        raise SpecError(f"{preset['name']} is a service, not a print job. Choose a print product or Custom product.")
    size = _selected_size(preset, payload)
    if payload.get("width") in (None, "") and size is not None:
        unit = _unit(size.get("unit") or "in")
    else:
        unit = _unit(payload.get("unit") or (size or {}).get("unit") or "in")
    width = _dimension(payload.get("width"), (size or {}).get("width"), unit, "Width")
    height = _dimension(payload.get("height"), (size or {}).get("height"), unit, "Height")
    if width is None or height is None:
        if recipe_doc and recipe_doc.get("width") and recipe_doc.get("height") and not payload.get("sizeId"):
            width = float(recipe_doc["width"])
            height = float(recipe_doc["height"])
            unit = "in"
        else:
            raise SpecError("Enter a finished width and height, or choose a preset size.")
    _fit(width, height, unit)
    bleed = _rule_length(payload.get("bleed"), rules["bleedInches"], "Bleed")
    safe = _rule_length(payload.get("safe"), rules["safeInches"], "Safe zone")
    width_in, height_in = _inches(width, unit), _inches(height, unit)
    bleed_in, safe_in = _inches(bleed, "in"), _inches(safe, "in")
    if safe_in * 2 >= min(width_in, height_in):
        raise SpecError("Safe zone must fit inside the finished size.")
    if payload.get("minDpi") not in (None, ""):
        min_dpi = int(_bounded(payload.get("minDpi"), "Image DPI", 72, 1200))
    else:
        min_dpi = int(rules["imageDpi"])
    try:
        sides = int(payload.get("sides") if payload.get("sides") not in (None, "") else 2)
    except (TypeError, ValueError) as error:
        raise SpecError("Sides must be 1 or 2.") from error
    if sides not in {1, 2}:
        raise SpecError("Sides must be 1 or 2. Multi-page imposition is not generated yet.")
    options = _options(payload.get("options") or {}, preset)
    if str(payload.get("orientation") or "").lower() == "horizontal":
        width, height = height, width
        width_in, height_in = height_in, width_in
    stock = str(payload.get("stock") or _first(preset.get("stocks")) or "Shop stock").strip()
    finish = str(payload.get("finish") or _first(preset.get("finishes")) or "Shop finish").strip()
    if not 1 <= len(stock) <= 120 or not 1 <= len(finish) <= 120:
        raise SpecError("Stock and finish must be between 1 and 120 characters.")
    spec = {
        "product": preset["id"],
        "productName": preset["name"],
        "sizeId": (size or {}).get("id") or "custom",
        "width": width,
        "height": height,
        "unit": unit,
        "bleed": bleed,
        "safe": safe,
        "minDpi": min_dpi,
        "sides": sides,
        "stock": stock,
        "finish": finish,
        "colourMode": rules["colourMode"],
        "options": options,
    }
    version = int((recipe_doc or {}).get("version") or 1)
    recipe = {
        "id": preset["id"],
        "product": preset["id"],
        "version": version,
        "name": preset["name"],
        "width": round(width_in, 4),
        "height": round(height_in, 4),
        "bleed": round(bleed_in, 4),
        "safe": round(safe_in, 4),
        "minDpi": min_dpi,
        "rasterTextDpi": int(rules["rasterTextDpi"]),
        "outputDpi": int(rules["outputDpi"]),
        "colourMode": rules["colourMode"],
        "rgbPolicy": rules["rgbPolicy"],
        "allowSpotColours": rules["allowSpotColours"],
        "maxPages": 2,
        "unit": "in",
        "displayUnit": unit,
        "cutInstructions": cut_instructions(spec),
    }
    return spec, recipe


def cut_instructions(spec):
    fold = spec["options"].get("fold") or "none"
    parts = [
        f"Cut to {_trim_num(spec['width'])} × {_trim_num(spec['height'])} {spec['unit']} using the verified trim box.",
        FOLD_LABELS.get(fold, f"Finish with fold: {fold}."),
    ]
    shape = spec["options"].get("shape")
    if shape and shape.lower() not in {"rectangle", "square or rectangle"}:
        parts.append(f"Shape: {shape}.")
    if spec["options"].get("dieCut"):
        parts.append("Die-cut as specified.")
    grommets = spec["options"].get("grommets") or 0
    if grommets:
        parts.append(f"{grommets} grommets.")
    if spec["options"].get("binding"):
        parts.append(f"Binding: {spec['options']['binding']}.")
    if spec["options"].get("hardware"):
        parts.append(f"Hardware: {spec['options']['hardware']}.")
    return " ".join(parts)


def _options(raw, preset):
    if not isinstance(raw, dict):
        raise SpecError("Product options must be an object.")
    fold = str(raw.get("fold") or "none").strip().lower()
    if fold in {"half-fold", "halffold"}:
        fold = "half"
    if fold in {"tri-fold", "trifold"}:
        fold = "tri"
    if not fold:
        fold = "none"
    if len(fold) > 40:
        raise SpecError("Fold name is too long.")
    shape = str(raw.get("shape") or "rectangle").strip()
    binding = str(raw.get("binding") or "").strip()
    hardware = str(raw.get("hardware") or "").strip()
    for label, value in (("Shape", shape), ("Binding", binding), ("Hardware", hardware)):
        if len(value) > 140:
            raise SpecError(f"{label} is too long.")
    try:
        grommets = int(raw.get("grommets") or 0)
    except (TypeError, ValueError) as error:
        raise SpecError("Grommets must be a whole number.") from error
    if not 0 <= grommets <= 100:
        raise SpecError("Grommets must be between 0 and 100.")
    die_cut = raw.get("dieCut")
    return {
        "fold": fold,
        "shape": shape or "rectangle",
        "dieCut": bool(die_cut),
        "grommets": grommets,
        "binding": binding,
        "hardware": hardware,
    }


def _selected_size(preset, payload):
    size_id = payload.get("sizeId")
    if size_id in (None, "", "custom"):
        return None
    for size in preset.get("sizes") or []:
        if size["id"] == size_id:
            return size
    raise SpecError("That preset size is not on this product.")


def _unit(value):
    value = str(value or "in").lower()
    aliases = {"inch": "in", "inches": "in", '"': "in", "feet": "ft", "foot": "ft"}
    value = aliases.get(value, value)
    if value not in UNIT_TO_INCH:
        raise SpecError("Unit must be in, mm, cm, or ft.")
    return value


def _dimension(explicit, fallback, unit, label):
    if explicit in (None, ""):
        if fallback in (None, ""):
            return None
        return _bounded_for_unit(fallback, unit, label)
    return _bounded_for_unit(explicit, unit, label)


def _bounded_for_unit(value, unit, label):
    number = _bounded(value, label, 0.05, 2000)
    inches = number * UNIT_TO_INCH[unit]
    if not 0.4 <= inches <= MAX_INCHES:
        raise SpecError(f"{label} must be between 0.4 and {MAX_INCHES} inches after unit conversion.")
    return number


def _rule_length(explicit, fallback, label):
    if explicit in (None, ""):
        return float(fallback)
    return _bounded(explicit, label, 0, 1)


def _inches(value, unit):
    return float(value) * UNIT_TO_INCH[unit]


def _fit(width, height, unit):
    _bounded_for_unit(width, unit, "Width")
    _bounded_for_unit(height, unit, "Height")


def _bounded(value, label, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise SpecError(f"{label} must be a number.") from error
    if not low <= number <= high:
        raise SpecError(f"{label} must be between {low} and {high}.")
    return number


def _first(values):
    return values[0] if values else ""


def _trim_num(value):
    return f"{float(value):.3f}".rstrip("0").rstrip(".")
