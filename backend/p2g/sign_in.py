"""Email sign-in, shop choice, sessions, and passkeys.

No new environment variable is required. The passkey relying party id is the
host of the request. Google and magic-link buttons stay off because those
flows are not implemented.
"""
import json
from datetime import datetime, timedelta, timezone

from p2g.tenancy import shop_slug


INVALID_LOGIN = "Email or password is incorrect."
LOCKED_LOGIN = "Too many sign-in attempts. Wait a few minutes and try again."
PASSKEY_FAILED = "This passkey could not sign in. Try again."
PASSKEY_SAVE_FAILED = "This passkey could not be saved. Try again."
PASSKEY_UNAVAILABLE = "This site cannot use a passkey."
CHOICE_EXPIRED = "Pick your shop again. That choice expired."
KEEP_SIGNED_IN_SECONDS = 30 * 24 * 60 * 60
SHORT_SESSION_SECONDS = 12 * 60 * 60
ROTATE_AFTER_SECONDS = 12 * 60 * 60
CHALLENGE_SECONDS = 5 * 60
TICKET_SECONDS = 5 * 60
LOGIN_LIMIT = 8
LOGIN_WINDOW_SECONDS = 15 * 60


class PasskeyError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _moment(value):
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def keep_requested(value):
    """Missing means keep the session. Only an explicit false turns it off."""
    if value is False or value == 0:
        return False
    if isinstance(value, str) and value.strip().lower() in {"0", "false", "off", "no"}:
        return False
    return True


def session_span(keep):
    return KEEP_SIGNED_IN_SECONDS if keep else SHORT_SESSION_SECONDS


def cookie_max_age(keep):
    """A kept session lasts 30 days. Otherwise the cookie ends with the browser."""
    if keep:
        return KEEP_SIGNED_IN_SECONDS
    return None


def session_deadline(now, keep):
    moment = _moment(now) or datetime.now(timezone.utc)
    return (moment + timedelta(seconds=session_span(keep))).isoformat()


def rotation_due(record, now):
    """A kept session gets a new token every 12 hours until it expires."""
    if not record or not record.get("keep"):
        return False
    issued = _moment(record.get("issued"))
    expires = _moment(record.get("expires"))
    current = _moment(now)
    if not issued or not expires or not current or current >= expires:
        return False
    return current - issued >= timedelta(seconds=ROTATE_AFTER_SECONDS)


def sign_in_locked(stamps, now, limit=LOGIN_LIMIT, window_seconds=LOGIN_WINDOW_SECONDS):
    current = _moment(now) or datetime.now(timezone.utc)
    cutoff = current - timedelta(seconds=window_seconds)
    recent = 0
    for stamp in stamps or []:
        moment = _moment(stamp)
        if moment and moment > cutoff:
            recent += 1
    return recent >= limit


def _shop_open(shop):
    status = (shop or {}).get("status")
    return status in (None, "", "active")


def sign_in_decision(users, shops, matching_ids):
    """Password matches only. Shop names are returned after that check."""
    matched = {str(item) for item in matching_ids or []}
    if not matched:
        return {"kind": "invalid"}
    allowed = []
    suspended = False
    for user in users or []:
        if str(user.get("id") or "") not in matched or user.get("active") is False:
            continue
        shop_id = user.get("shop_id")
        if not shop_id:
            allowed.append({**user, "choice_name": "Platform"})
            continue
        shop = (shops or {}).get(shop_id) or {}
        if not _shop_open(shop):
            suspended = True
            continue
        allowed.append({**user, "choice_name": shop.get("name") or "Shop"})
    if not allowed:
        return {"kind": "suspended" if suspended else "invalid"}
    if len(allowed) == 1:
        return {"kind": "session", "user": allowed[0]}
    return {
        "kind": "choose",
        "user_ids": [user["id"] for user in allowed],
        "shops": [{"id": user["id"], "name": user["choice_name"]} for user in allowed],
    }


def ticket_record(user_ids, keep, now):
    moment = _moment(now) or datetime.now(timezone.utc)
    return {
        "user_ids": [str(item) for item in user_ids],
        "keep": bool(keep),
        "expires": (moment + timedelta(seconds=TICKET_SECONDS)).isoformat(),
        "used": False,
    }


def ticket_is_open(ticket, now):
    if not ticket or ticket.get("used"):
        return False
    expires = _moment(ticket.get("expires"))
    current = _moment(now) or datetime.now(timezone.utc)
    return bool(expires and current < expires)


def choice_user(ticket, choice_id, users):
    """The choice id is the user id already proven by the password."""
    wanted = str(choice_id or "")
    allowed = {str(item) for item in (ticket or {}).get("user_ids") or []}
    if not wanted or wanted not in allowed:
        return None
    for user in users or []:
        if str(user.get("id") or "") == wanted:
            return user
    return None


