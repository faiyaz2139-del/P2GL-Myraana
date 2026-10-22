"""Early-access leads and the closed signup response.

A shop workspace is created only when both signup flags are on. This helper
always describes the request-only result.
"""
import re


EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class FormError(ValueError):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def lead_from_payload(payload, intent):
    payload = payload or {}
    email = str(payload.get("email") or "").strip().lower()
    if not EMAIL.match(email) or len(email) > 200:
        raise FormError("Enter a valid email address.")
    shop = str(payload.get("shop") or payload.get("shopName") or "").strip()
    name = str(payload.get("name") or "").strip()
    city = str(payload.get("city") or "").strip()
    message = str(payload.get("message") or "").strip()
    for label, value, limit in (
        ("Shop", shop, 120),
        ("Name", name, 80),
        ("City", city, 80),
        ("Message", message, 2000),
    ):
        if len(value) > limit:
            raise FormError(f"{label} is too long.")
    if intent not in {"early-access", "demo", "contact", "signup"}:
        raise FormError("Choose a request type.")
    if intent in {"early-access", "signup", "demo"} and len(shop) < 2:
        raise FormError("Enter your shop name.")
    return {
        "email": email,
        "shop": shop,
        "name": name,
        "city": city,
        "message": message,
        "intent": intent,
    }


def signup_result():
    """Request-only response used while self-serve signup is turned off."""
    return {
        "ok": True,
        "workspace": False,
        "message": (
            "Myraana saved your request. A separate shop workspace is not open yet. "
            "We will set the shop up with you."
        ),
    }
