"""Turn the Print2Go.com catalog into job presets.

Presets prefill a job. They are not a limit on what a shop can make.
Sizes that do not parse stay on the preset as notes, and the job form
still accepts a custom size.
"""
import json
import re
from pathlib import Path


CATALOG_PATH = Path(__file__).with_name("data") / "print2go_catalog.json"

_FRACTIONS = {
    "½": 0.5,
    "¼": 0.25,
    "¾": 0.75,
    "⅛": 0.125,
    "⅜": 0.375,
    "⅝": 0.625,
    "⅞": 0.875,
    "⅓": 1 / 3,
    "⅔": 2 / 3,
}
_NUM = r"(?:\d+\s+\d+/\d+|\d+-\d+/\d+|\d+/\d+|\d+(?:\.\d+)?[½¼¾⅛⅜⅝⅞⅓⅔]?|[½¼¾⅛⅜⅝⅞⅓⅔])"
_PAIR = re.compile(
    rf"(?P<a>{_NUM})\s*(?P<ua>ft|feet|cm|mm|in(?:ch(?:es)?)?|[\"″'])?\s*[x×]\s*"
    rf"(?P<b>{_NUM})\s*(?P<ub>ft|feet|cm|mm|in(?:ch(?:es)?)?|[\"″'])?",
    re.IGNORECASE,
)
_CIRCLE = re.compile(rf"(?P<a>{_NUM})\s*(?:[\"″'])?\s*circle", re.IGNORECASE)
_FOLD_MAP = {
    "half fold": "half",
    "half-fold": "half",
    "tri-fold": "tri",
    "trifold": "tri",
    "z-fold": "z",
    "z fold": "z",
    "gate fold": "gate",
    "accordion fold": "accordion",
}
_IGNORE = {"yes", "none", "select option", "unknown", "standard"}


class SpecError(ValueError):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _number(token):
    token = token.strip()
    mixed = re.fullmatch(r"(\d+)[\s-](\d+)/(\d+)", token)
    if mixed:
        return float(mixed.group(1)) + float(mixed.group(2)) / float(mixed.group(3))
    ratio = re.fullmatch(r"(\d+)/(\d+)", token)
    if ratio:
        return float(ratio.group(1)) / float(ratio.group(2))
    for mark, value in _FRACTIONS.items():
        if token == mark:
            return value
        if token.endswith(mark):
            head = token[: -len(mark)]
            try:
                return float(head) + value
            except ValueError:
                return None
    try:
        return float(token)
    except ValueError:
        return None


def _unit(token):
    token = (token or "").lower()
    if token in {"ft", "feet"}:
        return "ft"
    if token == "cm":
        return "cm"
    if token == "mm":
        return "mm"
    if token in {"in", "inch", "inches", '"', "″", "'"}:
        return "in"
    return None


def _trim(value):
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _normalize_size_text(raw):
    text = str(raw or "").strip()
    text = text.replace("”", '"').replace("“", '"').replace("″", '"').replace("′", "'")
    # Some pages encode an inch mark as two apostrophes: 24'' x 48''.
    text = text.replace("''", '"')
    return re.sub(r"(\d)\.(?=[x×])", r"\1", text)


_UP_TO = re.compile(
    rf"(?P<a>{_NUM})\s*(?P<ua>ft|feet|cm|mm|in(?:ch(?:es)?)?|[\"'])?\s+up to\s+"
    rf"(?P<b>{_NUM})\s*(?P<ub>ft|feet|cm|mm|in(?:ch(?:es)?)?|[\"'])?",
    re.IGNORECASE,
)


def parse_size_range(texts):
    """Read a single '1 in up to 60 in' range when the page has no width × height."""
    for raw in texts or []:
        match = _UP_TO.search(_normalize_size_text(raw))
        if not match:
            continue
        low, high = _number(match.group("a")), _number(match.group("b"))
        if not low or not high or low <= 0 or high < low:
            continue
        unit = _unit(match.group("ub")) or _unit(match.group("ua")) or "in"
        return {
            "unit": unit,
            "width_min": low,
            "width_max": high,
            "height_min": low,
            "height_max": high,
        }
    return None


