"""Connector credentials stay with the shop that paired them."""
import asyncio

from datetime import datetime, timedelta, timezone
from pathlib import Path

from p2g.connector_auth import (
    connector_presence,
    credential_hash,
    hold_for_device,
    last_seen_phrase,
    legacy_credential_hash,
    legacy_shared_secret_shop,
    list_open_pairings,
    manual_approval_required,
    newest_found_pairing,
    select_device,
    select_ready_connector,
    stale_connector_message,
)
from p2g.tenancy import PRINT2GO_SHOP_ID, TenantDatabase, TenantScopeError, shop_scope


def test_new_credential_hash_does_not_use_the_shared_secret():
    secret = "print2go-only-secret"
    assert credential_hash("AB23CD45") != legacy_credential_hash("AB23CD45", secret)
    assert legacy_credential_hash("AB23CD45", "") is None
    assert credential_hash("AB23CD45") == credential_hash("AB23CD45")


def test_legacy_hmac_is_accepted_only_for_print2go():
    secret = "print2go-only-secret"
    devices = [
        {
            "_id": "shop-b-current",
            "credential_hash": credential_hash("new-cred"),
            "shop_id": "shop-b",
            "enabled": True,
        },
        {
            "_id": "shop-b-legacy",
            "credential_hash": legacy_credential_hash("old-cred", secret),
            "shop_id": "shop-b",
            "enabled": True,
        },
        {
            "_id": "print2go-legacy",
            "credential_hash": legacy_credential_hash("p2g-cred", secret),
            "shop_id": PRINT2GO_SHOP_ID,
            "enabled": True,
        },
        {
            "_id": "print2go-unscoped-legacy",
            "credential_hash": legacy_credential_hash("missing-shop", secret),
            "enabled": True,
        },
    ]
    found, kind = select_device(devices, "new-cred", secret)
    assert found["_id"] == "shop-b-current"
    assert kind == "current"
    assert select_device(devices, "old-cred", secret) == (None, None)
    found, kind = select_device(devices, "p2g-cred", secret)
    assert found["_id"] == "print2go-legacy"
    assert kind == "legacy"
    found, kind = select_device(devices, "missing-shop", secret)
    assert found["_id"] == "print2go-unscoped-legacy"
    assert kind == "legacy"
    assert select_device(devices, "missing-shop", "") == (None, None)


def test_shared_connector_secret_rejects_another_shop():
    assert legacy_shared_secret_shop(None) == PRINT2GO_SHOP_ID
    assert legacy_shared_secret_shop("") == PRINT2GO_SHOP_ID
    assert legacy_shared_secret_shop(PRINT2GO_SHOP_ID) == PRINT2GO_SHOP_ID
    try:
        legacy_shared_secret_shop("shop-b")
        raise AssertionError("shared secret must stay on Print2Go")
    except TenantScopeError as error:
        assert error.code == "connector-shop"


def test_london_pairing_keeps_that_shop():
    """A print2go-london admin's code must not fall back to Print2Go."""
    from pathlib import Path

    from p2g.connector_auth import build_pairing_document, shop_for_connected_pairing

    user = {"id": "admin-london", "role": "admin", "shop_id": "print2go-london"}
    document = build_pairing_document(
        user,
        pairing_id="pair-london",
        code_hash="hash",
        expires_at="2099-01-01T00:00:00+00:00",
        created_at="2026-10-22T00:00:00+00:00",
        current_shop=None,
    )
    assert document["shop_id"] == "print2go-london"
    assert document["created_by"] == "admin-london"
    assert shop_for_connected_pairing(document) == "print2go-london"
    same_scope = build_pairing_document(
        user,
        pairing_id="pair-london-scoped",
        code_hash="hash",
        expires_at="2099-01-01T00:00:00+00:00",
        created_at="2026-10-22T00:00:00+00:00",
        current_shop="print2go-london",
    )
    assert same_scope["shop_id"] == "print2go-london"
    # The user's shop wins even if the request scope still says Print2Go.
    # The tenant write then rejects the foreign shop instead of storing Print2Go.
    preferred = build_pairing_document(
        user,
        pairing_id="pair-london-preferred",
        code_hash="hash",
        expires_at="2099-01-01T00:00:00+00:00",
        created_at="2026-10-22T00:00:00+00:00",
        current_shop=PRINT2GO_SHOP_ID,
    )
    assert preferred["shop_id"] == "print2go-london"
    assert shop_for_connected_pairing({}) is None
    assert shop_for_connected_pairing({"shop_id": ""}) is None
    assert build_pairing_document(
        {"id": "nobody"},
        pairing_id="pair-missing",
        code_hash="hash",
        expires_at="2099-01-01T00:00:00+00:00",
        created_at="2026-10-22T00:00:00+00:00",
        current_shop=None,
    ) is None
    source = Path(__file__).resolve().parents[1] / "p2g" / "connector_pairing.py"
    text = source.read_text(encoding="utf-8")
    assert "build_pairing_document(" in text
    assert "shop_for_connected_pairing(pairing)" in text
    assert 'pairing.get("shop_id") or PRINT2GO_SHOP_ID' not in text


