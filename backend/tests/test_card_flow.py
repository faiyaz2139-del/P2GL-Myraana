"""Business-card flow: defaults, queue pages, and a Fiery hold that never prints."""
from pathlib import Path

from p2g.card_flow import (
    AUTO_ACTOR,
    RECIPE_STEPS,
    apply_card_defaults,
    apply_known_stock,
    auto_bleed,
    duplo_line,
    keep_production_route,
    known_finish,
    manual_press_message,
    mark_sent_to_fiery,
    operator_touches,
    print_order,
    page_jobs,
    queue_bucket,
    queue_page_query,
    record_successful_hold,
    shop_cardstock,
    specs_known,
)
from p2g.fiery_hold import hold_payload, interpret_hold_report, submit_hold
from p2g.london_card import STOP_PRESET, london_business_card_recipe


ROOT = Path(__file__).resolve().parents[2]


def _task(status="Pending", title="Step"):
    return {"status": status, "title": title}


def _job(**extra):
    tasks = [_task("Completed" if index == 0 else "Pending") for index in range(16)]
    job = {
        "id": "job-1",
        "state": "active",
        "tasks": tasks,
        "files": [],
        "updated": "2026-10-22T00:00:00",
        "spec": {"width": 3.5, "height": 2, "stock": "14pt matte"},
        "quantity": 100,
        "stock": "14pt matte",
        "finish": "Matte",
    }
    job.update(extra)
    return job


def test_card_defaults_use_the_shop_recipe_and_keep_an_order():
    settings = {
        "stocks": ["100lb Gloss Text", "14pt matte", "Gloss Cover"],
        "jobDefaults": {"product": "business-card", "quantity": 250, "finish": "Gloss"},
    }
    filled = apply_card_defaults({"product": "business-card"}, settings)
    assert (filled["width"], filled["height"], filled["unit"]) == (3.5, 2.0, "in")
    assert filled["quantity"] == 250
    assert filled["stock"] == "14pt matte"
    assert filled["finish"] == "Glossy"
    assert shop_cardstock(settings) == "14pt matte"
    explicit = apply_card_defaults(
        {"product": "business-card", "width": 2, "height": 3.5, "quantity": 40, "stock": "16pt", "finish": "Matte"},
        settings,
    )
    assert explicit["width"] == 2 and explicit["height"] == 3.5
    assert explicit["quantity"] == 40 and explicit["stock"] == "16pt" and explicit["finish"] == "Matte"
    assert known_finish("Soft touch") is None
    assert known_finish("gloss") == "Glossy"


def test_missing_bleed_still_pauses_and_a_real_bleed_is_automatic():
    paused = _job(inspection={"bleed": "missing"})
    assert auto_bleed(paused, "orig", "2026-10-22T00:00:00") is None
    ready = _job(inspection={"bleed": "present"})
    confirmation = auto_bleed(ready, "orig", "2026-10-22T00:00:00")
    assert confirmation["actor_name"] == AUTO_ACTOR
    assert confirmation["decision"] == "bleed-present"
    assert specs_known(_job()) is True
    assert specs_known(_job(spec={})) is False


def test_queue_groups_and_pages_two_thousand_jobs():
    waiting = _job(id="wait")
    needs = _job(id="proof", files=[{"stage": "ORIGINAL"}])
    needs["tasks"][7]["status"] = "Waiting for approval"
    for index in range(1, 7):
        needs["tasks"][index]["status"] = "Completed"
    held = _job(id="held", files=[{"stage": "ORIGINAL"}], fieryHold={"status": "held"}, route={"mode": "production"})
    for index in range(1, 10):
        held["tasks"][index]["status"] = "Completed"
    printing = _job(id="press", files=[{"stage": "ORIGINAL"}])
    for index in range(1, 12):
        printing["tasks"][index]["status"] = "Completed"
    done = _job(id="done", state="complete")
    stopped = _job(id="stop", files=[{"stage": "ORIGINAL"}], productionStop="STOP")
    stopped["tasks"][2]["status"] = "Needs attention"
    assert queue_bucket(waiting) == "waiting-customer"
    assert queue_bucket(needs) == "needs-you"
    assert queue_bucket(stopped) == "needs-you"
    assert queue_bucket(held) == "ready-to-print"
    assert queue_bucket(printing) == "printing-cutting"
    assert queue_bucket(done) == "done"
    rows = []
    for index in range(2000):
        rows.append(_job(id=f"job-{index:04d}", updated=f"2026-10-22T00:{index // 60:02d}:{index % 60:02d}", state="complete"))
    rows.append(needs)
    page = page_jobs(rows, "done", limit=50)
    assert page["counts"]["done"] == 2000
    assert page["counts"]["needs-you"] == 1
    assert len(page["jobs"]) == 50
    assert page["nextCursor"]
    second = page_jobs(rows, "done", cursor=page["nextCursor"], limit=50)
    assert len(second["jobs"]) == 50
    assert {item["id"] for item in page["jobs"]}.isdisjoint({item["id"] for item in second["jobs"]})
    query, ordering = queue_page_query("ready-to-print")
    assert query["queue"] == "ready-to-print"
    assert ordering[0] == ("updated", -1)


