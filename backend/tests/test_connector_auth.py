"""Connector credentials stay with the shop that paired them."""
import asyncio

from datetime import datetime, timedelta, timezone
from pathlib import Path

from p2g.connector_auth import (
    connector_presence,
    credential_hash,
    legacy_credential_hash,
    legacy_shared_secret_shop,
    list_open_pairings,
    manual_approval_required,
    newest_found_pairing,
    select_device,
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
