"""London business-card recipe: both orientations, stops, and an editable shop copy."""
import asyncio
import copy

import pymupdf

from p2g.london_card import (
    KIND_LABELS,
    STOP_BLEED,
    STOP_CUT,
    STOP_FILE,
    STOP_HOLD,
    STOP_ORIGINAL,
    STOP_PRESET,
    STOP_SIZE,
    STOP_STOCK,
    STOP_STRETCH,
    apply_production_event,
    assess_london_card,
    connector_production_hook,
    fresh_checklist,
    layout_ok,
    london_business_card_recipe,
    match_finish,
    normalise_stock_list,
    normalise_stock_name,
    print_ready_name,
    seed_london_card_shops,
)
from p2g.pdfcheck import inspect
from p2g.tenancy import TenantDatabase, shop_scope
from test_tenancy import MemoryDB


PT = 72.0


def _recipe():
    return london_business_card_recipe()


def _page(width, height, draw):
    document = pymupdf.open()
    page = document.new_page(width=width * PT, height=height * PT)
    draw(page)
    data = document.tobytes()
    document.close()
    return data


def _fill(page, color):
    page.draw_rect(page.rect, color=color, fill=color, width=0)


def _blue(width, height, text=None, text_at=None):
    def draw(page):
        _fill(page, (0.1, 0.25, 0.85))
        if text:
            point = text_at or (page.rect.width / 2 - 20, page.rect.height / 2)
            page.insert_text(point, text, fontsize=12, color=(1, 1, 1))
    return _page(width, height, draw)


def _corner_image(width, height):
    def draw(page):
        _fill(page, (0.1, 0.25, 0.85))
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 12, 12), 1)
        pix.clear_with(255)
        page.insert_image(pymupdf.Rect(1, 1, 18, 18), pixmap=pix)
    return _page(width, height, draw)


def _white_band(width=3.75, height=2.25):
    def draw(page):
        _fill(page, (1, 1, 1))
        inset = 0.125 * PT
        page.draw_rect(
            pymupdf.Rect(inset, inset, page.rect.width - inset, page.rect.height - inset),
            color=(0.1, 0.25, 0.85),
            fill=(0.1, 0.25, 0.85),
            width=0,
        )
    return _page(width, height, draw)


def _opened(data):
    document = pymupdf.open(stream=data, filetype="pdf")
    return document


def test_recipe_matches_the_london_chart():
    recipe = _recipe()
    production = recipe["production"]
    assert recipe["workflow"] == "Business card workflow: file to Fiery"
    assert recipe["width"] == 3.5 and recipe["height"] == 2
    assert recipe["bleed"] == 0.125 and recipe["safe"] == 0.125
    assert production["trim"] == {"width": 3.5, "height": 2.0, "portrait": {"width": 2.0, "height": 3.5}}
    assert production["withBleed"]["width"] == 3.75
    assert production["withBleed"]["height"] == 2.25
    assert production["withBleed"]["portrait"] == {"width": 2.25, "height": 3.75}
    assert production["orientations"] == ["landscape", "portrait"]
    sheet = production["imposition"]
    assert sheet["sheetWidthIn"] == 12 and sheet["sheetHeightIn"] == 18
    assert sheet["sheetWidthMm"] == 304.8 and sheet["sheetHeightMm"] == 457.2
    assert sheet["columns"] == 3 and sheet["rows"] == 8 and sheet["up"] == 24
    cutter = production["cutter"]
    assert cutter["model"] == "Duplo DC-618"
    assert cutter["jobNumber"] == 2 and cutter["jobName"] == "London BC"
    assert cutter["slitterSlots"] == [2, 3]
    rules = recipe["fileRules"]
    assert rules["neverSearch"] is True and rules["neverGuess"] is True
    assert rules["confirmCustomer"] is True and rules["keepOriginal"] is True
    assert rules["fieryImports"] == "PRINT_READY"
    assert rules["source"] == "operator-or-order"
    assert layout_ok(recipe) is True
    kinds = {step["kind"] for step in production["steps"]}
    assert kinds <= set(KIND_LABELS)
    assert set(KIND_LABELS) <= {"ask", "photoshop", "fiery", "decision", "stop", "start"}


