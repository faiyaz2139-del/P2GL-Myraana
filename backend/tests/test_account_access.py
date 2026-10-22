"""Password-reset and mail rules. These do not import the server or Mongo."""
import os

from p2g.account_access import (
    PUBLIC_RESET_ERROR,
    PUBLIC_RESET_REQUEST,
    public_reset_error,
    reset_is_limited,
    reset_request_message,
    reset_token_state,
    shop_allows_sign_in,
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
