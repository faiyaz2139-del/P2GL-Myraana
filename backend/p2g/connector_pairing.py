import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from p2g.account_access import exclude_archived
from p2g.automatic import (
    apply_customer_approval,
    automatic_mode,
    automatic_route_note,
    build_proof_link,
    proof_link_state,
)
from p2g.card_flow import (
    AUTO_ACTOR,
    fiery_target,
    hold_failure_message,
    keep_production_route,
    record_successful_hold,
    route_for_print_order,
    stage_fiery_hold,
)
from p2g.connector_auth import (
    build_pairing_document,
    connector_presence,
    credential_hash,
    legacy_credential_hash,
    list_open_pairings,
    manual_approval_required,
    hold_for_device,
    normalise_capabilities,
    pairing_shop_id,
    shop_for_connected_pairing,
)
from p2g.connector_enroll import (
    ENROLL_WINDOW,
    PUBLIC_ENROLL_ERROR,
    build_enrollment,
    choose_device,
    enrollment_download,
    enrollment_rate_limited,
    enrollment_state,
    enrollment_website,
    public_enrollment,
    published_connector_update,
)
from p2g.core import AppError, db, new_id, now
from p2g.fiery_hold import hold_method_label, interpret_hold_report, job_label
from p2g.printer_discovery import normalise_reported, preferred_printer, scan_is_due
from p2g.printers import filter_printers
from p2g.tenancy import PRINT2GO_SHOP_ID, bound_shop, current_shop_id, shop_scope, unscoped
from p2g.workflow import file_bytes, get_job, latest, readiness, record_event, save_job, update_task


def _valid_id(value):
    value = str(value or "")
    if len(value) < 16 or len(value) > 80:
        raise AppError("Connector device identity is invalid.", 400)
    return value


def _inventory(value):
    if not isinstance(value, dict):
        raise AppError("Connector inventory is invalid.", 400)
    result = {}
    for key in ("printers", "fiery_rip", "hot_folders"):
        items = value.get(key, [])
        if not isinstance(items, list) or len(items) > 50:
            raise AppError("Connector inventory is invalid.", 400)
        result[key] = [item for item in items if isinstance(item, dict)][:50]
    result["printers"] = filter_printers(result.get("printers"))
    result["hostname"] = str(value.get("hostname", ""))[:120]
    result["capabilities"] = normalise_capabilities(value.get("capabilities"))
    return result


async def create_pairing(user):
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    pairing = build_pairing_document(
        user,
        pairing_id=new_id(),
        code_hash=credential_hash(code),
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        created_at=now(),
        current_shop=current_shop_id(),
    )
    if not pairing:
        raise AppError("Sign in to your shop.", 401)
    await db.connector_pairings.insert_one(pairing)
    return {"id": pairing["_id"], "code": code, "expiresIn": 600}


async def claim_pairing(payload):
    code = str(payload.get("code") or "").strip().upper()
    device_id = _valid_id(payload.get("deviceId"))
    claim = str(payload.get("claimSecret") or "")
    if len(code) != 8 or len(claim) < 32 or len(claim) > 160:
        raise AppError("Pairing request is invalid.", 400)
    with unscoped():
        pairing = await db.connector_pairings.find_one(
            {"code_hash": credential_hash(code), "status": "Searching"}
        )
        if not pairing or pairing["expires_at"] <= now():
            raise AppError("Pairing code is invalid or expired.", 409)
        result = await db.connector_pairings.update_one(
            {"_id": pairing["_id"], "status": "Searching"},
            {"$set": {"status": "Found", "device_id": device_id, "claim_hash": credential_hash(claim),
                      "inventory": _inventory(payload.get("inventory")), "claimed_at": now()}},
        )
    if not result.modified_count:
        raise AppError("Pairing is no longer available.", 409)
    return {"id": pairing["_id"], "status": "Found"}