def test_a_broken_imposition_is_rejected():
    broken = _recipe()
    broken["production"]["imposition"]["columns"] = 2
    broken["production"]["imposition"]["rows"] = 2
    broken["production"]["imposition"]["up"] = 4
    assert layout_ok(broken) is False
    wrong_mm = _recipe()
    wrong_mm["production"]["imposition"]["sheetWidthMm"] = 300
    assert layout_ok(wrong_mm) is False
    stopped = apply_production_event(
        _at("impose"),
        {"step": "impose", "ok": True, "preset": "London BC"},
        broken,
        ["14pt matte"],
    )
    assert stopped["stop"] == STOP_PRESET


def test_trim_file_extends_the_canvas_without_scaling_or_touching_the_original():
    original = _blue(3.5, 2, "Ada", (110, 70))
    before = bytes(original)
    result = assess_london_card(original, _recipe(), "ada-card.pdf", "Ada", "order:ada-card.pdf")
    assert original == before
    assert result["proceed"] is True
    assert result["public"]["route"] == "extend"
    assert result["public"]["kind"] == "photoshop"
    assert result["outputName"] == "ada-card_PRINT_READY.pdf"
    assert result["pdf"] is not None and result["pdf"] != original
    opened = _opened(result["pdf"])
    try:
        page = opened[0]
        assert abs(page.rect.width / PT - 3.75) < 0.01
        assert abs(page.rect.height / PT - 2.25) < 0.01
        assert "Ada" in page.get_text("text")
        pix = page.get_pixmap(dpi=36, alpha=False)
        red, green, blue = pix.pixel(0, 0)[:3]
        assert blue > 150 and red < 80
    finally:
        opened.close()
    plain = assess_london_card(_blue(3.5, 2), _recipe(), "plain.pdf", "Ada", "order:plain.pdf")
    report = inspect(
        plain["pdf"],
        {"width": 3.5, "height": 2, "bleed": 0.125, "safe": 0.125, "minDpi": 300},
        1,
    )
    assert report["errors"] == []
    assert not hasattr(__import__("p2g.london_card", fromlist=["london_card"]), "search_for_file")


def test_portrait_trim_uses_the_same_extend_step():
    original = _blue(2, 3.5, "Ada", (60, 120))
    result = assess_london_card(original, _recipe(), "portrait.pdf", "Ada", "order:portrait.pdf")
    assert result["proceed"] is True
    assert result["public"]["orientation"] == "portrait"
    assert result["trim"] == {"width": 2.0, "height": 3.5}
    opened = _opened(result["pdf"])
    try:
        page = opened[0]
        assert abs(page.rect.width / PT - 2.25) < 0.01
        assert abs(page.rect.height / PT - 3.75) < 0.01
        words = page.get_text("words")
        assert words and abs((words[0][2] - words[0][0]) - 0) >= 0
        source = _opened(original)
        try:
            old = source[0].get_text("words")[0]
            new = words[0]
            assert abs((old[2] - old[0]) - (new[2] - new[0])) < 0.8
        finally:
            source.close()
    finally:
        opened.close()


def test_text_or_logo_inside_the_eighth_inch_stops_without_a_print_ready_file():
    text = assess_london_card(_blue(3.5, 2, "QR", (2, 12)), _recipe(), "edge.pdf", "Ada", "order:edge.pdf")
    assert text["proceed"] is False and text["pdf"] is None
    assert text["stop"] == STOP_CUT
    logo = assess_london_card(_corner_image(3.5, 2), _recipe(), "logo.pdf", "Ada", "order:logo.pdf")
    assert logo["proceed"] is False and logo["pdf"] is None
    assert logo["stop"] == STOP_CUT


def test_real_bleed_proceeds_and_a_white_edge_stops():
    full = assess_london_card(_blue(3.75, 2.25, "Ada", (120, 80)), _recipe(), "full.pdf", "Ada", "order:full.pdf")
    assert full["proceed"] is True and full["pdf"] is None
    assert full["public"]["route"] == "check-bleed"
    assert full["outputName"] == "full_PRINT_READY.pdf"
    portrait = assess_london_card(_blue(2.25, 3.75, "Ada", (70, 140)), _recipe(), "tall.pdf", "Ada", "order:tall.pdf")
    assert portrait["proceed"] is True and portrait["public"]["orientation"] == "portrait"
    white = assess_london_card(_white_band(), _recipe(), "white.pdf", "Ada", "order:white.pdf")
    assert white["proceed"] is False and white["pdf"] is None
    assert white["stop"] == STOP_BLEED


