"""One-button job flow. Automatic mode is on unless the shop turns it off.

The run stops for customer approval and for an unsupported size. After approval
the file can be authorized onto Fiery HOLD. Nothing here prints or releases.
"""
from datetime import datetime, timedelta, timezone

from p2g.card_flow import fiery_target, is_london_card, known_finish
from p2g.connector_auth import credential_hash


PROOF_LINK_DAYS = 7


def automatic_mode(settings):
    """Missing means on. Only an explicit false turns the steps back on."""
    if not isinstance(settings, dict) or "automaticMode" not in settings:
        return True
    return settings.get("automaticMode") is not False


def _task(job, index):
    tasks = (job or {}).get("tasks") or []
    if index >= len(tasks) or not isinstance(tasks[index], dict):
        return {"status": "Pending", "result": ""}
    return tasks[index]


def job_failure(job):
    """The reason a person needs to fix this job, when there is one."""
    job = job or {}
    card = job.get("cardRoute") or {}
    if card.get("stop") and _task(job, 6).get("status") != "Completed":
        return str(card["stop"])
    for index in (2, 3, 4, 5, 6):
        task = _task(job, index)
        if task.get("status") in {"Blocked", "Failed", "Needs attention"}:
            return str(task.get("result") or "This step needs a fix.")
    hold = job.get("fieryHold") or {}
    if hold.get("status") == "failed":
        return str(hold.get("error") or "The Fiery Hold queue did not confirm the file. Nothing was printed.")
    automatic = job.get("automatic") or {}
    if automatic.get("error"):
        return str(automatic["error"])
    return ""


def timeline(job):
    """Six phases. A phase carries detail only when it failed."""
    job = job or {}
    failure = job_failure(job)
    proof_done = _task(job, 6).get("status") == "Completed"
    proof_failed = (not proof_done) and bool(failure) and (
        bool((job.get("cardRoute") or {}).get("stop"))
        or _task(job, 2).get("status") in {"Blocked", "Failed", "Needs attention"}
        or _task(job, 3).get("status") in {"Blocked", "Failed", "Needs attention"}
        or _task(job, 6).get("status") in {"Blocked", "Failed"}
    )
    approved = bool((job.get("approval") or {}).get("sha"))
    hold = (job.get("fieryHold") or {}).get("status") or ""
    printed = _task(job, 12).get("status") == "Completed"
    cut = _task(job, 13).get("status") == "Completed"
    packed = _task(job, 15).get("status") == "Completed"
    phases = []

    def add(ident, title, state, detail=""):
        phases.append({
            "id": ident,
            "title": title,
            "state": state,
            "detail": detail if state == "failed" else "",
        })

    add("order", "Order", "done" if _task(job, 0).get("status") == "Completed" else "current")
    if proof_failed:
        add("proof", "Artwork and proof", "failed", failure)
    elif proof_done:
        add("proof", "Artwork and proof", "done")
    elif _task(job, 1).get("status") != "Completed":
        add("proof", "Artwork and proof", "waiting")
    else:
        add("proof", "Artwork and proof", "current")
    if not proof_done:
        add("approval", "Customer approval", "upcoming")
    elif approved:
        add("approval", "Customer approval", "done")
    else:
        add("approval", "Customer approval", "current")
    hold_error = ""
    if hold == "failed":
        hold_error = failure
    elif approved and (job.get("automatic") or {}).get("error") and hold != "held":
        hold_error = str((job.get("automatic") or {}).get("error"))
    if hold == "held":
        add("hold", "Fiery HOLD", "done")
    elif hold_error:
        add("hold", "Fiery HOLD", "failed", hold_error)
    elif approved or hold == "queued":
        add("hold", "Fiery HOLD", "current")
    else:
        add("hold", "Fiery HOLD", "upcoming")
    if printed and cut:
        add("press", "Print and cut", "done")
    elif hold == "held" or printed:
        add("press", "Print and cut", "current")
    else:
        add("press", "Print and cut", "upcoming")
    if packed:
        add("finish", "Pack", "done")
    elif printed and cut:
        add("finish", "Pack", "current")
    else:
        add("finish", "Pack", "upcoming")
    return phases


def imposition_note(job):
    recipe = (job or {}).get("recipe") or {}
    product = str(((job or {}).get("spec") or {}).get("product") or (job or {}).get("product") or "")
    if is_london_card(recipe) or (recipe.get("production") or {}).get("preset") == "London BC" or product == "business-card":
        return "Impose with London BC."
    if product == "flyer":
        return "Impose this flyer."
    return "Impose the file."


def automatic_route_note(job, settings):
    printer = fiery_target(settings) or {}
    name = str(printer.get("name") or (settings or {}).get("printer") or "").strip() or "the shop press"
    finish = known_finish((job or {}).get("finish")) or str((job or {}).get("finish") or "").strip() or "the ordered stock"
    return f"Production route: {name}. {imposition_note(job)} Stock {finish}. Nothing is printed."


def _moment(value):
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def proof_link_expiry(created_at, days=PROOF_LINK_DAYS):
    moment = _moment(created_at) or datetime.now(timezone.utc)
    return (moment + timedelta(days=days)).isoformat()


def build_proof_link(job_id, shop_id, token, created_by, created_at, *, link_id):
    if not job_id or not shop_id or not str(token or "").strip():
        return None
    return {
        "_id": link_id,
        "job_id": str(job_id),
        "shop_id": str(shop_id),
        "token_hash": credential_hash(token),
        "created_by": str(created_by or ""),
        "created_at": created_at,
        "expires_at": proof_link_expiry(created_at),
        "used_at": "",
        "status": "open",
    }


def proof_link_state(record, at):
    if not record:
        return "missing"
    if record.get("status") == "used" or record.get("used_at"):
        return "used"
    if str(record.get("expires_at") or "") <= str(at or ""):
        return "expired"
    if record.get("status") != "open":
        return "invalid"
    return "open"


def apply_customer_approval(job, print_ready, actor, at):
    """Record approval of this exact PDF. Does not authorize printing."""
    sha = str((print_ready or {}).get("sha") or "")
    if not sha:
        return "missing"
    if (job.get("approval") or {}).get("sha") == sha:
        return "already"
    job["approval"] = {
        "sha": sha,
        "fileId": (print_ready or {}).get("id") or "",
        "actor": actor or "Customer",
        "at": at,
        "generation": job.get("generation"),
    }
    tasks = job.get("tasks") or []
    if len(tasks) > 7 and isinstance(tasks[7], dict):
        tasks[7]["status"] = "Completed"
        tasks[7]["result"] = "Proof approved for this exact PDF."
        if at:
            tasks[7]["updated"] = at
            tasks[7]["finished"] = at
    return "approved"
