"""Business-card defaults, the shop queue, and automatic proof steps.

Stop rules stay in the London recipe. Nothing here prints a job.
"""
from p2g.fiery_hold import interpret_hold_report
from p2g.london_card import (
    PRESET_NAME,
    apply_production_event,
    fresh_checklist,
    is_cardstock,
    is_london_card,
    match_finish,
    normalise_stock_name,
    print_ready_name,
)


AUTO_ACTOR = "Myraana (auto)"
RECIPE_STEPS = 16
QUEUE_GROUPS = (
    ("needs-you", "Needs you"),
    ("waiting-customer", "Waiting on customer"),
    ("ready-to-print", "Ready to print"),
    ("printing-cutting", "Printing/cutting"),
    ("done", "Done"),
)
QUEUE_IDS = tuple(item[0] for item in QUEUE_GROUPS)
STOP_STATUSES = {"Needs attention", "Blocked", "Failed"}
OPERATOR_STEPS = {7, 8, 9, 10, 11, 14, 15}
PREPARED_STEPS = {"start", "ask-file", "confirm-customer", "size", "canvas", "background", "safe", "export"}
HOLD_STEPS = ("import", "impose", "sheet", "save", "stock", "summary", "ready")
PAGE_MAX = 100


def known_finish(value):
    """Matte or Glossy when the coating was captured. Other words stay unknown."""
    text = " ".join(str(value or "").strip().lower().split())
    if text in {"matte", "matt", "matte cardstock"}:
        return "Matte"
    if text in {"glossy", "gloss", "gloss cardstock"}:
        return "Glossy"
    return None


def _blank(value):
    return value in (None, "")


def shop_cardstock(settings):
    for name in (settings or {}).get("stocks") or []:
        if is_cardstock(name):
            return normalise_stock_name(name)
    return "14pt matte"


def apply_card_defaults(payload, settings=None, recipe=None):
    """Fill a business-card order from the shop recipe. Values on the order win."""
    payload = dict(payload or {})
    product = str(payload.get("product") or payload.get("presetId") or "")
    if product not in {"", "business-card"}:
        return payload
    if product == "":
        payload["product"] = "business-card"
    saved = (settings or {}).get("jobDefaults") or {}
    saved_card = saved.get("product") in (None, "", "business-card")
    if _blank(payload.get("width")) and payload.get("sizeId") in (None, "", "custom"):
        width = 3.5
        height = 2.0
        if recipe and recipe.get("width") and recipe.get("height"):
            width = float(recipe["width"])
            height = float(recipe["height"])
        payload["width"] = width
        payload["height"] = height
        payload["unit"] = "in"
        payload.setdefault("sizeId", "3.5x2-in")
    if _blank(payload.get("quantity")):
        qty = saved.get("quantity") if saved_card else None
        payload["quantity"] = 100 if qty in (None, "") else qty
    if _blank(payload.get("stock")):
        payload["stock"] = shop_cardstock(settings)
    coating = known_finish(payload.get("finish"))
    if coating:
        payload["finish"] = coating
    elif _blank(payload.get("finish")):
        saved_finish = known_finish(saved.get("finish")) if saved_card else None
        payload["finish"] = saved_finish or "Matte"
    return payload


def specs_known(job):
    spec = (job or {}).get("spec") or {}
    stock = (job or {}).get("stock") or spec.get("stock")
    try:
        quantity = int((job or {}).get("quantity"))
        width = float(spec.get("width"))
        height = float(spec.get("height"))
    except (TypeError, ValueError):
        return False
    return width > 0 and height > 0 and bool(str(stock or "").strip()) and quantity >= 1


def auto_bleed(job, original_id, stamp):
    """Confirm bleed when no stop rule is waiting. Missing bleed with no decision pauses."""
    inspection = (job or {}).get("inspection") or {}
    if inspection.get("bleed") == "missing" and not job.get("bleedDecision"):
        return None
    if job.get("bleedConfirmation"):
        return job["bleedConfirmation"]
    decision = job.get("bleedDecision") or "bleed-present"
    return {
        "actor_name": AUTO_ACTOR,
        "at": stamp,
        "generation": job.get("generation"),
        "original_file_id": original_id,
        "decision": decision,
        "note": "Bleed handling recorded automatically. No stop rule fired.",
    }


def _has_artwork(job):
    return any(item.get("stage") == "ORIGINAL" for item in (job.get("files") or []))


def _open_task(job):
    for index, task in enumerate(job.get("tasks") or []):
        if task.get("status") not in {"Completed", "Cancelled"}:
            return index, task
    return None