def test_other_sizes_stop_and_are_not_resized():
    result = assess_london_card(_blue(4, 3), _recipe(), "other.pdf", "Ada", "order:other.pdf")
    assert result["proceed"] is False and result["pdf"] is None
    assert "size error" in result["stop"]
    assert "re-design" in result["stop"]
    assert "Never resize or stretch" in result["stop"]
    assert result["stop"] == STOP_SIZE


def test_missing_file_or_the_wrong_customer_stops_without_searching():
    empty = assess_london_card(b"", _recipe(), "card.pdf", "Ada", "order:card.pdf")
    assert empty["stop"] == STOP_FILE
    missing = assess_london_card(_blue(3.5, 2), _recipe(), "card.pdf", "Ada", "")
    assert missing["stop"] == STOP_FILE
    wrong = assess_london_card(
        _blue(3.5, 2, "customer: Bea", (80, 70)),
        _recipe(),
        "ada-card.pdf",
        "Ada",
        "order:ada-card.pdf",
    )
    assert wrong["stop"] == STOP_FILE and wrong["pdf"] is None
    right = assess_london_card(_blue(3.5, 2, "Ada", (110, 70)), _recipe(), "ada-card.pdf", "Ada", "order:ada-card.pdf")
    assert right["proceed"] is True


def test_stock_phrases_map_to_matte_and_finishes_use_the_shop_list():
    assert normalise_stock_name("14-pt paper weight") == "14pt matte"
    assert normalise_stock_name("14 pt paper weight") == "14pt matte"
    assert normalise_stock_name("14pt") == "14pt matte"
    assert normalise_stock_name("14-pt") == "14pt matte"
    assert normalise_stock_name("14pt matte") == "14pt matte"
    assert normalise_stock_name("16pt soft touch") == "16pt soft touch"
    assert normalise_stock_name("100lb Gloss Text") == "100lb Gloss Text"
    assert normalise_stock_name("14-pt glossy") == "14-pt glossy"
    assert normalise_stock_list(["14-pt paper weight", "14pt matte", "16pt soft touch"]) == [
        "14pt matte",
        "16pt soft touch",
    ]
    stocks = ["14pt matte", "16pt soft touch", "100lb Gloss Text"]
    assert match_finish("Matte", stocks) == "14pt matte"
    assert match_finish("Glossy", stocks) == "100lb Gloss Text"
    assert match_finish("Soft touch", stocks) is None
    assert print_ready_name("card.pdf") == "card_PRINT_READY.pdf"
    assert print_ready_name("") == "artwork_PRINT_READY.pdf"