def parse_sizes(texts, category=None):
    """Return parsed sizes and the strings that did not parse."""
    found, skipped = [], []
    for raw in texts or []:
        text = _normalize_size_text(raw)
        if not text or text.lower() == "unknown":
            continue
        pairs = list(_PAIR.finditer(text))
        if not pairs:
            if parse_size_range([text]):
                continue
            circle = _CIRCLE.search(text)
            if circle:
                size = _number(circle.group("a"))
                if size and size > 0:
                    found.append(_size(size, size, "in", text, shape="circle"))
                    continue
            skipped.append(text)
            continue
        for match in pairs:
            width, height = _number(match.group("a")), _number(match.group("b"))
            if not width or not height or width <= 0 or height <= 0:
                skipped.append(text)
                continue
            unit = _unit(match.group("ub")) or _unit(match.group("ua")) or "in"
            if category == "Business Cards" and unit == "in" and {round(width, 3), round(height, 3)} == {2.0, 3.5}:
                width, height = 3.5, 2.0
                text = "3.5 × 2 in"
            found.append(_size(width, height, unit, text))
    unique = []
    seen = set()
    for item in found:
        key = (item["unit"], round(item["width"], 3), round(item["height"], 3))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique, skipped


def _size(width, height, unit, label, shape=None):
    item = {
        "id": f"{_trim(width)}x{_trim(height)}-{unit}",
        "label": label.strip(),
        "width": round(width, 4),
        "height": round(height, 4),
        "unit": unit,
    }
    if shape:
        item["shape"] = shape
    return item


def _values(spec_value):
    if not isinstance(spec_value, dict):
        return []
    values = []
    for option in spec_value.get("options") or []:
        values.extend(option.get("values") or [])
    cleaned = []
    for value in values:
        text = str(value or "").strip()
        if not text or text.lower() in _IGNORE or "free text" in text.lower():
            continue
        if len(text) > 140:
            continue
        cleaned.append(text)
    return list(dict.fromkeys(cleaned))


def _folds(spec_value):
    folds = []
    for value in _values(spec_value):
        key = _FOLD_MAP.get(value.lower())
        if key and key not in folds:
            folds.append(key)
    return folds


def _sides(spec_value):
    text = " ".join(_values(spec_value)).lower()
    sides = set()
    if any(token in text for token in ("front & back", "front and back", "both", "double")):
        sides.update({1, 2})
    if any(token in text for token in ("front only", "single", "outside only")):
        sides.add(1)
    if "front" in text and "back" not in text:
        sides.add(1)
    return sorted(sides) or [1, 2]


def _custom_range(item, calculators):
    url = (item.get("url") or "").rstrip("/")
    for calculator in calculators:
        if (calculator.get("url") or "").rstrip("/") != url:
            continue
        unit = {"inch": "in", "ft": "ft", "mm": "mm", "cm": "cm"}.get(
            str(calculator.get("unit") or "").lower(), "in"
        )
        numbers = {}
        for key in ("width_min", "width_max", "height_min", "height_max"):
            raw = calculator.get(key)
            try:
                numbers[key] = float(raw) if raw not in (None, "") else None
            except (TypeError, ValueError):
                numbers[key] = None
        if not any(value is not None for value in numbers.values()):
            return None
        return {"unit": unit, **numbers}
    return None


def _slug(item):
    name = re.sub(r"[^a-z0-9]+", "-", item["name"].lower()).strip("-")
    suffix = item.get("product_id") or item.get("url", "").rstrip("/").split("/")[-1]
    return f"{name}-{suffix}"[:90]


def _pipeline(item, sizes, custom):
    if item.get("type") == "service":
        return "service"
    if sizes or custom:
        return "print-ready"
    return "custom"


