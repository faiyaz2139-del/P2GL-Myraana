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


SUSPENDED_MESSAGE = "This shop is suspended."
_DIRECTORY_KEYS = ("id", "name", "slug", "status", "created", "users", "jobs", "lastActivity")


def shop_allows_sign_in(status):
    """Missing status is the original Print2Go row, which stays active."""
    return status in (None, "", "active")


def sign_in_denial(status, has_shop=True):
    if not has_shop or shop_allows_sign_in(status):
        return None
    return SUSPENDED_MESSAGE


def shop_directory_row(shop, user_count, job_count, last_activity):
    """Counts and timestamps only. Job documents never leave the shop."""
    status = shop.get("status") or "active"
    if status not in {"active", "suspended", "pending"}:
        status = "active"
    return {
        "id": shop.get("_id") or shop.get("id"),
        "name": shop.get("name"),
        "slug": shop.get("slug"),
        "status": status,
        "created": shop.get("created"),
        "users": int(user_count or 0),
        "jobs": int(job_count or 0),
        "lastActivity": last_activity or shop.get("created"),
    }


def directory_keys():
    return _DIRECTORY_KEYS


def removal_denial(actor_id, target, active_admin_count):
    """Why this removal must be refused, or None when it may proceed.

    An administrator cannot remove their own account. Removing the only
    remaining administrator is also refused, so the shop always has one.
    """
    if not target or target.get("active") is False:
        return "That person is not in this shop."
    if str(target.get("id") or "") == str(actor_id or ""):
        return "You can't remove your own account."
    if target.get("role") == "admin" and int(active_admin_count or 0) <= 1:
        return "The shop needs at least one administrator."
    return None


def account_is_active(user):
    return bool(user) and user.get("active") is not False


def exclude_archived(query=None):
    """Default job reads omit archived jobs. A direct id lookup does not use this."""
    combined = dict(query or {})
    combined["archived"] = {"$ne": True}
    return combined


def public_lead(lead):
    return {
        "id": lead.get("id") or (None if lead.get("_id") is None else str(lead.get("_id"))),
        "email": lead.get("email"),
        "shop": lead.get("shop"),
        "name": lead.get("name"),
        "city": lead.get("city"),
        "message": lead.get("message"),
        "intent": lead.get("intent"),
        "created": lead.get("created"),
    }