async def pairing_status(pairing_id, claim):
    with unscoped():
        pairing = await db.connector_pairings.find_one({"_id": pairing_id})
    if not pairing or pairing["expires_at"] <= now():
        raise AppError("Pairing is invalid or expired.", 409)
    expected = pairing.get("claim_hash") or ""
    actual = credential_hash(claim)
    if len(expected) != len(actual) or not hmac.compare_digest(expected, actual):
        raise AppError("Connector claim is invalid.", 401)
    if pairing["status"] != "Connected":
        return {"status": pairing["status"]}
    shop_id = shop_for_connected_pairing(pairing)
    if not shop_id:
        raise AppError("Pairing is not bound to a shop.", 409)
    credential = secrets.token_urlsafe(48)
    with shop_scope(shop_id):
        await db.connector_devices.update_one(
            {"_id": pairing["device_id"]},
            {"$set": {"credential_hash": credential_hash(credential), "enabled": True,
                      "inventory": pairing["inventory"], "lastSeen": now(), "status": "Connecting"}},
            upsert=True,
        )
        await db.connector_pairings.update_one({"_id": pairing_id}, {"$set": {"status": "Consumed"}})
    return {"status": "Connected", "credential": credential}


async def approve_pairing(pairing_id, user):
    result = await db.connector_pairings.update_one(
        {"_id": pairing_id, "status": "Found", "expires_at": {"$gt": now()}},
        {"$set": {"status": "Connected", "approved_by": user["id"], "approved_at": now()}},
    )
    if not result.modified_count:
        raise AppError("No pending connector was found.", 409)
    return {"ok": True}


async def pairings():
    """Live Searching and Found codes only. Expired rows are marked Expired first."""
    rows = await list_open_pairings(db.connector_pairings, now())
    known = [device.get("id") for device in await devices()]
    for row in rows:
        row["manualApproval"] = manual_approval_required(
            row.get("created_at"), row.get("device_id"), known
        )
    return rows


async def devices():
    records = await db.connector_devices.find(
        {},
        {"credential_hash": 0},
    ).to_list(50)
    current = datetime.now(timezone.utc)
    for record in records:
        record["id"] = record.pop("_id")
        record["status"] = connector_presence(record.get("lastSeen"), record.get("enabled"), current)
    return records


async def _device_for(request):
    credential = request.headers.get("authorization", "").removeprefix("Bearer ")
    requested = request.headers.get("x-shop-id")
    plain = credential_hash(credential)
    with unscoped():
        device = await db.connector_devices.find_one({"credential_hash": plain, "enabled": True})
        kind = "current" if device else None
        if not device:
            old = legacy_credential_hash(credential, os.environ.get("CONNECTOR_SECRET"))
            if old:
                device = await db.connector_devices.find_one(
                    {"credential_hash": old, "enabled": True}
                )
                kind = "legacy" if device else None
    if device and kind == "legacy" and (device.get("shop_id") or PRINT2GO_SHOP_ID) != PRINT2GO_SHOP_ID:
        device = None
    if not device:
        raise AppError("Connector authentication failed.", 401)
    owner = device.get("shop_id") or PRINT2GO_SHOP_ID
    return device, bound_shop(owner, requested)


