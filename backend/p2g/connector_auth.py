"""How a connector proves which shop it belongs to.

New pairing codes and device credentials are a plain SHA-256. That path does
not need CONNECTOR_SECRET. The older HMAC is accepted only for Print2Go, which
is the shop the shared secret was installed for.
"""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from p2g.tenancy import PRINT2GO_SHOP_ID, bound_shop


# A paired computer stays Connected until this long after its last heartbeat.
OFFLINE_AFTER = timedelta(seconds=90)
# The admin who just created a code is still on Shop settings during this window.
AUTO_APPROVE_WITHIN = timedelta(minutes=2)


def credential_hash(value):
    return hashlib.sha256(str(value or "").encode()).hexdigest()


def legacy_credential_hash(value, secret):
    secret = str(secret or "")
    if not secret:
        return None
    return hmac.new(secret.encode(), str(value or "").encode(), hashlib.sha256).hexdigest()


def select_device(devices, credential, secret):
    """Return (device, kind) where kind is current or legacy.

    A legacy HMAC match is ignored unless that device belongs to Print2Go.
    A missing shop_id on a legacy device is the original Print2Go install.
    """
    plain = credential_hash(credential)
    for device in devices or []:
        if device.get("enabled", True) and device.get("credential_hash") == plain:
            return device, "current"
    old = legacy_credential_hash(credential, secret)
    if not old:
        return None, None
    for device in devices or []:
        if not device.get("enabled", True) or device.get("credential_hash") != old:
            continue
        owner = device.get("shop_id") or PRINT2GO_SHOP_ID
        if owner == PRINT2GO_SHOP_ID:
            return device, "legacy"
    return None, None


def legacy_shared_secret_shop(requested_shop):
    """The bearer CONNECTOR_SECRET path is Print2Go only."""
    return bound_shop(PRINT2GO_SHOP_ID, requested_shop)


def pairing_shop_id(user, current_shop=None):
    """Shop that owns a new pairing code.

    The creating user's shop wins. A request that is already in that shop
    passes the same id as current_shop. A missing shop stays missing so the
    caller can refuse it. Print2Go is never filled in for another shop.
    """
    shop = str((user or {}).get("shop_id") or "").strip()
    if not shop:
        shop = str(current_shop or "").strip()
    return shop or None


def build_pairing_document(user, *, pairing_id, code_hash, expires_at, created_at, current_shop=None):
    """Pairing row written by create_pairing. shop_id is the creating user's shop."""
    shop_id = pairing_shop_id(user, current_shop)
    if not shop_id or not user or not user.get("id"):
        return None
    return {
        "_id": pairing_id,
        "status": "Searching",
        "code_hash": code_hash,
        "expires_at": expires_at,
        "created_by": user["id"],
        "created_at": created_at,
        "shop_id": shop_id,
    }


def _as_utc(value):
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


def last_seen_phrase(last_seen, at=None):
    """How long ago a heartbeat arrived, for the readiness notice."""
    moment = _as_utc(at) or datetime.now(timezone.utc)
    seen = _as_utc(last_seen)
    if seen is None:
        return ""
    seconds = int((moment - seen).total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        unit = "second" if seconds == 1 else "seconds"
        return f"{seconds} {unit} ago"
    minutes = seconds // 60
    if minutes < 60:
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit} ago"
    hours = minutes // 60
    unit = "hour" if hours == 1 else "hours"
    return f"{hours} {unit} ago"


def device_capabilities(device):
    inventory = (device or {}).get("inventory") if isinstance(device, dict) else {}
    raw = (inventory or {}).get("capabilities")
    if raw is None and isinstance(device, dict):
        raw = device.get("capabilities")
    if isinstance(raw, str):
        raw = [raw]
    found = []
    for item in raw or []:
        text = str(item or "").strip().lower().replace("-", "_")
        if text and text not in found:
            found.append(text)
    return found[:12]


def normalise_capabilities(value):
    return device_capabilities({"capabilities": value})


def folder_agent_configured(agent):
    """A file-drop agent exists only when it has a folder to write into."""
    if not isinstance(agent, dict):
        return False
    return bool(str(agent.get("destination") or "").strip())


def _device_id(device):
    return str((device or {}).get("id") or (device or {}).get("_id") or "")


def _device_hostname(device):
    inventory = (device or {}).get("inventory") or {}
    return str(inventory.get("hostname") or "").strip() or "The shop computer"


