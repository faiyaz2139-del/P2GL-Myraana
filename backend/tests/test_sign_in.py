"""Email, shop choice, session length, and passkey register/login."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from p2g.sign_in import (
    KEEP_SIGNED_IN_SECONDS,
    PASSKEY_FAILED,
    SHORT_SESSION_SECONDS,
    begin_passkey,
    challenge_record,
    challenge_usable,
    choice_user,
    cookie_max_age,
    finish_passkey_login,
    finish_passkey_registration,
    keep_requested,
    optional_sign_in_providers,
    rotation_due,
    rp_id_from_host,
    session_deadline,
    session_span,
    sign_in_decision,
    sign_in_locked,
    ticket_is_open,
    ticket_record,
    unique_shop_slug,
)


ROOT = Path(__file__).resolve().parents[2]
START = datetime(2026, 10, 23, tzinfo=timezone.utc)
RP_ID = "myraana.com"
ORIGIN = "https://myraana.com"


def test_one_matching_shop_signs_in_and_several_shops_ask_for_a_choice():
    users = [
        {"id": "owner-a", "email": "ada@shop.test", "shop_id": "shop-a", "active": True},
        {"id": "owner-b", "email": "ada@shop.test", "shop_id": "shop-b", "active": True},
    ]
    shops = {
        "shop-a": {"name": "North Press", "status": "active"},
        "shop-b": {"name": "South Press", "status": "active"},
    }
    one = sign_in_decision(users, shops, ["owner-a"])
    assert one["kind"] == "session"
    assert one["user"]["shop_id"] == "shop-a"
    assert "shops" not in one

    both = sign_in_decision(users, shops, ["owner-a", "owner-b"])
    assert both["kind"] == "choose"
    assert [shop["name"] for shop in both["shops"]] == ["North Press", "South Press"]
    assert "slug" not in json.dumps(both["shops"])
    assert "ada@shop.test" not in json.dumps(both["shops"])
    assert both["user_ids"] == ["owner-a", "owner-b"]

    wrong = sign_in_decision(users, shops, [])
    assert wrong == {"kind": "invalid"}
    assert "North Press" not in json.dumps(wrong)

    closed = {
        "shop-a": {"name": "North Press", "status": "suspended"},
        "shop-b": {"name": "South Press", "status": "suspended"},
    }
    assert sign_in_decision(users, closed, ["owner-a", "owner-b"])["kind"] == "suspended"
    mixed = sign_in_decision(users, {**shops, "shop-b": {"name": "South Press", "status": "suspended"}}, ["owner-a", "owner-b"])
    assert mixed["kind"] == "session"
    assert mixed["user"]["id"] == "owner-a"

    ticket = ticket_record(both["user_ids"], True, START)
    assert ticket_is_open(ticket, START + timedelta(minutes=4)) is True
    assert choice_user(ticket, "owner-b", users)["shop_id"] == "shop-b"
    assert choice_user(ticket, "owner-c", users) is None
    ticket["used"] = True
    assert ticket_is_open(ticket, START) is False
    assert sign_in_locked([START.isoformat()] * 8, START + timedelta(minutes=1)) is True
    assert sign_in_locked([START.isoformat()] * 7, START) is False
    assert sign_in_locked([START.isoformat()] * 8, START + timedelta(minutes=16)) is False


def test_a_kept_session_lasts_thirty_days_and_rotates():
    assert keep_requested(None) is True
    assert keep_requested(True) is True
    assert keep_requested(False) is False
    assert keep_requested("false") is False
    assert session_span(True) == KEEP_SIGNED_IN_SECONDS == 30 * 24 * 60 * 60
    assert cookie_max_age(True) == KEEP_SIGNED_IN_SECONDS
    assert session_span(False) == SHORT_SESSION_SECONDS == 12 * 60 * 60
    assert cookie_max_age(False) is None
    deadline = session_deadline(START, True)
    assert deadline.startswith("2026-11-22")
    kept = {"keep": True, "issued": START.isoformat(), "expires": deadline}
    assert rotation_due(kept, START + timedelta(hours=11, minutes=59)) is False
    assert rotation_due(kept, START + timedelta(hours=12)) is True
    assert rotation_due({"keep": False, "issued": START.isoformat(), "expires": deadline}, START + timedelta(days=1)) is False
    expired = {"keep": True, "issued": START.isoformat(), "expires": (START + timedelta(hours=1)).isoformat()}
    assert rotation_due(expired, START + timedelta(days=2)) is False


def test_signup_slug_comes_from_the_shop_name_and_stays_unique():
    assert unique_shop_slug("North Shore Print", []) == "north-shore-print"
    assert unique_shop_slug("North Shore Print", ["north-shore-print"]) == "north-shore-print-2"
    assert unique_shop_slug("Print2Go", ["print2go", "print2go-2"]) == "print2go-3"
    assert unique_shop_slug("", []) == "shop"
    shops = (ROOT / "backend/p2g/shops.py").read_text(encoding="utf-8")
    assert "unique_shop_slug" in shops


def test_passkey_register_and_login_use_the_request_host():
    import cbor2
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from webauthn.helpers import bytes_to_base64url

    assert rp_id_from_host("myraana.com") == RP_ID
    assert rp_id_from_host("Myraana.com:443") == RP_ID
    assert rp_id_from_host("myraana.com, evil.example") == RP_ID
    assert rp_id_from_host("localhost:3000") == "localhost"
    assert rp_id_from_host("") == ""
    assert optional_sign_in_providers({"GOOGLE_CLIENT_ID": "abc"}) == {"google": False, "magicLink": False}

    options, challenge = begin_passkey(
        "register", RP_ID, user_id="user-1", user_name="ada@shop.test", display_name="Ada",
    )
    assert options["rp"]["id"] == RP_ID
    assert options["challenge"] == challenge
    stored = challenge_record("register", challenge, START, user_id="user-1", shop_id="shop-a")
    assert challenge_usable(stored, "register", START, "user-1") is True

    key = ec.generate_private_key(ec.SECP256R1())
    numbers = key.public_key().public_numbers()
    cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})
    cred_id = b"cred-id-0123456789"
    rp_hash = hashlib.sha256(RP_ID.encode()).digest()
    auth_data = rp_hash + bytes([0x41]) + (0).to_bytes(4, "big") + bytes(16) + len(cred_id).to_bytes(2, "big") + cred_id + cose
    attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
    client = json.dumps({
        "type": "webauthn.create",
        "challenge": challenge,
        "origin": ORIGIN,
        "crossOrigin": False,
    }, separators=(",", ":")).encode()
    credential = {
        "id": bytes_to_base64url(cred_id),
        "rawId": bytes_to_base64url(cred_id),
        "type": "public-key",
        "response": {
            "clientDataJSON": bytes_to_base64url(client),
            "attestationObject": bytes_to_base64url(attestation),
        },
    }
    registered = finish_passkey_registration(credential, challenge=challenge, rp_id=RP_ID, origin=ORIGIN)
    assert registered["credential_id"] == bytes_to_base64url(cred_id)
    assert registered["sign_count"] == 0
    try:
        finish_passkey_registration(credential, challenge=challenge, rp_id=RP_ID, origin="https://evil.example")
        raise AssertionError("wrong origin was accepted")
    except Exception as error:
        assert getattr(error, "message", "")
    stored["used"] = True
    assert challenge_usable(stored, "register", START, "user-1") is False

    login_options, login_challenge = begin_passkey("login", RP_ID)
    assert login_options["rpId"] == RP_ID
    login_auth = rp_hash + bytes([0x01]) + (1).to_bytes(4, "big")
    login_client = json.dumps({
        "type": "webauthn.get",
        "challenge": login_challenge,
        "origin": ORIGIN,
        "crossOrigin": False,
    }, separators=(",", ":")).encode()
    signature = key.sign(login_auth + hashlib.sha256(login_client).digest(), ec.ECDSA(hashes.SHA256()))
    assertion = {
        "id": registered["credential_id"],
        "rawId": registered["credential_id"],
        "type": "public-key",
        "response": {
            "clientDataJSON": bytes_to_base64url(login_client),
            "authenticatorData": bytes_to_base64url(login_auth),
            "signature": bytes_to_base64url(signature),
        },
    }
    signed_in = finish_passkey_login(
        assertion,
        challenge=login_challenge,
        rp_id=RP_ID,
        origin=ORIGIN,
        public_key=registered["public_key"],
        sign_count=registered["sign_count"],
    )
    assert signed_in["sign_count"] == 1
    try:
        finish_passkey_login(
            assertion,
            challenge=login_challenge,
            rp_id=RP_ID,
            origin=ORIGIN,
            public_key=registered["public_key"],
            sign_count=signed_in["sign_count"],
        )
        raise AssertionError("replayed passkey was accepted")
    except Exception as error:
        assert error.message == PASSKEY_FAILED


def test_sign_in_page_is_email_and_password():
    app = (ROOT / "frontend/src/App.js").read_text(encoding="utf-8")
    signup = (ROOT / "frontend/src/site/Marketing.js").read_text(encoding="utf-8")
    server = (ROOT / "backend/server.py").read_text(encoding="utf-8")
    assert "auth-shop-input" not in app
    assert "Only if this email is used by more than one shop" not in app
    assert 'autoComplete="username"' in app
    assert '"current-password"' in app
    assert "Keep me signed in" in app
    assert "Sign in with passkey" in app
    assert "Use Windows Hello next time?" in app
    assert "Pick your shop" in app
    assert "auth.providers?.google" in app
    assert "auth.providers?.magicLink" in app
    assert "signup-city-input" not in signup
    assert "signup-message-input" not in signup
    assert "signup-password-strength" in signup
    assert 'autoComplete="new-password"' in signup
    assert "You'll be signed in" in signup
    assert "Enter the shop address" not in server
    assert "chooseShop" in server
    assert '"/auth/passkey/login"' in server
    assert "assert_origin(request)" in server
