"""Catalog presets, custom specs, shop artwork rules, and print-ready output."""
import hashlib
import io

from PIL import Image
from reportlab.pdfgen import canvas

from p2g.catalog_seed import load_presets, parse_sizes
from p2g.pdfcheck import inspect, make_print_ready, prepare, verify
from p2g.present import reset_result, status_label
from p2g.printers import filter_printers, is_virtual_printer
from p2g.products import (
    SpecError,
    default_artwork_rules,
    normalize_artwork_rules,
    resolve_spec,
)
from p2g.review import review_headline
from p2g.uploads import classify_upload, prepare_artwork
from p2g.billing import billing_status
from p2g.public_forms import signup_result


def artwork(width, height, pages=1, text=None, low_resolution=False):
    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=(width * 72, height * 72))
    for _ in range(pages):
        document.setFillColorRGB(0.1, 0.2, 0.5)
        document.rect(0, 0, width * 72, height * 72, fill=1, stroke=0)
        if text:
            document.setFillColorRGB(1, 1, 1)
            document.drawString(text[0], text[1], text[2])
        if low_resolution:
            image = Image.new("RGB", (40, 40), "red")
            handle = io.BytesIO()
            image.save(handle, format="PNG")
            from reportlab.lib.utils import ImageReader

            document.drawImage(ImageReader(handle), 20, 20, width=3 * 72, height=2 * 72)
        document.showPage()
    document.save()
    return output.getvalue()


def round_trip(recipe, pages, text=None):
    media_w = recipe["width"] + 2 * recipe["bleed"]
    media_h = recipe["height"] + 2 * recipe["bleed"]
    original = artwork(media_w, media_h, pages=pages, text=text)
    report = inspect(original, recipe, pages)
    assert report["errors"] == [], report["errors"]
    ready = make_print_ready(prepare(original, recipe, False), recipe, "job-test", 1)
    checked = verify(ready, recipe, pages, hashlib.sha256(ready).hexdigest())
    assert checked["errors"] == [], checked["errors"]
    return report


def test_catalog_counts_and_priority_presets():
    loaded = load_presets()
    report = loaded["report"]
    assert report["catalogItems"] == 139
    assert report["printProducts"] == 134
    assert report["services"] == 5
    assert report["printReadyPresets"] > 90
    assert "business-card" in report["testedPresets"]
    assert "flyer" in report["testedPresets"]
    flyer = next(item for item in loaded["presets"] if item["id"] == "flyer")
    labels = " ".join(size["label"] for size in flyer["sizes"])
    assert "8.5" in labels and "11" in labels
    assert "half" in flyer["folds"]
    card = next(item for item in loaded["presets"] if item["id"] == "business-card")
    assert any(size["width"] == 3.5 and size["height"] == 2 for size in card["sizes"])
    assert any(size["width"] == 2.5 and size["height"] == 2.5 for size in card["sizes"])


def test_doubled_inch_marks_and_page_ranges_parse():
    from p2g.catalog_seed import parse_size_range

    sizes, skipped = parse_sizes(["24'' x 48''"])
    assert not skipped
    assert sizes[0]["width"] == 24 and sizes[0]["height"] == 48 and sizes[0]["unit"] == "in"
    ranged = parse_size_range(['Size Range: 1" up to 60"'])
    assert ranged["width_min"] == 1 and ranged["width_max"] == 60 and ranged["unit"] == "in"
    die = next(item for item in load_presets()["presets"] if item["name"] == "Die-Cut Stickers")
    assert die["customSize"]["width_min"] == 1 and die["customSize"]["width_max"] == 60
    giant = next(item for item in load_presets()["presets"] if item["name"] == "Giant Cheques")
    assert any(size["width"] == 24 and size["height"] == 48 for size in giant["sizes"])


def test_curly_quotes_and_circle_sizes_parse():
    sizes, skipped = parse_sizes(['Standard Size: 5.5” x 8.5” or 8.5” x 11”', "1” Circle - 48 Labels / Sheet"])
    assert not skipped
    assert (5.5, 8.5) in {(item["width"], item["height"]) for item in sizes}
    assert any(item.get("shape") == "circle" and item["width"] == 1 for item in sizes)


