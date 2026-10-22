import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from p2g.account_access import exclude_archived
from p2g.card_flow import AUTO_ACTOR, hold_failure_message, record_successful_hold
from p2g.connector_auth import (
    build_pairing_document,
    credential_hash,
    legacy_credential_hash,
    shop_for_connected_pairing,
)
from p2g.core import AppError, db, new_id, now
from p2g.fiery_hold import interpret_hold_report
from p2g.printer_discovery import normalise_reported, scan_is_due
from p2g.printers import filter_printers
from p2g.tenancy import PRINT2GO_SHOP_ID, bound_shop, current_shop_id, shop_scope, unscoped
from p2g.workflow import file_bytes, get_job, latest, record_event, save_job, update_task


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
    records = await db.connector_pairings.find(
        {},
        {"code_hash": 0, "claim_hash": 0},
    ).to_list(20)
    for record in records:
        record["id"] = record.pop("_id")
    return records


async def devices():
    records = await db.connector_devices.find(
        {},
        {"credential_hash": 0},
    ).to_list(50)
    current = datetime.now(timezone.utc)
    for record in records:
        record["id"] = record.pop("_id")
        last_seen = record.get("lastSeen")
        try:
            fresh = current - datetime.fromisoformat(last_seen) <= timedelta(seconds=90)
        except (TypeError, ValueError):
            fresh = False
        record["status"] = "Connected" if record.get("enabled") and fresh else "Offline"
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
            outcome = record_successful_hold(job, stocks)
            if outcome.get("stop"):
                job["productionStop"] = outcome["stop"]
                update_task(job, 9, "Needs attention", f"{outcome['stop']} Nothing was printed.", AUTO_ACTOR)
            else:
                job.pop("productionStop", None)
                pending = next((step for step in job.get("productionChecklist") or [] if step.get("status") != "done"), None)
                title = pending["title"] if pending else "Load Duplo DC-618 job no. 2."
                update_task(job, 9, "Waiting for operator", title, AUTO_ACTOR)
            record_event(job, "PRINT_READY is on the Fiery hold queue. It was not printed.", AUTO_ACTOR)
        else:
            hold.update({"status": "failed", "held": False, "printed": False, "error": interpreted["error"]})
            job["fieryHold"] = hold
            message = hold_failure_message(interpreted["error"])
            job["productionStop"] = message
            if job["tasks"][8]["status"] != "Completed":
                update_task(job, 8, "Needs attention", message, AUTO_ACTOR)
            else:
                update_task(job, 9, "Needs attention", message, AUTO_ACTOR)
        await save_job(job)


async def _pending_holds(settings, inventory):
    if (settings or {}).get("fieryAutoSend") is not True:
        return []
    fiery = next((item for item in inventory.get("printers") or [] if item.get("isFiery") and item.get("name")), None)
    if not fiery:
        return []
    folders = inventory.get("hot_folders") or []
    hot = ""
    if folders and isinstance(folders[0], dict):
        hot = str(folders[0].get("path") or "")[:300]
    queued = await db.jobs.find(
        exclude_archived({"state": "active", "fieryHold.status": "queued"}),
        {"_id": 0, "id": 1, "cardRoute": 1, "finish": 1, "stock": 1},
    ).to_list(5)
    outgoing = []
    for job in queued:
        name = (job.get("cardRoute") or {}).get("outputName") or "artwork_PRINT_READY.pdf"
        outgoing.append(
            {
                "jobId": job.get("id"),
                "filename": name,
                "preset": "London BC",
                "stock": job.get("finish") or job.get("stock") or "",
                "address": fiery.get("address") or "",
                "hotFolder": hot,
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
            await db.settings.update_one({"_id": settings["_id"]}, {"$set": fields})
            if fields.get("discoveredPrinters") is not None:
                settings = {**settings, **fields}
        await _record_holds(payload.get("holds"), settings)
        holds = await _pending_holds(settings, inventory)
    return {"ok": True, "status": "Connected", "scan": due, "holds": holds}


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