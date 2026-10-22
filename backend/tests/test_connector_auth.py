"""Connector credentials stay with the shop that paired them."""
import asyncio

from p2g.connector_auth import (
    credential_hash,
    legacy_credential_hash,
    legacy_shared_secret_shop,
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