async def _record_holds(reports, settings):
    if not isinstance(reports, list):
        return
    stocks = (settings or {}).get("stocks") or []
    for report in reports[:8]:
        if not isinstance(report, dict):
            continue
        job = await get_job(str(report.get("jobId") or ""))
        if not job or (job.get("fieryHold") or {}).get("status") not in {"queued", "held"}:
            continue
        interpreted = interpret_hold_report(report)
        hold = dict(job.get("fieryHold") or {})
        if interpreted["ok"]:
            hold.update(
                {
                    "status": "held",
                    "held": True,
                    "printed": False,
                    "method": interpreted["method"],
                    "error": "",
                }
            )
            job["fieryHold"] = hold
            # Readiness and authorize already moved the job past the handoff.
            # Recording the hold must not send that job back to step 10.
            note = (
                f"PRINT_READY is on the Fiery HOLD queue via {hold_method_label(interpreted['method'])}. "
                "It was not printed."
            )
            past_handoff = job["tasks"][10]["status"] == "Completed"
            if past_handoff:
                job.pop("productionStop", None)
                if job["tasks"][11]["status"] == "Completed":
                    update_task(job, 11, "Completed", note, AUTO_ACTOR)
                if len(job["tasks"]) > 12 and job["tasks"][12]["status"] != "Completed":
                    update_task(
                        job,
                        12,
                        "Waiting for operator",
                        f"{note} Confirm only after physical sheets print.",
                        AUTO_ACTOR,
                    )
            else:
                outcome = record_successful_hold(job, stocks)
                if outcome.get("stop"):
                    job["productionStop"] = outcome["stop"]
                    update_task(job, 9, "Needs attention", f"{outcome['stop']} Nothing was printed.", AUTO_ACTOR)
                else:
                    job.pop("productionStop", None)
                    pending = next((step for step in job.get("productionChecklist") or [] if step.get("status") != "done"), None)
                    title = pending["title"] if pending else "Load Duplo DC-618 job no. 2."
                    update_task(job, 9, "Waiting for operator", title, AUTO_ACTOR)
            record_event(job, note, AUTO_ACTOR)
        else:
            hold.update({
                "status": "failed",
                "held": False,
                "printed": False,
                "method": interpreted.get("method") or "",
                "error": interpreted["error"],
            })
            job["fieryHold"] = hold
            message = interpreted["error"]
            if "Nothing was printed" not in message and "stays on HOLD" not in message:
                message = hold_failure_message(message)
            job["productionStop"] = message
            if job["tasks"][10]["status"] == "Completed":
                update_task(job, 11, "Needs attention", message, AUTO_ACTOR)
            elif job["tasks"][8]["status"] != "Completed":
                update_task(job, 8, "Needs attention", message, AUTO_ACTOR)
            else:
                update_task(job, 9, "Needs attention", message, AUTO_ACTOR)
        await save_job(job)


async def _pending_holds(settings, inventory, device_id=None):
    printers = inventory.get("printers") or []
    fiery_name = preferred_printer(printers)
    fiery = next((item for item in printers if fiery_name and item.get("name") == fiery_name), None)
    if fiery is None:
        fiery = next((item for item in printers if item.get("isFiery") and item.get("name")), None)
    if not fiery:
        return []
    # Shop-wide auto-send stays off unless the shop turned it on. An operator
    # who clicks Send to Fiery HOLD still queues that one job.
    query = {"state": "active", "fieryHold.status": "queued"}
    if (settings or {}).get("fieryAutoSend") is not True:
        query["fieryHold.explicit"] = True
    queued = await db.jobs.find(
        exclude_archived(query),
        {"_id": 0, "id": 1, "customer": 1, "cardRoute": 1, "finish": 1, "stock": 1, "fieryHold": 1},
    ).to_list(5)
    outgoing = []
    for job in queued:
        if not hold_for_device(job, device_id):
            continue
        name = (job.get("cardRoute") or {}).get("outputName") or "artwork_PRINT_READY.pdf"
        outgoing.append(
            {
                "jobId": job.get("id"),
                "jobName": job_label(job.get("customer"), job.get("id"), name),
                "filename": name,
                "preset": "London BC",
                "stock": job.get("finish") or job.get("stock") or "",
                "address": fiery.get("address") or "",
            }
        )
    return outgoing