def test_print_order_stays_on_production_and_a_proof_switch_keeps_the_proof():
    recipe = london_business_card_recipe()
    job = _job(
        recipe=recipe,
        product="business-card",
        spec={"product": "business-card", "width": 3.5, "height": 2, "stock": "14pt matte"},
        stock="14pt matte",
        finish="Matte",
        generation=3,
        approval={"sha": "proof-sha", "fileId": "file-1"},
        files=[{"id": "file-1", "stage": "PRINT_READY", "sha": "proof-sha", "name": "RA_PRINT_READY.pdf"}],
        route={"mode": "proof-only", "printer": None},
    )
    for index in range(8):
        job["tasks"][index]["status"] = "Completed"
        job["tasks"][index]["result"] = f"done-{index}"
    job["tasks"][8]["status"] = "Completed"
    job["tasks"][8]["result"] = "Proof-only route selected. No press is assigned and nothing will print."
    job["tasks"][9]["status"] = "Waiting for operator"
    job["tasks"][9]["result"] = "Proof only: nothing is sent to a press."
    assert print_order(job) is True
    assert print_order(_job(spec={"product": "flyer"}, product="flyer")) is True
    keep_production_route(job, {"version": 4, "stocks": ["14pt matte"], "printer": "", "discoveredPrinters": []})
    assert job["route"]["mode"] == "production"
    assert job["route"]["manual"] is True
    assert job["approval"] == {"sha": "proof-sha", "fileId": "file-1"}
    assert job["generation"] == 3
    assert job["files"][0]["sha"] == "proof-sha"
    for index in range(8):
        assert job["tasks"][index]["status"] == "Completed"
        assert job["tasks"][index]["result"] == f"done-{index}"
    assert job["tasks"][9]["result"] == manual_press_message(job)
    assert job["tasks"][9]["result"] == (
        "Print it yourself: download the PRINT_READY PDF, import it to Fiery, "
        "hold it, impose with London BC, set 14pt matte"
    )
    assert "Proof only" not in job["tasks"][9]["result"]
    paired = {
        "version": 4,
        "discoveredPrinters": [
            {"name": "Xerox EX-Li PX300 Server 1.0 US(6B:72:F0)", "address": "192.168.0.200", "isFiery": True},
            {"name": "Color Printer", "address": "192.168.0.200", "isFiery": True},
        ],
    }
    keep_production_route(job, paired)
    assert job["route"]["mode"] == "production"
    assert job["route"]["manual"] is False
    assert job["route"]["printer"] == "Xerox EX-Li PX300 Server 1.0 US(6B:72:F0)"
    assert "Fiery HOLD" in job["tasks"][9]["result"]
    assert job["approval"]["sha"] == "proof-sha"
    keep_production_route(job, {"version": 4, "printer": "", "discoveredPrinters": []})
    assert mark_sent_to_fiery(job) == "Cut on Duplo DC-618, job 2"
    assert duplo_line(job) == "Cut on Duplo DC-618, job 2"
    assert queue_bucket(job) == "printing-cutting"
    assert job["tasks"][12]["status"] == "Waiting for operator"
    assert job["tasks"][9]["status"] == "Completed"
    assert job["approval"]["sha"] == "proof-sha"
    assert job["generation"] == 3
    flyer = _job(spec={"product": "flyer"}, product="flyer", stock="100lb Gloss Text")
    assert "impose this flyer" in manual_press_message(flyer)
    assert "100lb Gloss Text" in manual_press_message(flyer)