def test_pairing_created_for_one_shop_is_hidden_from_another():
    asyncio.run(_pairing_created_for_one_shop_is_hidden_from_another())


async def _pairing_created_for_one_shop_is_hidden_from_another():
    import test_tenancy

    database = TenantDatabase(test_tenancy.MemoryDB())
    with shop_scope("shop-a"):
        await database.connector_pairings.insert_one({
            "_id": "pair-a",
            "code_hash": credential_hash("CODEAAAA"),
            "status": "Searching",
        })
    with shop_scope("shop-b"):
        assert await database.connector_pairings.find_one({"_id": "pair-a"}) is None
        await database.connector_pairings.insert_one({
            "_id": "pair-b",
            "code_hash": credential_hash("CODEBBBB"),
            "status": "Searching",
        })
        listed = await database.connector_pairings.find({}).to_list(10)
        assert [row["_id"] for row in listed] == ["pair-b"]


def test_connector_stays_online_until_ninety_seconds():
    at = datetime(2026, 10, 22, 21, 53, tzinfo=timezone.utc)
    fresh = (at - timedelta(seconds=90)).isoformat()
    stale = (at - timedelta(seconds=91)).isoformat()
    assert connector_presence(fresh, True, at) == "Connected"
    assert connector_presence(stale, True, at) == "Offline"
    assert connector_presence(fresh, False, at) == "Offline"
    assert connector_presence("", True, at) == "Offline"


def test_fresh_same_computer_does_not_need_a_manual_approve():
    at = datetime(2026, 10, 22, 22, 14, tzinfo=timezone.utc)
    created = (at - timedelta(seconds=30)).isoformat()
    edge = (at - timedelta(minutes=2)).isoformat()
    older = (at - timedelta(minutes=2, seconds=1)).isoformat()
    assert manual_approval_required(created, "device-p2gl-2", [], at) is False
    assert manual_approval_required(created, "device-p2gl-2", ["device-p2gl-2"], at) is False
    assert manual_approval_required(edge, "device-p2gl-2", ["device-p2gl-2"], at) is False
    assert manual_approval_required(created, "other-device", ["device-p2gl-2"], at) is True
    assert manual_approval_required(older, "device-p2gl-2", ["device-p2gl-2"], at) is True
    assert manual_approval_required(older, "new-device", [], at) is True


def test_expired_found_pairing_is_not_the_approve_target():
    asyncio.run(_expired_found_pairing_is_not_the_approve_target())