def test_services_cannot_become_print_jobs():
    service = next(item for item in load_presets()["presets"] if item["kind"] == "service")
    try:
        resolve_spec({"product": service["id"], "width": 8.5, "height": 11, "unit": "in"})
    except SpecError as error:
        assert "service" in error.message
    else:
        raise AssertionError("a service was accepted as a print job")


def test_custom_millimetre_size_is_not_limited_to_the_catalog():
    spec, recipe = resolve_spec(
        {
            "product": "custom",
            "width": 210,
            "height": 99,
            "unit": "mm",
            "sides": 1,
            "stock": "Custom vinyl",
            "finish": "Matte",
            "options": {"fold": "none", "grommets": 4, "hardware": "Pole pocket"},
        }
    )
    assert abs(recipe["width"] - 210 / 25.4) < 0.01
    assert spec["unit"] == "mm"
    assert "4 grommets" in recipe["cutInstructions"]
    assert recipe["safe"] == 0.25
    assert recipe["bleed"] == 0.125
    assert recipe["rgbPolicy"] == "warn"


def test_flyer_letter_and_custom_and_fold_round_trip():
    rules = default_artwork_rules()
    for payload in (
        {"product": "flyer", "sizeId": "8.5x11-in", "sides": 2, "options": {"fold": "half"}},
        {"product": "flyer", "width": 7.25, "height": 9.5, "unit": "in", "sides": 1, "options": {"fold": "tri"}},
        {"product": "business-card", "sizeId": "3.5x2-in", "sides": 2},
    ):
        spec, recipe = resolve_spec(payload, rules)
        report = round_trip(recipe, spec["sides"])
        assert any(item["name"] == "colour" and item["status"] == "warn" for item in report["artworkChecks"])
        if payload["product"] == "flyer" and payload.get("options", {}).get("fold") == "half":
            assert "half fold" in recipe["cutInstructions"]


def test_missing_bleed_and_low_dpi_still_stop():
    _, recipe = resolve_spec({"product": "business-card", "width": 3.5, "height": 2, "unit": "in", "sides": 1})
    missing = inspect(artwork(3.5, 2), recipe, 1)
    assert missing["bleed"] == "missing"
    assert missing["errors"] == []
    low = inspect(artwork(3.75, 2.25, low_resolution=True), recipe, 1)
    assert any("dpi" in item for item in low["errors"])


def test_rgb_policy_can_warn_or_reject():
    base = {"product": "flyer", "width": 8.5, "height": 11, "unit": "in", "sides": 1}
    warned, recipe = resolve_spec(base, {**default_artwork_rules(), "rgbPolicy": "warn"})
    assert warned["colourMode"] == "CMYK"
    soft = inspect(artwork(recipe["width"] + 0.25, recipe["height"] + 0.25), recipe, 1)
    assert soft["errors"] == []
    assert soft["colourMode"]["status"] == "warn"
    _, strict = resolve_spec(base, {**default_artwork_rules(), "rgbPolicy": "reject"})
    hard = inspect(artwork(strict["width"] + 0.25, strict["height"] + 0.25), strict, 1)
    assert any("DeviceRGB" in item for item in hard["errors"])


def test_artwork_rules_reject_bad_values_and_keep_design_guide_defaults():
    rules = default_artwork_rules()
    assert rules["bleedInches"] == 0.125
    assert rules["safeInches"] == 0.25
    assert rules["imageDpi"] == 300
    assert rules["rasterTextDpi"] == 1200
    assert rules["maxUploadBytes"] == 150_000_000
    assert "psd" in rules["acceptedTypes"]
    saved = normalize_artwork_rules({"bleedInches": 0.1, "safeInches": 0.2, "maxUploadMb": 40, "rgbPolicy": "reject"})
    assert saved["bleedInches"] == 0.1
    assert saved["maxUploadBytes"] == 40_000_000
    try:
        normalize_artwork_rules({"imageDpi": 10})
    except SpecError:
        pass
    else:
        raise AssertionError("low dpi was accepted")