def _open_step(job):
    return next((step for step in (job.get("productionChecklist") or []) if step.get("status") != "done"), None)


def queue_bucket(job):
    """One shop queue. Stops and operator actions land in Needs you."""
    job = job or {}
    if job.get("state") in {"complete", "cancelled"}:
        return "done"
    opened = _open_task(job)
    if opened is None:
        return "done"
    index, task = opened
    status = task.get("status") or "Pending"
    if status in STOP_STATUSES or job.get("productionStop"):
        return "needs-you"
    if index <= 1 and not _has_artwork(job):
        return "waiting-customer"
    if index in {12, 13}:
        return "printing-cutting"
    step = _open_step(job)
    hold = (job.get("fieryHold") or {}).get("status")
    if step and step.get("id") == "cutter":
        return "needs-you"
    if status in {"Waiting for operator", "Waiting for approval"} and index in OPERATOR_STEPS:
        return "needs-you"
    if hold in {"queued", "held"} and index < 12:
        return "ready-to-print"
    route = (job.get("route") or {}).get("mode")
    if route == "production" and index in {10, 11}:
        return "ready-to-print"
    return "needs-you"


def encode_cursor(updated, ident):
    return f"{updated}|{ident}"


def decode_cursor(cursor):
    text = str(cursor or "")
    if "|" not in text:
        return None
    updated, ident = text.split("|", 1)
    if not updated or not ident:
        return None
    return updated, ident


def queue_page_query(group, cursor=""):
    """Indexed page: shop_id is added by the tenant scope. Newest first."""
    if group not in QUEUE_IDS:
        group = "needs-you"
    query = {"queue": group, "archived": {"$ne": True}}
    decoded = decode_cursor(cursor)
    if decoded:
        updated, ident = decoded
        query["$or"] = [
            {"updated": {"$lt": updated}},
            {"updated": updated, "_id": {"$lt": ident}},
        ]
    return query, [("updated", -1), ("_id", -1)]


def clamp_limit(limit):
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 50
    return min(PAGE_MAX, max(1, value))


def page_jobs(jobs, group, cursor="", limit=50):
    """In-memory pager with the same order as the indexed query."""
    limit = clamp_limit(limit)
    if group not in QUEUE_IDS:
        group = "needs-you"
    rows = [job for job in jobs if queue_bucket(job) == group and not job.get("archived")]
    rows.sort(key=lambda job: (str(job.get("updated") or ""), str(job.get("id") or "")), reverse=True)
    decoded = decode_cursor(cursor)
    if decoded:
        updated, ident = decoded
        rows = [
            job
            for job in rows
            if (str(job.get("updated") or ""), str(job.get("id") or "")) < (updated, ident)
        ]
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1]
        next_cursor = encode_cursor(last.get("updated"), last.get("id"))
    counts = {name: 0 for name in QUEUE_IDS}
    for job in jobs:
        if job.get("archived"):
            continue
        counts[queue_bucket(job)] += 1
    return {"group": group, "counts": counts, "jobs": page, "nextCursor": next_cursor}


def fiery_target(settings):
    """The shop Fiery. One host wins even when its queue has a different name."""
    from p2g.printer_discovery import preferred_printer

    rows = [item for item in (settings or {}).get("discoveredPrinters") or [] if isinstance(item, dict)]
    chosen = preferred_printer(rows)
    if chosen:
        for printer in rows:
            if printer.get("name") == chosen:
                return printer
    for printer in rows:
        if printer.get("isFiery") and printer.get("name"):
            return printer
    return None


def print_order(job):
    """A business card or flyer the customer ordered to be printed."""
    spec = (job or {}).get("spec") or {}
    recipe = (job or {}).get("recipe") or {}
    product = str(
        spec.get("product")
        or (job or {}).get("product")
        or recipe.get("product")
        or recipe.get("id")
        or ""
    )
    return product in {"business-card", "flyer"}


def manual_press_message(job):
    """Step-10 card when no press is paired. Proof-only is not this message."""
    stock = str((job or {}).get("stock") or "").strip() or "the ordered stock"
    recipe = (job or {}).get("recipe") or {}
    preset = str((recipe.get("production") or {}).get("preset") or "")
    spec = (job or {}).get("spec") or {}
    product = str(spec.get("product") or (job or {}).get("product") or recipe.get("product") or recipe.get("id") or "")
    if product == "business-card" or preset == "London BC" or is_london_card(recipe):
        impose = "impose with London BC"
    elif product == "flyer":
        impose = "impose this flyer"
    else:
        impose = "impose the file"
    return (
        f"Print it yourself: download the PRINT_READY PDF, import it to Fiery, "
        f"hold it, {impose}, set {stock}"
    )