async def heartbeat(request, payload):
    device, shop_id = await _device_for(request)
    inventory = _inventory(payload.get("inventory"))
    inventory["printers"] = normalise_reported(inventory.get("printers"))
    scanned = payload.get("scanned") is True
    with shop_scope(shop_id):
        await db.connector_devices.update_one(
            {"_id": device["_id"]},
            {"$set": {"lastSeen": now(), "status": "Connected", "inventory": inventory}},
        )
        settings = await db.settings.find_one({"kind": "settings"})
        due = scan_is_due(settings or {}, incoming_scanned=scanned)
        if settings:
            fields = {"discoveredPrinters": inventory["printers"], "discoveredAt": now()}
            if scanned:
                fields["scanFulfilledAt"] = now()
            # One Fiery becomes the business-card press. A press the shop already chose stays.
            chosen = preferred_printer(inventory["printers"])
            if chosen and not str(settings.get("printer") or "").strip():
                fields["printer"] = chosen
            await db.settings.update_one({"_id": settings["_id"]}, {"$set": fields})
            if fields.get("discoveredPrinters") is not None:
                settings = {**settings, **fields}
        await _record_holds(payload.get("holds"), settings)
        holds = await _pending_holds(settings, inventory, device.get("_id"))
    result = {"ok": True, "status": "Connected", "scan": due, "holds": holds}
    manifest = published_connector_update()
    if manifest:
        result["update"] = manifest
    return result


async def hold_pdf(request, job_id):
    """PRINT_READY bytes for a queued hold. The connector submits them. This does not print."""
    _device, shop_id = await _device_for(request)
    with shop_scope(shop_id):
        job = await get_job(job_id)
        if not job or (job.get("fieryHold") or {}).get("status") not in {"queued", "held"}:
            raise AppError("Hold file not found.", 404)
        record = latest(job, "PRINT_READY")
        if not record:
            raise AppError("Hold file not found.", 404)
        content = await file_bytes(job, record)
        name = str(record.get("name") or "artwork_PRINT_READY.pdf").replace('"', "").replace("\\", "")
        return content, name


def _base_package():
    path = os.environ.get("CONNECTOR_PACKAGE_PATH", "").strip()
    if path and os.path.isfile(path):
        with open(path, "rb") as handle:
            return handle.read()
    return b""


async def create_enrollment_package(user, website_candidates):
    """One exe. The token is in the filename and stored only as a hash."""
    shop_id = pairing_shop_id(user, current_shop_id())
    if not shop_id:
        raise AppError("Sign in to your shop.", 401)
    content = _base_package()
    if not content:
        raise AppError("The connector setup file is not on this server yet.", 503)
    created = now()
    cutoff = (datetime.now(timezone.utc) - ENROLL_WINDOW).isoformat()
    website = enrollment_website(website_candidates)
    with shop_scope(shop_id):
        recent = await db.connector_enrollments.find({"created_at": {"$gt": cutoff}}, {"created_at": 1}).to_list(20)
        if enrollment_rate_limited([item.get("created_at") for item in recent], created):
            raise AppError("Wait a few minutes before downloading the connector again.", 429)
        token = secrets.token_urlsafe(32)
        document = build_enrollment(
            user, token, created, enrollment_id=new_id(), current_shop=shop_id,
        )
        if not document:
            raise AppError("Sign in to your shop.", 401)
        document["website"] = website
        await db.connector_enrollments.insert_one(document)
    return enrollment_download(content, token)


async def revoke_enrollment(enrollment_id, user):
    moment = now()
    record = await db.connector_enrollments.find_one({"_id": enrollment_id})
    if not record or enrollment_state(record, moment) != "open":
        raise AppError("That setup download is no longer open.", 409)
    audit = list(record.get("audit") or [])
    audit.append({"at": moment, "action": "revoked", "actor": user.get("id") or ""})
    result = await db.connector_enrollments.update_one(
        {"_id": enrollment_id, "status": "open"},
        {"$set": {"status": "revoked", "revoked_at": moment, "audit": audit[-20:]}},
    )
    if not result.modified_count:
        raise AppError("That setup download is no longer open.", 409)
    return {"ok": True}


async def list_enrollments():
    moment = now()
    rows = await db.connector_enrollments.find({}, {"token_hash": 0}).to_list(20)
    public = [public_enrollment(row, moment) for row in rows]
    public.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return public