def test_raster_image_is_placed_without_stretching_and_psd_is_blocked():
    image = Image.new("RGB", (900, 600), "navy")
    payload = io.BytesIO()
    image.save(payload, format="PNG", dpi=(300, 300))
    data = payload.getvalue()
    assert classify_upload("card.png", data, default_artwork_rules()["acceptedTypes"]) == "raster"
    pdf = prepare_artwork(data, "raster", 300)
    _, recipe = resolve_spec({
        "product": "custom",
        "width": 3,
        "height": 2,
        "unit": "in",
        "sides": 1,
        "bleed": 0,
        "safe": 0.05,
        "stock": "Photo paper",
        "finish": "Gloss",
    })
    report = inspect(pdf, recipe, 1)
    assert report["errors"] == [], report["errors"]
    assert classify_upload("logo.psd", b"8BPS" + b"\x00" * 20, ["psd", "pdf"]) == "psd"
    try:
        prepare_artwork(b"8BPS" + b"\x00" * 20, "psd", 300)
    except SpecError as error:
        assert "PSD" in error.message
    else:
        raise AssertionError("psd was converted")


def test_virtual_printers_are_hidden_and_presses_stay():
    rows = [
        {"name": "Microsoft Print to PDF", "driver": "Microsoft Print To PDF", "port": "PORTPROMPT:"},
        {"name": "OneNote (Desktop)", "driver": "Send to Microsoft OneNote 16 Driver"},
        {"name": "Adobe PDF", "driver": "Adobe PDF Converter"},
        {"name": "Shop Xerox", "driver": "Xerox AltaLink", "port": "192.168.1.20"},
    ]
    kept = filter_printers(rows)
    assert [item["name"] for item in kept] == ["Shop Xerox"]
    assert is_virtual_printer({"name": "Microsoft XPS Document Writer"})
    assert not is_virtual_printer({"name": "Fiery RIP", "driver": "EFI Fiery", "port": "9100"})


def test_proof_approval_changes_the_job_badge():
    job = {
        "state": "active",
        "approval": {"sha": "abc"},
        "tasks": [
            {"title": "Review and approve proof", "status": "Completed"},
            {"title": "Choose production route", "status": "Waiting for operator"},
        ],
    }
    assert status_label(job) == "Proof approved"
    job["approval"] = None
    job["tasks"][0]["status"] = "Waiting for approval"
    job["tasks"].pop()
    assert status_label(job) == "Waiting for approval"


def test_a_new_job_keeps_not_started_on_steps_it_has_not_reached():
    reason = "New artwork version: downstream checks and approvals invalidated."
    assert reset_result({"status": "Pending", "result": "Not started."}, reason) == "Not started."
    assert reset_result({"status": "Completed", "result": "Checked 1 page(s)."}, reason) == reason
    assert reset_result({"status": "Waiting for operator", "result": "Confirm bleed handling."}, reason) == reason


def test_review_headline_counts_passes_before_a_stop():
    results = [{"agent": f"a{i}", "status": "PASS", "summary": "ok"} for i in range(5)]
    results.append({"agent": "production", "status": "STOP", "summary": "Disconnected or stale connector."})
    headline = review_headline(results)
    assert headline["title"] == "5 checks passed"
    assert "production" in headline["detail"]
    assert review_headline([{"status": "STOP", "agent": "order", "summary": "Missing quantity"}])["title"] == "Not production-ready"


def test_billing_and_signup_stay_closed_by_default(monkeypatch=None):
    import os

    for key in ("BILLING_ENABLED", "STRIPE_SECRET_KEY", "STRIPE_PRICE_ID", "STRIPE_WEBHOOK_SECRET"):
        os.environ.pop(key, None)
    status = billing_status()
    assert status["enabled"] is False
    assert "sk_" not in str(status)
    result = signup_result()
    assert result["workspace"] is False
    assert "not open" in result["message"]
