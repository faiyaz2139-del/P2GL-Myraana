"""How a connector proves which shop it belongs to.

New pairing codes and device credentials are a plain SHA-256. That path does
not need CONNECTOR_SECRET. The older HMAC is accepted only for Print2Go, which
is the shop the shared secret was installed for.
"""
import hashlib
import hmac

from p2g.tenancy import PRINT2GO_SHOP_ID, bound_shop


def credential_hash(value):
    return hashlib.sha256(str(value or "").encode()).hexdigest()


def legacy_credential_hash(value, secret):
    secret = str(secret or "")
    if not secret:
        return None
    return hmac.new(secret.encode(), str(value or "").encode(), hashlib.sha256).hexdigest()


def select_device(devices, credential, secret):
    """Return (device, kind) where kind is current or legacy.

    A legacy HMAC match is ignored unless that device belongs to Print2Go.
    A missing shop_id on a legacy device is the original Print2Go install.
    """
    plain = credential_hash(credential)
    for device in devices or []:
        if device.get("enabled", True) and device.get("credential_hash") == plain:
            return device, "current"
    old = legacy_credential_hash(credential, secret)
    if not old:
        return None, None
    for device in devices or []:
        if not device.get("enabled", True) or device.get("credential_hash") != old:
            continue
        owner = device.get("shop_id") or PRINT2GO_SHOP_ID
        if owner == PRINT2GO_SHOP_ID:
            return device, "legacy"
    return None, None


def legacy_shared_secret_shop(requested_shop):
    """The bearer CONNECTOR_SECRET path is Print2Go only."""
    return bound_shop(PRINT2GO_SHOP_ID, requested_shop)
