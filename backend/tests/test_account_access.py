"""Password-reset and mail rules. These do not import the server or Mongo."""
import os

from p2g.account_access import (
    PUBLIC_RESET_ERROR,
    PUBLIC_RESET_REQUEST,
    SUSPENDED_MESSAGE,
    directory_keys,
    public_lead,
    public_reset_error,
    reset_is_limited,
    reset_request_message,
    reset_token_state,
    shop_allows_sign_in,
    shop_directory_row,
    sign_in_denial,
)
from p2g.mail import email_provider


NOW = "2026-10-22T12:00:00+00:00"


def test_reset_token_expiry_reuse_and_missing():
    fresh = {"used": False, "expires": "2026-10-22T13:00:00+00:00"}
    assert reset_token_state(fresh, NOW) == "ok"
    assert reset_token_state({"used": False, "expires": NOW}, NOW) == "expired"
    assert reset_token_state({"used": False, "expires": "2026-10-22T11:00:00+00:00"}, NOW) == "expired"
    assert reset_token_state({"used": True, "expires": "2026-10-22T13:00:00+00:00"}, NOW) == "invalid"
    assert reset_token_state(None, NOW) == "invalid"
    assert reset_token_state({}, NOW) == "invalid"
    assert public_reset_error("invalid") == public_reset_error("expired") == PUBLIC_RESET_ERROR
    assert public_reset_error("missing") == PUBLIC_RESET_ERROR
    assert "not found" not in PUBLIC_RESET_ERROR.lower()
    assert "expired" not in public_reset_error("invalid").lower() or public_reset_error("invalid") == public_reset_error("expired")


def test_reset_request_does_not_enumerate():
    found = reset_request_message(True)
    missing = reset_request_message(False)
    assert found == missing == PUBLIC_RESET_REQUEST
    lowered = found.lower()
    assert "not found" not in lowered
    assert "does not exist" not in lowered
    assert "no account" not in lowered


def test_reset_rate_limit_blocks_the_sixth_attempt():
    assert reset_is_limited(0) is False
    assert reset_is_limited(4) is False
    assert reset_is_limited(5) is True
    assert reset_is_limited(6) is True


def test_email_provider_defaults_to_log():
    previous = os.environ.pop("EMAIL_PROVIDER", None)
    try:
        assert email_provider() == "log"
        os.environ["EMAIL_PROVIDER"] = "not-a-provider"
        assert email_provider() == "log"
        os.environ["EMAIL_PROVIDER"] = "off"
        assert email_provider() == "off"
        os.environ["EMAIL_PROVIDER"] = "SMTP"
        assert email_provider() == "smtp"
    finally:
        if previous is None:
            os.environ.pop("EMAIL_PROVIDER", None)
        else:
            os.environ["EMAIL_PROVIDER"] = previous


def test_shop_sign_in_allows_only_an_active_shop():
    assert shop_allows_sign_in("active") is True
    assert shop_allows_sign_in(None) is True
    assert shop_allows_sign_in("") is True
    assert shop_allows_sign_in("suspended") is False
    assert shop_allows_sign_in("pending") is False
    assert sign_in_denial("active", True) is None
    assert sign_in_denial(None, True) is None
    assert sign_in_denial("suspended", True) == SUSPENDED_MESSAGE
    assert sign_in_denial("pending", True) == SUSPENDED_MESSAGE
    assert sign_in_denial("suspended", False) is None


def test_platform_directory_counts_shops_without_job_contents():
    row = shop_directory_row(
        {
            "_id": "shop-north",
            "name": "North Press",
            "slug": "north-press",
            "status": "suspended",
            "created": "2026-10-01T00:00:00+00:00",
            "customer": "Ada",
            "files": ["secret.pdf"],
            "messages": ["hello"],
        },
        3,
        9,
        "2026-10-22T00:00:00+00:00",
    )
    assert tuple(row) == directory_keys()
    assert row["users"] == 3
    assert row["jobs"] == 9
    assert row["status"] == "suspended"
    assert row["lastActivity"] == "2026-10-22T00:00:00+00:00"
    assert "Ada" not in row.values()
    assert "secret.pdf" not in str(row)
    missing = shop_directory_row({"_id": "print2go", "name": "Print2Go", "slug": "print2go"}, 1, 0, None)
    assert missing["status"] == "active"


def test_public_lead_omits_a_password():
    lead = public_lead({
        "id": "lead-1",
        "email": "owner@north.test",
        "shop": "North Press",
        "name": "Ada",
        "city": "London",
        "message": "Ready",
        "intent": "signup",
        "created": "2026-10-22T00:00:00+00:00",
        "password": "not-stored",
    })
    assert "password" not in lead
    assert "not-stored" not in lead.values()
    assert lead["email"] == "owner@north.test"