async def _expired_found_pairing_is_not_the_approve_target():
    """Live shop: 3e6fe8ac was still Found after 22:08, and 70125725 was the fresh claim."""
    import test_tenancy

    collection = test_tenancy.MemoryDB().connector_pairings
    await collection.insert_one({
        "_id": "3e6fe8ac",
        "status": "Found",
        "expires_at": "2026-10-22T22:08:00+00:00",
        "created_at": "2026-10-22T21:58:00+00:00",
        "code_hash": "secret-old",
        "claim_hash": "claim-old",
        "inventory": {"hostname": "P2GL-2"},
    })
    await collection.insert_one({
        "_id": "70125725",
        "status": "Found",
        "expires_at": "2026-10-22T22:23:00+00:00",
        "created_at": "2026-10-22T22:13:00+00:00",
        "code_hash": "secret-new",
        "claim_hash": "claim-new",
        "device_id": "device-p2gl-2",
        "inventory": {"hostname": "P2GL-2"},
    })
    await collection.insert_one({
        "_id": "still-searching",
        "status": "Searching",
        "expires_at": "2026-10-22T22:20:00+00:00",
        "created_at": "2026-10-22T22:10:00+00:00",
        "code_hash": "secret-search",
    })
    await collection.insert_one({
        "_id": "search-old",
        "status": "Searching",
        "expires_at": "2026-10-22T22:00:00+00:00",
        "created_at": "2026-10-22T21:50:00+00:00",
        "code_hash": "secret-stale",
    })
    rows = await list_open_pairings(collection, "2026-10-22T22:13:30+00:00")
    assert [row["id"] for row in rows] == ["70125725", "still-searching"]
    assert "code_hash" not in rows[0]
    assert "claim_hash" not in rows[0]
    target = newest_found_pairing(rows)
    assert target["id"] == "70125725"
    assert target["id"] != "3e6fe8ac"
    stored = {doc["_id"]: doc["status"] for doc in collection.docs}
    assert stored["3e6fe8ac"] == "Expired"
    assert stored["search-old"] == "Expired"
    assert stored["70125725"] == "Found"
    assert stored["still-searching"] == "Searching"
    pairing_source = Path(__file__).resolve().parents[1] / "p2g" / "connector_pairing.py"
    text = pairing_source.read_text(encoding="utf-8")
    assert "list_open_pairings(" in text
    assert 'record["status"] = connector_presence(' in text
    app = Path(__file__).resolve().parents[2] / "frontend" / "src" / "App.js"
    ui = app.read_text(encoding="utf-8")
    assert "PAIRING_POLL_MS = 3000" in ui
    assert "newestFoundPairing" in ui
    assert "approve(item.id)" in ui
    assert "connector-approve-error" in ui
    assert "Open MyraanaConnector on " in ui
    assert "It runs in the tray." in ui
    assert "Connected to ${host}" in ui
    assert "pairings[0]" not in ui


def _p2gl(at, seconds_ago, capabilities=None, enabled=True):
    seen = (at - timedelta(seconds=seconds_ago)).isoformat()
    device = {
        "_id": "device-p2gl-2",
        "enabled": enabled,
        "lastSeen": seen,
        "inventory": {"hostname": "P2GL-2"},
    }
    if capabilities is not None:
        device["inventory"]["capabilities"] = capabilities
    return device


def test_paired_device_is_ready_without_a_writable_folder():
    """P2GL-2 heartbeats every few seconds. Step 11 must not demand a drop folder."""
    at = datetime(2026, 10, 22, 22, 30, tzinfo=timezone.utc)
    ready = select_ready_connector([_p2gl(at, 8, ["fiery_hold"])], agent=None, at=at)
    assert ready["kind"] == "device"
    assert ready["id"] == "device-p2gl-2"
    assert ready["hostname"] == "P2GL-2"
    assert ready["delivery"] == "fiery_hold"
    assert ready["writable"] is False
    assert ready["destination"] == ""
    assert "fiery_hold" in ready["capabilities"]


def test_live_connector_without_capabilities_still_stages_to_fiery_hold():
    at = datetime(2026, 10, 22, 22, 30, tzinfo=timezone.utc)
    ready = select_ready_connector([_p2gl(at, 8)], agent=None, at=at)
    assert ready["kind"] == "device"
    assert ready["hostname"] == "P2GL-2"
    assert ready["delivery"] == "fiery_hold"
    assert ready["writable"] is False
    assert "fiery_hold" in ready["capabilities"]


def test_stale_paired_device_is_named_and_not_ready():
    at = datetime(2026, 10, 22, 22, 30, tzinfo=timezone.utc)
    stale = _p2gl(at, 91, ["fiery_hold"])
    assert select_ready_connector([stale], agent=None, at=at) is None
    message = stale_connector_message([stale], at)
    assert "P2GL-2 is not connected." in message
    assert "Open MyraanaConnector on P2GL-2." in message
    assert "Last seen 1 minute ago." in message
    edge = _p2gl(at, 90, ["fiery_hold"])
    assert select_ready_connector([edge], agent=None, at=at)["hostname"] == "P2GL-2"