def duplo_line(job):
    """What the operator reads on the cutting step for a London card."""
    recipe = (job or {}).get("recipe") or {}
    cutter = (recipe.get("production") or {}).get("cutter") or {}
    if not cutter and not is_london_card(recipe):
        return ""
    model = str(cutter.get("model") or "Duplo DC-618")
    number = cutter.get("jobNumber") if cutter.get("jobNumber") not in (None, "") else 2
    if model == "Duplo DC-618" and str(number) == "2":
        return "Cut on Duplo DC-618, job 2"
    return f"Cut on {model}, job {number}"


def route_for_print_order(job, settings):
    """Production route. A missing printer stays manual instead of proof-only."""
    settings = settings or {}
    fiery = fiery_target(settings)
    saved = str(settings.get("printer") or "").strip()
    verified = settings.get("verifiedPrinters") or []
    printer = ""
    if saved and (not verified or saved in verified):
        printer = saved
    elif fiery and fiery.get("name") and (not verified or fiery.get("name") in verified):
        printer = str(fiery["name"])
    return {
        "mode": "production",
        "settingsVersion": settings.get("version"),
        "printer": printer or None,
        "manual": not bool(printer),
    }


def keep_production_route(job, settings):
    """Move a print order onto the production route without touching the proof.

    Tasks before the route step, the approval, the generation, and the files
    stay as they are. Proof-only is not chosen here.
    """
    approval = job.get("approval")
    generation = job.get("generation")
    files = job.get("files")
    route = route_for_print_order(job, settings)
    job["route"] = route
    step = manual_press_message(job) if route.get("manual") else (
        "Send the PRINT_READY file to the Fiery HOLD queue. It stays on HOLD and will not print."
    )
    tasks = job.get("tasks") or []
    if len(tasks) > 8:
        tasks[8]["status"] = "Completed"
        tasks[8]["result"] = "Production route. The approved proof was kept."
    if len(tasks) > 9:
        tasks[9]["status"] = "Waiting for operator"
        tasks[9]["result"] = step
    if approval is not None:
        job["approval"] = approval
    if generation is not None:
        job["generation"] = generation
    if files is not None:
        job["files"] = files
    return job


def mark_sent_to_fiery(job):
    """The operator imported the file by hand. The next open step is printing."""
    if (job.get("route") or {}).get("mode") != "production":
        return ""
    notes = (
        (9, "Completed", "Operator placed the PRINT_READY file on the Fiery HOLD queue. Myraana did not print it."),
        (10, "Completed", "Sent by hand. The shop connector was not required."),
        (11, "Completed", "The approved PRINT_READY file was marked sent to Fiery."),
        (12, "Waiting for operator", "Confirm only after the sheets physically print."),
    )
    tasks = job.get("tasks") or []
    for index, status, result in notes:
        if len(tasks) > index:
            tasks[index]["status"] = status
            tasks[index]["result"] = result
    line = duplo_line(job)
    if line and len(tasks) > 13:
        tasks[13]["result"] = line
    return line


def auto_send_ready(job, settings):
    """True when this shop asked to hold the file and a Fiery is already known."""
    if (settings or {}).get("fieryAutoSend") is not True:
        return False
    if not is_london_card((job or {}).get("recipe") or {}):
        return False
    printer = fiery_target(settings)
    if not printer:
        return False
    verified = (settings or {}).get("verifiedPrinters") or []
    if verified and printer.get("name") not in verified:
        return False
    return match_finish((job or {}).get("finish"), (settings or {}).get("stocks") or [])


def apply_known_stock(job, shop_stocks):
    """Answer the Fiery stock step when Matte or Glossy is already on the job."""
    coating = known_finish((job or {}).get("finish"))
    checklist = (job or {}).get("productionChecklist") or []
    current = next((step for step in checklist if step.get("status") != "done"), None)
    if not coating or not current or current.get("id") != "stock":
        return None
    return apply_production_event(
        checklist,
        {"step": "stock", "finish": coating, "ok": True},
        job.get("recipe") or {},
        shop_stocks,
    )


def _mark_prepared(checklist):
    for step in checklist:
        if step.get("id") in PREPARED_STEPS:
            step["status"] = "done"


def _hold_event(step_id, output_name, finish):
    if step_id == "import":
        return {"file": output_name, "ok": True}
    if step_id == "impose":
        return {"preset": PRESET_NAME, "ok": True}
    if step_id == "sheet":
        return {"sheet": {"stretched": False, "cropped": False, "missingCards": False}, "ok": True}
    if step_id == "save":
        return {"held": True, "ok": True}
    if step_id == "stock":
        return {"finish": known_finish(finish) or finish, "ok": True}
    return {"ok": True}


