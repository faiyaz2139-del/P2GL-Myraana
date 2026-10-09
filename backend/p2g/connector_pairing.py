import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from p2g.core import AppError, db, new_id, now


def _secret():
    secret = os.environ.get("CONNECTOR_SECRET")
    if not secret:
        raise AppError("Preview connector pairing is not configured.", 503)
    return secret


def _digest(value):
    return hmac.new(_secret().encode(), value.encode(), hashlib.sha256).hexdigest()


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
    result["hostname"] = str(value.get("hostname", ""))[:120]
    return result


async def create_pairing(user):
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    pairing = {
        "_id": new_id(),
        "status": "Searching",
        "code_hash": _digest(code),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "created_by": user["id"],
        "created_at": now(),
    }
    await db.connector_pairings.insert_one(pairing)
    return {"id": pairing["_id"], "code": code, "expiresIn": 600}


async def claim_pairing(payload):
    code = str(payload.get("code") or "").strip().upper()
    device_id = _valid_id(payload.get("deviceId"))
    claim = str(payload.get("claimSecret") or "")
    if len(code) != 8 or len(claim) < 32 or len(claim) > 160:
        raise AppError("Pairing request is invalid.", 400)
    pairing = await db.connector_pairings.find_one(
        {"code_hash": _digest(code), "status": "Searching"}
    )
    if not pairing or pairing["expires_at"] <= now():
        raise AppError("Pairing code is invalid or expired.", 409)
    result = await db.connector_pairings.update_one(
        {"_id": pairing["_id"], "status": "Searching"},
        {"$set": {"status": "Found", "device_id": device_id, "claim_hash": _digest(claim),
                  "inventory": _inventory(payload.get("inventory")), "claimed_at": now()}},
    )
    if not result.modified_count:
        raise AppError("Pairing is no longer available.", 409)
    return {"id": pairing["_id"], "status": "Found"}


async def pairing_status(pairing_id, claim):
    pairing = await db.connector_pairings.find_one({"_id": pairing_id}, {"_id": 0})
    if not pairing or pairing["expires_at"] <= now():
        raise AppError("Pairing is invalid or expired.", 409)
    if not hmac.compare_digest(pairing.get("claim_hash", ""), _digest(claim)):
        raise AppError("Connector claim is invalid.", 401)
    if pairing["status"] != "Connected":
        return {"status": pairing["status"]}
    credential = secrets.token_urlsafe(48)
    await db.connector_devices.update_one(
        {"_id": pairing["device_id"]},
        {"$set": {"credential_hash": _digest(credential), "enabled": True,
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


async def heartbeat(request, payload):
    credential = request.headers.get("authorization", "").removeprefix("Bearer ")
    device = await db.connector_devices.find_one({"credential_hash": _digest(credential), "enabled": True})
    if not device:
        raise AppError("Connector authentication failed.", 401)
    await db.connector_devices.update_one(
        {"_id": device["_id"]},
        {"$set": {"lastSeen": now(), "status": "Connected", "inventory": _inventory(payload.get("inventory"))}},
    )
    return {"ok": True, "status": "Connected"}