"""Stripe subscription scaffold. Disabled unless billing env vars are set.

No secret is read into a response. Checkout is not called while disabled.
"""
import os


def billing_status():
    enabled_flag = os.environ.get("BILLING_ENABLED", "").strip().lower() == "true"
    secret = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    price = os.environ.get("STRIPE_PRICE_ID", "").strip()
    webhook = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    key_ok = secret.startswith(("sk_test_", "sk_live_"))
    price_ok = price.startswith("price_")
    webhook_ok = webhook.startswith("whsec_")
    return {
        "enabled": bool(enabled_flag and key_ok and price_ok and webhook_ok),
        "provider": "stripe",
        "flag": enabled_flag,
        "keyPresent": bool(secret),
        "pricePresent": bool(price),
        "webhookPresent": bool(webhook),
    }


def checkout_available():
    status = billing_status()
    if not status["enabled"]:
        return None
    return status