def record_successful_hold(job, shop_stocks):
    """Mark the Fiery hold steps done. The Duplo step stays for the operator. Never prints."""
    output = (job.get("cardRoute") or {}).get("outputName") or print_ready_name("artwork.pdf")
    if not job.get("productionChecklist"):
        job["productionChecklist"] = fresh_checklist(job.get("recipe") or {}, output)
    _mark_prepared(job["productionChecklist"])
    for step_id in HOLD_STEPS:
        current = next((step for step in job["productionChecklist"] if step.get("status") != "done"), None)
        if current is None or current.get("id") == "cutter":
            break
        if current.get("id") != step_id:
            return {
                "stop": "The checklist could not be updated automatically. Use the checklist. Nothing was printed.",
                "done": False,
            }
        outcome = apply_production_event(
            job["productionChecklist"],
            {"step": step_id, **_hold_event(step_id, output, job.get("finish"))},
            job.get("recipe") or {},
            shop_stocks,
        )
        if outcome.get("stop"):
            return outcome
    return {"stop": None, "done": False, "checklist": job["productionChecklist"]}


def stage_fiery_hold(job, ready, printer, actor, print_ready, at=""):
    """Finish readiness and authorization, then queue HOLD. This never prints."""
    if (ready or {}).get("delivery") != "fiery_hold":
        raise ValueError("The shop computer cannot place this file on Fiery HOLD. Nothing was printed.")
    tasks = job.get("tasks") or []
    if len(tasks) < 13:
        raise ValueError("This job is missing steps.")
    if tasks[12].get("status") == "Completed":
        raise ValueError("Printing was already confirmed. Nothing else was sent.")
    host = str((ready or {}).get("hostname") or "The shop computer")
    printer = printer or {}
    name = str(printer.get("name") or "")
    preset = "London BC" if is_london_card((job or {}).get("recipe") or {}) else (
        (((job or {}).get("recipe") or {}).get("production") or {}).get("preset") or "London BC"
    )
    notes = (
        (9, "Completed", "Sending the PRINT_READY file to the Fiery HOLD queue. It will not print."),
        (10, "Completed", f"{host} is connected. The PRINT_READY file will be sent to Fiery HOLD. This does not print."),
        (11, "Completed", f"Sending the PRINT_READY file to Fiery HOLD on {host}. It will not print."),
    )
    for index, status, result in notes:
        tasks[index]["status"] = status
        tasks[index]["result"] = result
        if at:
            tasks[index]["updated"] = at
            tasks[index]["finished"] = at
    tasks[12]["status"] = "Waiting for operator"
    tasks[12]["result"] = "Confirm only after physical sheets print."
    if at:
        tasks[12]["updated"] = at
    line = duplo_line(job)
    if line and len(tasks) > 13 and tasks[13].get("status") != "Completed":
        tasks[13]["result"] = line
    job["readiness"] = {
        "checkedAt": at,
        "deviceId": ready.get("id") or "",
        "hostname": host,
        "lastSeen": ready.get("lastSeen") or "",
        "delivery": "fiery_hold",
    }
    job["authorization"] = {
        "sha": (print_ready or {}).get("sha") or "",
        "fileId": (print_ready or {}).get("id") or "",
        "generation": job.get("generation"),
        "actor": actor,
        "at": at,
    }
    route = dict(job.get("route") or {})
    route["mode"] = "production"
    route["printer"] = name or route.get("printer")
    route["manual"] = False
    job["route"] = route
    job["fieryHold"] = {
        "status": "queued",
        "explicit": True,
        "deviceId": ready.get("id") or "",
        "preset": preset or "London BC",
        "stock": job.get("stock") or "",
        "finish": job.get("finish") or "",
        "printer": name,
        "address": printer.get("address") or "",
        "at": at,
        "held": False,
        "printed": False,
    }
    job.pop("productionStop", None)
    return job


def hold_failure_message(error):
    detail = str(error or "Fiery did not accept the hold.").strip()
    return f"Fiery hold failed: {detail} Use the checklist. Nothing was printed."


def operator_touches(finish_known, auto_send):
    """Clicks from a ready proof through loading Duplo. Later print, QC, and pack stay manual.

    Before this change an operator confirmed all 16 recipe steps.
    """
    touches = 1
    if not finish_known:
        touches += 1
    if not auto_send:
        touches += 1 + (6 if finish_known else 7)
    touches += 1
    return touches


__all__ = ["interpret_hold_report", "AUTO_ACTOR", "RECIPE_STEPS"]
