"""Rules for password reset and shop sign-in. No database and no core import.

The public reset reply is the same whether or not the address exists.
A bad, used, or expired token uses one error so those cases are not distinct.
"""

PUBLIC_RESET_REQUEST = (
    "If that shop has an account for this email, we sent reset instructions."
)
PUBLIC_RESET_ERROR = "This reset link is invalid or expired."
RESET_ATTEMPT_LIMIT = 5


def reset_request_message(found=None):
    """Ignore whether an account was found. Callers must not branch on it."""
    return PUBLIC_RESET_REQUEST


def reset_token_state(record, now_iso):
    if not record or record.get("used"):
        return "invalid"
    if str(record.get("expires") or "") <= str(now_iso or ""):
        return "expired"
    return "ok"


def public_reset_error(state=None):
    return PUBLIC_RESET_ERROR


def reset_is_limited(count):
    try:
        attempts = int(count or 0)
    except (TypeError, ValueError):
        attempts = RESET_ATTEMPT_LIMIT
    return attempts >= RESET_ATTEMPT_LIMIT


def shop_allows_sign_in(status):
    """Missing status is the original Print2Go row, which stays active."""
    return status in (None, "", "active")