def test_known_finish_answers_stock_and_a_hold_leaves_duplo_without_printing():
    recipe = london_business_card_recipe()
    job = _job(recipe=recipe, finish="Matte", cardRoute={"outputName": "card_PRINT_READY.pdf"})
    outcome = record_successful_hold(job, ["14pt matte", "Gloss Cover"])
    assert outcome["stop"] is None
    statuses = {step["id"]: step["status"] for step in job["productionChecklist"]}
    assert statuses["import"] == "done"
    assert statuses["save"] == "done"
    assert statuses["stock"] == "done"
    assert statuses["cutter"] == "pending"
    assert job["productionChecklist"][-1]["id"] == "cutter"
    broken = _job(recipe=london_business_card_recipe(), finish="Matte")
    broken["recipe"]["production"]["imposition"]["name"] = "Other"
    stopped = record_successful_hold(broken, ["14pt matte"])
    assert stopped["stop"] == STOP_PRESET
    stock_job = _job(recipe=recipe, finish="Glossy", productionChecklist=[{"id": "stock", "status": "pending"}])
    answered = apply_known_stock(stock_job, ["Gloss Cover"])
    assert answered["stop"] is None
    assert stock_job["productionChecklist"][0]["status"] == "done"


def test_fiery_hold_never_prints_and_falls_back_to_a_hold_folder(tmp_path=None):
    seen = {}

    def opener(url, payload, pdf, timeout):
        seen["url"] = url
        seen["payload"] = payload
        seen["pdf"] = pdf
        return 500

    refused = submit_hold("10.0.0.8", "card_PRINT_READY.pdf", "London BC", "14pt matte", b"%PDF", opener=opener)
    assert refused["ok"] is False and refused["printed"] is False
    assert seen["payload"]["queue"] == "hold"
    assert seen["payload"]["print"] is False and seen["payload"]["release"] is False
    assert seen["url"].endswith("/live/api/v5/jobs")
    folder = ROOT / "backend" / "tests" / "_hold_tmp"
    folder.mkdir(exist_ok=True)
    try:
        saved = submit_hold(
            "10.0.0.8",
            "card_PRINT_READY.pdf",
            "London BC",
            "Matte",
            b"%PDF-hold",
            opener=opener,
            hot_folder=str(folder),
        )
        assert saved == {"ok": True, "held": True, "printed": False, "method": "hot-folder", "error": ""}
        assert (folder / "Hold" / "card_PRINT_READY.pdf").read_bytes() == b"%PDF-hold"
        assert not (folder / "card_PRINT_READY.pdf").exists()
    finally:
        target = folder / "Hold" / "card_PRINT_READY.pdf"
        if target.exists():
            target.unlink()
        hold_dir = folder / "Hold"
        if hold_dir.exists():
            hold_dir.rmdir()
        if folder.exists():
            folder.rmdir()
    assert interpret_hold_report({"ok": True, "held": True, "printed": True})["ok"] is False
    assert hold_payload("x.pdf", "London BC", "Matte")["release"] is False


def test_operator_clicks_drop_when_the_proof_path_is_automatic():
    assert RECIPE_STEPS == 16
    assert operator_touches(finish_known=True, auto_send=True) == 2
    assert operator_touches(finish_known=False, auto_send=True) == 3
    assert operator_touches(finish_known=True, auto_send=False) < RECIPE_STEPS
    workflow = (ROOT / "backend" / "p2g" / "workflow.py").read_text(encoding="utf-8")
    pipeline = workflow.split("async def run_pdf_workflow", 1)[1].split("async def process_with_lease", 1)[0]
    assert "actor = AUTO_ACTOR" in pipeline
    assert "Proof is ready to send" in pipeline
    assert 'name="shop_queue_updated"' in workflow
    server = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "fieryAutoSend" in server
    assert "process_with_lease(job[\"id\"], job[\"generation\"], AUTO_ACTOR)" in server
    original = (ROOT / "backend" / "p2g" / "fiery_hold.py").read_text(encoding="utf-8")
    shipped = (ROOT / "frontend" / "public" / "setup" / "fiery_hold.py").read_text(encoding="utf-8")
    assert original == shipped
    connector = (ROOT / "frontend" / "public" / "setup" / "myraana-connector.py").read_text(encoding="utf-8")
    assert "perform_holds" in connector
    assert "It was not printed" in connector


def test_queue_index_page_does_not_request_every_job():
    query, _ordering = queue_page_query("needs-you", "2026-10-22T00:00:00|job-9")
    assert query["archived"] == {"$ne": True}
    assert "$or" in query
    assert "limit" not in query