def test_checklist_covers_the_chart_and_stops_on_the_fiery_rules():
    recipe = _recipe()
    steps = fresh_checklist(recipe, "card_PRINT_READY.pdf")
    titles = " ".join(step["title"] + " " + step["detail"] for step in steps)
    assert "Ask for the design file location" in titles
    assert "right customer" in titles
    assert "PRINT_READY" in titles and "never the original" in titles
    assert "HOLD" in titles
    assert "London BC" in titles
    assert "Matte or Glossy" in titles
    assert "Ready to print after approval" in titles
    assert "job no. 2" in titles
    assert {step["kind"] for step in steps} <= set(KIND_LABELS)
    stocks = ["14pt matte", "100lb Gloss Text"]
    rejected = apply_production_event(_at("import"), {"step": "import", "file": "card.pdf"}, recipe, stocks)
    assert rejected["stop"] == STOP_ORIGINAL
    held = apply_production_event(_at("save"), {"step": "save", "held": False}, recipe, stocks)
    assert held["stop"] == STOP_HOLD
    stretched = apply_production_event(
        _at("sheet"),
        {"step": "sheet", "sheet": {"stretched": True, "cropped": False, "missingCards": False}},
        recipe,
        stocks,
    )
    assert stretched["stop"] == STOP_STRETCH
    unknown = apply_production_event(_at("stock"), {"step": "stock", "finish": "Canvas"}, recipe, stocks)
    assert unknown["stop"] == STOP_STOCK
    walking = fresh_checklist(recipe, "card_PRINT_READY.pdf")
    events = [
        ("start", {}),
        ("ask-file", {}),
        ("confirm-customer", {}),
        ("size", {}),
        ("canvas", {}),
        ("background", {}),
        ("safe", {}),
        ("export", {}),
        ("import", {"file": "card_PRINT_READY.pdf"}),
        ("impose", {"preset": "London BC"}),
        ("sheet", {"sheet": {"stretched": False, "cropped": False, "missingCards": False}}),
        ("save", {"held": True}),
        ("stock", {"finish": "Matte"}),
        ("summary", {}),
        ("ready", {}),
        ("cutter", {}),
    ]
    result = None
    for step_id, extra in events:
        result = apply_production_event(walking, {"step": step_id, "ok": True, **extra}, recipe, stocks)
        assert result["stop"] is None
    assert result["done"] is True
    assert walking[-4]["stock"] == "14pt matte"
    hook = connector_production_hook({"recipe": recipe, "cardRoute": {"outputName": "card_PRINT_READY.pdf"}})
    assert hook["file"] == "card_PRINT_READY.pdf"
    assert "never the original" in hook["importRule"]
    assert connector_production_hook({"recipe": {"id": "flyer", "product": "flyer"}}) is None


def _at(step_id):
    checklist = fresh_checklist(_recipe(), "card_PRINT_READY.pdf")
    for step in checklist:
        if step["id"] == step_id:
            break
        step["status"] = "done"
    return checklist


def test_seed_is_idempotent_isolated_and_keeps_shop_edits():
    asyncio.run(_seed())


async def _seed():
    database = TenantDatabase(MemoryDB())
    first = await seed_london_card_shops(database)
    assert first["print2go"] == "inserted"
    assert first["print2go-london"] == "inserted"
    second = await seed_london_card_shops(database)
    assert second["print2go"] == "present"
    assert second["print2go-london"] == "present"
    with shop_scope("print2go"):
        rows = await database.recipes.find({"id": "business-card"}).to_list(10)
        assert len(rows) == 1
        rows[0]["cutInstructions"] = "Shop cut note"
        await database.recipes.update_one(
            {"id": "business-card", "version": 1},
            {"$set": {"cutInstructions": "Shop cut note"}},
        )
    assert (await seed_london_card_shops(database))["print2go"] == "present"
    with shop_scope("print2go"):
        kept = await database.recipes.find_one({"id": "business-card", "version": 1})
        assert kept["cutInstructions"] == "Shop cut note"
        assert kept["production"]["preset"] == "London BC"
    with shop_scope("print2go-london"):
        other = await database.recipes.find_one({"id": "business-card"})
        assert other["cutInstructions"] != "Shop cut note"
        assert other["shop_id"] == "print2go-london"
    with shop_scope("print2go"):
        visible = await database.recipes.find({}).to_list(10)
        assert [row["shop_id"] for row in visible] == ["print2go"]

    edited = TenantDatabase(MemoryDB())
    with shop_scope("print2go"):
        await edited.raw.shops.insert_one({"_id": "print2go", "slug": "print2go", "name": "Print2Go"})
        plain = {
            "id": "business-card",
            "version": 1,
            "name": "Business card",
            "width": 3.5,
            "height": 2,
            "bleed": 0.125,
            "safe": 0.2,
            "cutInstructions": "Edited by the shop",
        }
        await edited.recipes.insert_one(plain)
    assert (await seed_london_card_shops(edited, ("print2go",)))["print2go"] == "upgraded"
    with shop_scope("print2go"):
        upgraded = await edited.recipes.find({"id": "business-card"}).to_list(10)
        assert len(upgraded) == 1
        assert upgraded[0]["safe"] == 0.2
        assert upgraded[0]["cutInstructions"] == "Edited by the shop"
        assert upgraded[0]["production"]["preset"] == "London BC"
        assert upgraded[0]["fileRules"]["neverSearch"] is True