async def redeem_enrollment(payload):
    token = str(payload.get("token") or "").strip()
    device_id = _valid_id(payload.get("deviceId"))
    if len(token) < 20 or len(token) > 200:
        raise AppError(PUBLIC_ENROLL_ERROR, 409)
    digest = credential_hash(token)
    with unscoped():
        record = await db.connector_enrollments.find_one({"token_hash": digest})
    if not record or not hmac.compare_digest(str(record.get("token_hash") or ""), digest):
        raise AppError(PUBLIC_ENROLL_ERROR, 409)
    state = enrollment_state(record, now())
    if state != "open":
        raise AppError(PUBLIC_ENROLL_ERROR, 409)
    shop_id = record.get("shop_id")
    if not shop_id:
        raise AppError(PUBLIC_ENROLL_ERROR, 409)
    raw = payload.get("inventory") if isinstance(payload.get("inventory"), dict) else {
        "hostname": str(payload.get("hostname") or "")[:120],
        "printers": [],
        "fiery_rip": [],
        "hot_folders": [],
        "capabilities": ["fiery_hold"],
    }
    inventory = _inventory(raw)
    credential = secrets.token_urlsafe(48)
    moment = now()
    with shop_scope(shop_id):
        audit = list(record.get("audit") or [])
        audit.append({"at": moment, "action": "enrolled", "actor": device_id})
        result = await db.connector_enrollments.update_one(
            {"_id": record["_id"], "status": "open", "used_at": ""},
            {"$set": {"status": "used", "used_at": moment, "device_id": device_id, "audit": audit[-20:]}},
        )
        if not result.modified_count:
            raise AppError(PUBLIC_ENROLL_ERROR, 409)
        existing = await db.connector_devices.find({}, {"credential_hash": 0}).to_list(50)
        target, _mode = choose_device(existing, device_id)
        await db.connector_devices.update_one(
            {"_id": target},
            {"$set": {
                "credential_hash": credential_hash(credential),
                "enabled": True,
                "inventory": inventory,
                "lastSeen": moment,
                "status": "Connected",
            }},
            upsert=True,
        )
    return {"status": "Connected", "credential": credential}


async def _settings_for_route():
    settings = await db.settings.find_one({"kind": "settings"}) or {}
    printer = fiery_target(settings)
    if printer and not str(settings.get("printer") or "").strip():
        await db.settings.update_one({"kind": "settings"}, {"$set": {"printer": printer["name"]}})
        settings = {**settings, "printer": printer["name"]}
    return settings


async def note_prepared_route(job):
    """Record the press, imposition, and stock. Approval is still required."""
    settings = await _settings_for_route()
    job["route"] = route_for_print_order(job, settings)
    note = automatic_route_note(job, settings)
    automatic = dict(job.get("automatic") or {})
    automatic["routeNote"] = note
    try:
        ready = await readiness(job)
    except AppError as error:
        automatic["readiness"] = error.message
        record_event(job, error.message, AUTO_ACTOR)
    else:
        automatic.pop("error", None)
        automatic["readiness"] = "ready"
        automatic["hostname"] = ready.get("hostname") or ""
        record_event(job, f"{ready.get('hostname') or 'The shop computer'} is connected. This does not print.", AUTO_ACTOR)
    job["automatic"] = automatic
    record_event(job, note, AUTO_ACTOR)
    return job