def build_presets(catalog):
    calculators = catalog.get("custom_options", {}).get("custom_size_calculators") or []
    presets = []
    for item in catalog.get("products") or []:
        specs = item.get("specs") or {}
        size_text = []
        sizes_field = specs.get("sizes")
        if isinstance(sizes_field, dict):
            size_text.extend(sizes_field.get("preset_options") or [])
            size_text.extend(sizes_field.get("page_text") or [])
        sizes, skipped = parse_sizes(size_text, item.get("category"))
        custom = _custom_range(item, calculators)
        notes = []
        if custom is None:
            ranged = parse_size_range(size_text)
            if ranged:
                custom = ranged
                notes.append(
                    "Custom size "
                    f"{ranged['width_min']}–{ranged['width_max']} {ranged['unit']} "
                    "was read from the product page."
                )
        for key, value in specs.items():
            if value == "unknown":
                notes.append(f"{key.replace('_', ' ')}: not shown on print2go.com")
        if skipped:
            notes.append("Unparsed size text: " + "; ".join(skipped[:4]))
        presets.append(
            {
                "id": _slug(item),
                "sourceId": item.get("product_id"),
                "name": item["name"],
                "category": item.get("category") or "Other",
                "subcategory": item.get("subcategory"),
                "url": item.get("url"),
                "kind": item.get("type") or "product",
                "pipeline": _pipeline(item, sizes, custom),
                "summary": " ".join(item.get("overview") or [])[:240],
                "sizes": sizes,
                "customSize": custom,
                "stocks": _values(specs.get("stocks_materials")),
                "finishes": _values(specs.get("finishes_coatings")),
                "sides": _sides(specs.get("sides")),
                "folds": _folds(specs.get("folding")),
                "shapes": _values(specs.get("die_cut_shape")),
                "binding": _values(specs.get("binding")),
                "hardware": _values(specs.get("grommets_hardware")),
                "quantities": (specs.get("quantity") or {}).get("values")
                if isinstance(specs.get("quantity"), dict)
                else [],
                "notes": notes,
                "priority": False,
                "tested": False,
            }
        )
    presets.insert(0, _custom_preset())
    presets.insert(0, _flyer_preset(presets))
    presets.insert(0, _card_preset(presets))
    return presets


def _unique_sizes(presets):
    found, seen = [], set()
    for preset in presets:
        for size in preset.get("sizes") or []:
            key = (size["unit"], round(size["width"], 3), round(size["height"], 3))
            if key in seen:
                continue
            seen.add(key)
            found.append(dict(size))
    return found


def _card_preset(presets):
    cards = [item for item in presets if item["category"] == "Business Cards"]
    sizes = _unique_sizes(cards)
    if not any(size["width"] == 3.5 and size["height"] == 2 and size["unit"] == "in" for size in sizes):
        sizes.insert(0, {"id": "3.5x2-in", "label": "US standard 3.5 × 2 in", "width": 3.5, "height": 2, "unit": "in"})
    return {
        "id": "business-card",
        "sourceId": None,
        "name": "Business card",
        "category": "Business Cards",
        "subcategory": "Preset",
        "url": "https://print2go.com/standard-business-cards/",
        "kind": "product",
        "pipeline": "print-ready",
        "summary": "US and shaped cards. Sizes, stocks and finishes come from the Print2Go card pages and can be overridden.",
        "sizes": sizes,
        "customSize": {"unit": "in", "width_min": 1, "width_max": 5, "height_min": 1, "height_max": 5},
        "stocks": sorted({stock for item in cards for stock in item["stocks"]}) or ["14pt", "16pt"],
        "finishes": sorted({finish for item in cards for finish in item["finishes"]}) or ["Matte"],
        "sides": [1, 2],
        "folds": [],
        "shapes": sorted({shape for item in cards for shape in item["shapes"]}) or ["Square", "Round - All 4 Corner"],
        "binding": [],
        "hardware": [],
        "quantities": ["100", "250", "500", "1000"],
        "notes": ["Folding is not used on the card pages. A fold can still be added on the job."],
        "priority": True,
        "tested": True,
    }