def test_writable_folder_applies_only_to_a_configured_file_drop_agent():
    at = datetime(2026, 10, 22, 22, 30, tzinfo=timezone.utc)
    fresh = (at - timedelta(seconds=8)).isoformat()
    bare = {"writable": True, "lastSeen": fresh}
    assert select_ready_connector([], bare, at) is None
    folder = {"writable": True, "lastSeen": fresh, "destination": r"C:\hotfolder"}
    ready = select_ready_connector([], folder, at)
    assert ready["kind"] == "folder"
    assert ready["delivery"] == "folder"
    assert ready["writable"] is True
    assert ready["destination"] == r"C:\hotfolder"
    closed = {"writable": False, "lastSeen": fresh, "destination": r"C:\hotfolder"}
    assert select_ready_connector([], closed, at) is None
    old = {"writable": True, "lastSeen": (at - timedelta(seconds=91)).isoformat(), "destination": r"C:\hotfolder"}
    assert select_ready_connector([], old, at) is None
    device = _p2gl(at, 8, ["fiery_hold"])
    chosen = select_ready_connector([device], closed, at)
    assert chosen["kind"] == "device"
    assert chosen["delivery"] == "fiery_hold"
    assert chosen["writable"] is False


def test_fiery_hold_device_is_preferred_and_a_drop_folder_device_stays_a_folder():
    at = datetime(2026, 10, 22, 22, 30, tzinfo=timezone.utc)
    newer = _p2gl(at, 2)
    newer["_id"] = "device-other"
    newer["inventory"]["hostname"] = "OTHER-PC"
    newer["inventory"]["capabilities"] = ["pdf_hot_folder"]
    fiery = _p2gl(at, 20, ["fiery_hold"])
    ready = select_ready_connector([newer, fiery], at=at)
    assert ready["id"] == "device-p2gl-2"
    assert ready["delivery"] == "fiery_hold"
    only_folder = select_ready_connector([newer], at=at)
    assert only_folder["delivery"] == "folder"
    assert only_folder["writable"] is False
    disabled = _p2gl(at, 4, ["fiery_hold"], enabled=False)
    assert select_ready_connector([disabled], at=at) is None


def test_last_seen_phrase_and_hold_stay_with_the_paired_device():
    at = datetime(2026, 10, 22, 22, 30, tzinfo=timezone.utc)
    assert last_seen_phrase(at - timedelta(seconds=8), at) == "8 seconds ago"
    assert last_seen_phrase(at - timedelta(seconds=1), at) == "1 second ago"
    assert last_seen_phrase("", at) == ""
    open_hold = {"fieryHold": {"status": "queued", "explicit": True, "deviceId": ""}}
    pinned = {"fieryHold": {"status": "queued", "explicit": True, "deviceId": "device-p2gl-2"}}
    assert hold_for_device(open_hold, "device-p2gl-2") is True
    assert hold_for_device(open_hold, "device-other") is True
    assert hold_for_device(pinned, "device-p2gl-2") is True
    assert hold_for_device(pinned, "device-other") is False


def test_readiness_and_staging_use_the_paired_device():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / "backend" / "p2g" / "workflow.py").read_text(encoding="utf-8")
    start = workflow.index("async def readiness")
    body = workflow[start:]
    assert "select_ready_connector(" in body
    assert "connector_devices" in body
    assert 'agent.get("writable")' not in body
    assert "destination" in body
    pairing = (root / "backend" / "p2g" / "connector_pairing.py").read_text(encoding="utf-8")
    assert "normalise_capabilities" in pairing
    assert "hold_for_device" in pairing
    assert 'job["tasks"][10]["status"] == "Completed"' in pairing
    server = (root / "backend" / "server.py").read_text(encoding="utf-8")
    assert 'ready.get("delivery") == "fiery_hold"' in server
    assert '"explicit": True' in server
    assert 'deviceId": ready.get("id")' in server
    ui = (root / "frontend" / "src" / "App.js").read_text(encoding="utf-8")
    assert 'data-testid="readiness-connector-notice"' in ui
    assert "Last seen " in ui
    assert "readinessNotice(settings)" in ui