async def queue_automatic_hold(job, actor):
    """Authorize this approved file onto Fiery HOLD. A failure does not print."""
    settings = await _settings_for_route()
    keep_production_route(job, settings)
    record_event(job, automatic_route_note(job, settings), AUTO_ACTOR)
    try:
        ready = await readiness(job)
    except AppError as error:
        message = f"{error.message} Nothing was printed."
        job.setdefault("automatic", {})["error"] = message
        record_event(job, message, AUTO_ACTOR)
        return job
    if ready.get("delivery") != "fiery_hold":
        message = "The shop computer cannot place this file on Fiery HOLD. Nothing was printed."
        job.setdefault("automatic", {})["error"] = message
        record_event(job, message, AUTO_ACTOR)
        return job
    printer = fiery_target(settings) or {"name": (job.get("route") or {}).get("printer") or "", "address": ""}
    try:
        stage_fiery_hold(job, ready, printer, actor, latest(job, "PRINT_READY"), now())
    except ValueError as error:
        job.setdefault("automatic", {})["error"] = str(error)
        record_event(job, str(error), AUTO_ACTOR)
        return job
    job.setdefault("automatic", {}).pop("error", None)
    record_event(job, "PRINT_READY is queued on the Fiery HOLD queue. It was not printed.", AUTO_ACTOR)
    return job


async def create_proof_link(job, user, base_url):
    if not latest(job, "PRINT_READY"):
        raise AppError("The proof is not ready yet.", 409)
    shop_id = current_shop_id() or job.get("shop_id")
    if not shop_id:
        raise AppError("Sign in to your shop.", 401)
    token = secrets.token_urlsafe(32)
    document = build_proof_link(
        job.get("id"), shop_id, token, (user or {}).get("id"), now(), link_id=new_id(),
    )
    if not document:
        raise AppError("The proof link could not be created.", 409)
    await db.proof_links.insert_one(document)
    base = str(base_url or "").rstrip("/")
    url = f"{base}/proof/{token}" if base else f"/proof/{token}"
    record_event(job, "Approval link created. Approving does not print the job.", (user or {}).get("name") or AUTO_ACTOR)
    return {"url": url, "emailed": False}


async def proof_for_token(token):
    digest = credential_hash(str(token or "").strip())
    with unscoped():
        record = await db.proof_links.find_one({"token_hash": digest})
    if not record or not hmac.compare_digest(str(record.get("token_hash") or ""), digest):
        raise AppError("This approval link is invalid or expired.", 409)
    if proof_link_state(record, now()) == "expired":
        raise AppError("This approval link is invalid or expired.", 409)
    with shop_scope(record["shop_id"]):
        job = await get_job(record["job_id"])
    if not job:
        raise AppError("This approval link is invalid or expired.", 409)
    proof = latest(job, "PRINT_READY")
    approved = (job.get("approval") or {}).get("sha") == (proof or {}).get("sha") and bool((proof or {}).get("sha"))
    return {
        "customer": job.get("customer") or "",
        "product": (job.get("spec") or {}).get("productName") or (job.get("recipe") or {}).get("name") or "Print",
        "status": "approved" if approved else "waiting",
        "sha": (proof or {}).get("sha") or "",
        "pages": int(job.get("sides") or 1),
    }


async def approve_proof_token(token, actor="Customer"):
    digest = credential_hash(str(token or "").strip())
    with unscoped():
        record = await db.proof_links.find_one({"token_hash": digest})
    if not record or not hmac.compare_digest(str(record.get("token_hash") or ""), digest):
        raise AppError("This approval link is invalid or expired.", 409)
    state = proof_link_state(record, now())
    if state == "expired":
        raise AppError("This approval link is invalid or expired.", 409)
    with shop_scope(record["shop_id"]):
        if state == "open":
            await db.proof_links.update_one(
                {"_id": record["_id"], "status": "open"},
                {"$set": {"status": "used", "used_at": now()}},
            )
        job = await get_job(record["job_id"])
        if not job:
            raise AppError("This approval link is invalid or expired.", 409)
        proof = latest(job, "PRINT_READY")
        outcome = apply_customer_approval(job, proof, actor, now())
        if outcome == "missing":
            raise AppError("The proof is not ready yet.", 409)
        if outcome == "approved":
            record_event(job, "Customer approved this exact PDF. Nothing was printed.", actor)
        if automatic_mode(await db.settings.find_one({"kind": "settings"}, {"_id": 0})):
            await queue_automatic_hold(job, actor)
        await save_job(job)
    return {"ok": True, "status": "approved"}