def _flyer_preset(presets):
    flyer = next(item for item in presets if item["name"] == "Flyers")
    sizes = list(flyer["sizes"])
    wanted = [
        (4, 6, "4 × 6 in"),
        (5, 7, "5 × 7 in"),
        (5.5, 8.5, "5.5 × 8.5 in"),
        (8.5, 11, "US Letter 8.5 × 11 in"),
    ]
    for width, height, label in wanted:
        if not any(abs(size["width"] - width) < 0.02 and abs(size["height"] - height) < 0.02 for size in sizes):
            sizes.append({"id": f"{width}x{height}-in", "label": label, "width": width, "height": height, "unit": "in"})
    return {
        "id": "flyer",
        "sourceId": flyer.get("sourceId"),
        "name": "Flyer",
        "category": "Marketing & Business",
        "subcategory": "Marketing Material",
        "url": flyer.get("url"),
        "kind": "product",
        "pipeline": "print-ready",
        "summary": "Common flyer sizes from print2go.com/flyers, plus a custom size and an optional fold.",
        "sizes": sizes,
        "customSize": {"unit": "in", "width_min": 3, "width_max": 17, "height_min": 3, "height_max": 17},
        "stocks": flyer["stocks"] or ["100lb Gloss Text"],
        "finishes": flyer["finishes"] or ["Gloss"],
        "sides": [1, 2],
        "folds": ["half", "tri", "z", "gate", "accordion"],
        "shapes": flyer["shapes"],
        "binding": [],
        "hardware": [],
        "quantities": flyer["quantities"] or ["25", "50", "100", "250", "500"],
        "notes": [
            "The flyer page does not list folds. Half, tri, Z, gate and accordion are optional finishing, also seen on menus.",
            "Custom size is offered on the flyer page without a numeric calculator.",
        ],
        "priority": True,
        "tested": True,
    }


def _custom_preset():
    return {
        "id": "custom",
        "sourceId": None,
        "name": "Custom product",
        "category": "Custom",
        "subcategory": None,
        "url": None,
        "kind": "product",
        "pipeline": "print-ready",
        "summary": "Any finished size and options. Use this when the job is not one of the catalog presets.",
        "sizes": [],
        "customSize": {"unit": "in", "width_min": 0.5, "width_max": 150, "height_min": 0.5, "height_max": 150},
        "stocks": [],
        "finishes": [],
        "sides": [1, 2],
        "folds": ["half", "tri", "z", "gate", "accordion"],
        "shapes": [],
        "binding": [],
        "hardware": [],
        "quantities": [],
        "notes": ["Catalog presets are starting points. This job stores the specs you enter."],
        "priority": True,
        "tested": False,
    }


def vocabulary(presets):
    def gather(key):
        values = []
        for preset in presets:
            for value in preset.get(key) or []:
                if value not in values:
                    values.append(value)
        return values

    return {
        "folds": [
            {"id": "none", "label": "No fold"},
            {"id": "half", "label": "Half fold"},
            {"id": "tri", "label": "Tri-fold"},
            {"id": "z", "label": "Z-fold"},
            {"id": "gate", "label": "Gate fold"},
            {"id": "accordion", "label": "Accordion fold"},
        ],
        "stocks": gather("stocks"),
        "finishes": gather("finishes"),
        "shapes": gather("shapes"),
        "binding": gather("binding"),
        "hardware": gather("hardware"),
    }


def catalog_report(presets):
    products = [item for item in presets if item["id"] not in {"business-card", "flyer", "custom"}]
    return {
        "catalogItems": len(products),
        "printProducts": sum(1 for item in products if item["kind"] == "product"),
        "services": sum(1 for item in products if item["kind"] == "service"),
        "printReadyPresets": sum(1 for item in products if item["pipeline"] == "print-ready"),
        "customOnly": sum(1 for item in products if item["pipeline"] == "custom"),
        "testedPresets": [item["id"] for item in presets if item.get("tested")],
    }


_CACHE = None


def load_presets():
    global _CACHE
    if _CACHE is None:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        presets = build_presets(catalog)
        _CACHE = {
            "crawled": catalog.get("meta", {}).get("crawled"),
            "source": "https://print2go.com",
            "report": catalog_report(presets),
            "vocabulary": vocabulary(presets),
            "presets": presets,
        }
    return _CACHE