def select_ready_connector(devices, agent=None, at=None):
    """The connector that may stage a PRINT_READY file.

    A paired device is ready when it is enabled and its heartbeat is under 90
    seconds old. That is the same rule as Shop settings. A writable folder is
    required only for a configured file-drop agent, and only when no paired
    device is fresh. The Windows connector places the file on Fiery HOLD itself,
    so a missing folder does not block it.
    """
    moment = _as_utc(at) or datetime.now(timezone.utc)
    fresh = []
    for device in devices or []:
        if not isinstance(device, dict) or device.get("enabled") is False:
            continue
        if connector_presence(device.get("lastSeen"), True, moment) != "Connected":
            continue
        fresh.append(device)
    fresh.sort(key=lambda device: str(device.get("lastSeen") or ""), reverse=True)
    fiery = [device for device in fresh if "fiery_hold" in device_capabilities(device)]
    chosen = (fiery or fresh or [None])[0]
    if chosen:
        capabilities = device_capabilities(chosen)
        # A paired computer that has not reported a capability yet still stages
        # to Fiery HOLD. Do not demand a writable folder for that path.
        delivery = "folder" if capabilities == ["pdf_hot_folder"] else "fiery_hold"
        if "fiery_hold" not in capabilities and delivery == "fiery_hold":
            capabilities = capabilities + ["fiery_hold"]
        return {
            "kind": "device",
            "id": _device_id(chosen),
            "hostname": _device_hostname(chosen),
            "lastSeen": chosen.get("lastSeen") or "",
            "capabilities": capabilities,
            "delivery": delivery,
            "destination": "",
            "writable": False,
        }
    if not folder_agent_configured(agent):
        return None
    fresh_agent = connector_presence(agent.get("lastSeen"), True, moment) == "Connected"
    if fresh_agent and agent.get("writable"):
        return {
            "kind": "folder",
            "id": "",
            "hostname": "The shop computer",
            "lastSeen": agent.get("lastSeen") or "",
            "capabilities": ["pdf_hot_folder"],
            "delivery": "folder",
            "destination": str(agent.get("destination") or "").strip(),
            "writable": True,
        }
    return None


def stale_connector_message(devices, at=None):
    """Name a paired computer whose heartbeat is older than 90 seconds."""
    candidates = [
        device for device in devices or []
        if isinstance(device, dict) and device.get("enabled") is not False
    ]
    if not candidates:
        return ""
    moment = _as_utc(at) or datetime.now(timezone.utc)
    candidates.sort(key=lambda device: str(device.get("lastSeen") or ""), reverse=True)
    device = candidates[0]
    if connector_presence(device.get("lastSeen"), True, moment) == "Connected":
        return ""
    host = _device_hostname(device)
    phrase = last_seen_phrase(device.get("lastSeen"), moment)
    when = f"Last seen {phrase}. " if phrase else "It has not checked in. "
    return (
        f"{host} is not connected. {when}"
        f"Open MyraanaConnector on {host}. It runs in the tray. This step does not print."
    )


def hold_for_device(job, device_id):
    """A hold with no device stays available. A named device only takes its own."""
    owner = str(((job or {}).get("fieryHold") or {}).get("deviceId") or "")
    return not owner or not device_id or owner == str(device_id)


def connector_presence(last_seen, enabled=True, at=None):
    """Connected while a heartbeat is at most 90 seconds old. Otherwise Offline."""
    if not enabled:
        return "Offline"
    moment = _as_utc(at) or datetime.now(timezone.utc)
    seen = _as_utc(last_seen)
    if seen is None or moment - seen > OFFLINE_AFTER:
        return "Offline"
    return "Connected"


def manual_approval_required(created_at, device_id, existing_device_ids, at=None):
    """A click is required once the code is older than 2 minutes, or the computer is new.

    A shop with no connector yet, or the same device id pairing again, can be
    approved by the browser session that is waiting on the fresh code.
    """
    moment = _as_utc(at) or datetime.now(timezone.utc)
    created = _as_utc(created_at)
    if created is None or moment - created > AUTO_APPROVE_WITHIN:
        return True
    known = [str(item) for item in (existing_device_ids or []) if item]
    if known and str(device_id or "") not in known:
        return True
    return False


def newest_found_pairing(records):
    """The Found pairing Approve should use. Newest created_at wins."""
    found = [record for record in records or [] if record.get("status") == "Found" and (record.get("id") or record.get("_id"))]
    found.sort(key=lambda record: str(record.get("created_at") or ""), reverse=True)
    return found[0] if found else None


def _pairing_expired(record, at):
    moment = _as_utc(at) or datetime.now(timezone.utc)
    expires = _as_utc((record or {}).get("expires_at"))
    if expires is None:
        return True
    return expires <= moment


async def list_open_pairings(collection, at):
    """Mark stale Searching and Found codes Expired, then return the live ones, newest first.

    An expired Found row must not stay in the list. Approve on that row returns
    409, which is what made the Shop settings button look broken.
    """
    moment = (_as_utc(at) or datetime.now(timezone.utc)).isoformat()
    for _ in range(20):
        records = await collection.find({"status": {"$in": ["Searching", "Found"]}}).to_list(100)
        stale = [
            record["_id"]
            for record in records
            if record.get("_id") and _pairing_expired(record, moment)
        ]
        if not stale:
            break
        result = await collection.update_many(
            {"_id": {"$in": stale}},
            {"$set": {"status": "Expired"}},
        )
        if not getattr(result, "modified_count", 0):
            break
        if len(records) < 100:
            break
    records = await collection.find(
        {"status": {"$in": ["Searching", "Found"]}},
        {"code_hash": 0, "claim_hash": 0},
    ).to_list(100)
    visible = []
    for record in records:
        if _pairing_expired(record, moment):
            continue
        record["id"] = record.pop("_id", None) or record.get("id")
        visible.append(record)
    visible.sort(key=lambda record: str(record.get("created_at") or ""), reverse=True)
    return visible[:20]


def shop_for_connected_pairing(pairing):
    """Shop that receives the connector device once the code is approved.

    A missing shop_id is not Print2Go. Callers must refuse that pairing
    instead of attaching the computer to the wrong shop.
    """
    shop = str((pairing or {}).get("shop_id") or "").strip()
    return shop or None