def unique_shop_slug(name, taken):
    """A shop address from the shop name. The next free number keeps it unique."""
    owned = {str(item) for item in taken or []}
    base = shop_slug(name)
    if base not in owned:
        return base
    stem = base[:32].rstrip("-") or "shop"
    for number in range(2, 100):
        candidate = f"{stem}-{number}"
        if candidate not in owned:
            return candidate
    return f"shop-{len(owned) + 2}"


def rp_id_from_host(host):
    """Relying party id is the site host, with no port and no extra names."""
    text = str(host or "").split(",")[0].strip().lower().strip(".")
    if not text or text.startswith("["):
        return ""
    if ":" in text:
        text = text.split(":", 1)[0].strip(".")
    if not text or any(char in text for char in " /\\@") or ".." in text:
        return ""
    return text


def optional_sign_in_providers(env=None):
    """Google and email codes are hidden. There is no flow to turn on."""
    return {"google": False, "magicLink": False}


def challenge_record(purpose, challenge, now, *, user_id="", shop_id=""):
    moment = _moment(now) or datetime.now(timezone.utc)
    return {
        "purpose": purpose,
        "challenge": challenge,
        "user_id": user_id,
        "shop_id": shop_id,
        "expires": (moment + timedelta(seconds=CHALLENGE_SECONDS)).isoformat(),
        "used": False,
    }


def challenge_usable(record, purpose, now, user_id=""):
    if not record or record.get("used") or record.get("purpose") != purpose:
        return False
    if user_id and str(record.get("user_id") or "") != str(user_id):
        return False
    expires = _moment(record.get("expires"))
    current = _moment(now) or datetime.now(timezone.utc)
    return bool(expires and current < expires)


def _load_webauthn():
    try:
        import webauthn
        from webauthn.helpers import bytes_to_base64url
        from webauthn.helpers.structs import (
            AuthenticatorSelectionCriteria,
            PublicKeyCredentialDescriptor,
            ResidentKeyRequirement,
            UserVerificationRequirement,
        )
    except ImportError as error:
        raise PasskeyError(PASSKEY_UNAVAILABLE) from error
    return webauthn, bytes_to_base64url, AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor, ResidentKeyRequirement, UserVerificationRequirement


def begin_passkey(purpose, rp_id, *, user_id="", user_name="", display_name="", exclude_ids=None):
    if not rp_id:
        raise PasskeyError(PASSKEY_UNAVAILABLE)
    webauthn, _encode, criteria, descriptor, resident, verification = _load_webauthn()
    from webauthn.helpers import base64url_to_bytes, options_to_json

    if purpose == "register":
        excluded = []
        for item in exclude_ids or []:
            try:
                excluded.append(descriptor(id=base64url_to_bytes(item)))
            except Exception:
                continue
        options = webauthn.generate_registration_options(
            rp_id=rp_id,
            rp_name="Myraana",
            user_name=user_name or user_id or "shop",
            user_id=str(user_id or "shop").encode(),
            user_display_name=display_name or user_name or "Myraana",
            authenticator_selection=criteria(
                resident_key=resident.PREFERRED,
                user_verification=verification.PREFERRED,
            ),
            exclude_credentials=excluded,
        )
    else:
        options = webauthn.generate_authentication_options(
            rp_id=rp_id,
            user_verification=verification.PREFERRED,
        )
    body = json.loads(options_to_json(options))
    return body, body["challenge"]


def client_challenge(payload):
    response = (payload or {}).get("response") or {}
    raw = response.get("clientDataJSON") or ""
    if not raw:
        return ""
    try:
        from webauthn.helpers import base64url_to_bytes

        data = json.loads(base64url_to_bytes(raw))
    except Exception:
        return ""
    return str(data.get("challenge") or "")


def finish_passkey_registration(credential, *, challenge, rp_id, origin):
    webauthn, encode, *_rest = _load_webauthn()
    from webauthn.helpers import base64url_to_bytes

    try:
        verified = webauthn.verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id,
            expected_origin=origin,
        )
    except PasskeyError:
        raise
    except Exception as error:
        raise PasskeyError(PASSKEY_SAVE_FAILED) from error
    return {
        "credential_id": encode(verified.credential_id),
        "public_key": encode(verified.credential_public_key),
        "sign_count": int(verified.sign_count),
    }


def finish_passkey_login(credential, *, challenge, rp_id, origin, public_key, sign_count):
    webauthn, encode, *_rest = _load_webauthn()
    from webauthn.helpers import base64url_to_bytes

    try:
        verified = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=base64url_to_bytes(public_key),
            credential_current_sign_count=int(sign_count or 0),
        )
    except PasskeyError:
        raise
    except Exception as error:
        raise PasskeyError(PASSKEY_FAILED) from error
    credential_id = verified.credential_id or b""
    return {
        "credential_id": encode(credential_id) if credential_id else str((credential or {}).get("id") or ""),
        "sign_count": int(verified.new_sign_count),
    }
