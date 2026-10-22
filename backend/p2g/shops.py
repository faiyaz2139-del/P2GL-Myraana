"""Create a shop and keep its settings, connector, and invites inside that shop."""
import secrets
from datetime import datetime, timedelta, timezone

from p2g.account_access import PUBLIC_RESET_ERROR, reset_token_state
from p2g.core import AppError, db, new_id, now, sha256
from p2g.mail import MailError, send_email
from p2g.tenancy import (
    current_shop_id,
    invite_role,
    new_shop_records,
    shop_scope,
    shop_slug,
    starter_recipes,
    starter_settings,
    unscoped,
)
from p2g.workflow import password_hash


async def provision_shop(name, email, password, owner_name=""):
    name = str(name or "").strip()
    email = str(email or "").strip().lower()
    owner_name = str(owner_name or "").strip() or name
    if len(name) < 2 or len(name) > 120:
        raise AppError("Enter your shop name.", 400)
    if "@" not in email or len(email) > 200 or " " in email:
        raise AppError("Enter a valid email address.", 400)
    if not owner_name or len(owner_name) > 80:
        raise AppError("Enter your name.", 400)
    if not 12 <= len(str(password or "")) <= 200:
        raise AppError("Use a password of at least 12 characters.", 400)
    created = now()
    with unscoped():
        if await db.users.find_one({"email": email, "role": "superadmin"}):
            raise AppError("That email cannot be used for a shop.", 409)
        candidate = await _unique_slug(name)
        shop_id = new_id()
        bundle = new_shop_records(
            shop_id=shop_id,
            name=name,
            slug=candidate,
            email=email,
            owner_name=owner_name,
            owner_id=new_id(),
            password_hash=password_hash(password),
            created=created,
        )
        await db.shops.insert_one(bundle["shop"])
    try:
        with shop_scope(shop_id):
            await db.users.insert_one(bundle["user"])
            await db.settings.insert_one(bundle["settings"])
            for recipe in bundle["recipes"]:
                await db.recipes.insert_one(recipe)
    except Exception:
        with unscoped():
            await db.shops.delete_one({"_id": shop_id})
            await db.users.delete_many({"shop_id": shop_id})
            await db.settings.delete_many({"shop_id": shop_id})
            await db.recipes.delete_many({"shop_id": shop_id})
        raise
    return bundle["user"], bundle["shop"]


async def _unique_slug(name):
    slug = shop_slug(name)
    candidate = slug
    for _ in range(6):
        if not await db.shops.find_one({"slug": candidate}):
            return candidate
        candidate = f"{slug[:32].rstrip('-')}-{new_id()[:6]}"
    return f"shop-{new_id()[:8]}"


async def open_shop_from_lead(lead, created_by, link_for=None):
    """A signup lead has no password. The owner joins through an invite."""
    name = str((lead or {}).get("shop") or "").strip()
    email = str((lead or {}).get("email") or "").strip().lower()
    owner_name = str((lead or {}).get("name") or "").strip() or name
    if len(name) < 2 or len(name) > 120:
        raise AppError("Enter your shop name.", 400)
    if "@" not in email or len(email) > 200 or " " in email:
        raise AppError("Enter a valid email address.", 400)
    created = now()
    with unscoped():
        if await db.users.find_one({"email": email, "role": "superadmin"}):
            raise AppError("That email cannot be used for a shop.", 409)
        slug = await _unique_slug(name)
        shop_id = new_id()
        shop = {
            "_id": shop_id,
            "name": name,
            "slug": slug,
            "created": created,
            "status": "active",
            "billing": {"enabled": False, "provider": "stripe"},
        }
        await db.shops.insert_one(shop)
    try:
        with shop_scope(shop_id):
            settings = starter_settings(name)
            settings["_id"] = shop_id
            await db.settings.insert_one(settings)
            for recipe in starter_recipes():
                await db.recipes.insert_one({**recipe, "created": created})
            invite = await create_invite(
                {"id": created_by},
                {"email": email, "role": "admin", "name": owner_name[:80]},
                link_for=link_for,
                shop_name=name,
            )
    except Exception:
        with unscoped():
            await db.shops.delete_one({"_id": shop_id})
            await db.settings.delete_many({"shop_id": shop_id})
            await db.recipes.delete_many({"shop_id": shop_id})
            await db.invites.delete_many({"shop_id": shop_id})
        raise
    return shop, invite


async def replace_settings(data):
    current = await db.settings.find_one({"kind": "settings"})
    doc_id = current["_id"] if current else current_shop_id()
    body = {
        key: value
        for key, value in data.items()
        if key not in {"_id", "id", "shop_id", "kind"}
    }
    await db.settings.replace_one(
        {"_id": doc_id},
        {"_id": doc_id, "kind": "settings", **body},
        upsert=True,
    )


async def save_connector_agent(fields):
    current = await db.connector_state.find_one({"role": "agent"})
    doc_id = current["_id"] if current else f"agent:{current_shop_id()}"
    body = {
        key: value
        for key, value in fields.items()
        if key not in {"_id", "id", "shop_id", "role"}
    }
    await db.connector_state.replace_one(
        {"_id": doc_id},
        {"_id": doc_id, "role": "agent", **body},
        upsert=True,
    )


def _invite_email_ok(email):
    if "@" not in email or len(email) > 200 or " " in email:
        raise AppError("Enter a valid email address.", 400)
    return email


def invite_message(shop_name, role, link):
    label = "shop administrator" if role == "admin" else "operator"
    return (
        f"You are invited to join {shop_name} on Myraana as a {label}.\n\n"
        "Open this link to choose a password. It expires in 7 days and only joins this shop.\n\n"
        f"{link}\n"
    )


def deliver_invite(email, shop_name, role, link):
    """A failed send still leaves the token with the administrator who created it."""
    try:
        return send_email(
            email,
            f"You're invited to {shop_name}",
            invite_message(shop_name, role, link),
        )
    except MailError:
        return {"delivered": False, "provider": "error"}


def _public_invite(invite, token=None, delivery=None):
    body = {
        "ok": True,
        "id": invite["_id"],
        "email": invite["email"],
        "role": invite["role"],
        "expires": invite["expires"],
        "revoked": bool(invite.get("revoked")),
        "accepted": bool(invite.get("accepted")),
    }
    if token:
        body["token"] = token
    if delivery:
        body["emailed"] = bool(delivery.get("delivered"))
        body["provider"] = delivery.get("provider")
    return body


async def create_invite(user, payload, link_for=None, shop_name="your shop"):
    email = _invite_email_ok(str((payload or {}).get("email") or "").strip().lower())
    role = invite_role((payload or {}).get("role") or "operator")
    name = str((payload or {}).get("name") or "").strip()[:80]
    raw = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    invite = {
        "_id": new_id(),
        "email": email,
        "role": role,
        "name": name,
        "token_hash": sha256(raw),
        "expires": expires,
        "created_by": user["id"],
        "created": now(),
        "accepted": False,
        "revoked": False,
    }
    await db.invites.insert_one(invite)
    delivery = None
    if link_for:
        delivery = deliver_invite(email, shop_name, role, link_for(raw))
    return _public_invite(invite, raw, delivery)


async def list_invites():
    rows = await db.invites.find({"accepted": {"$ne": True}}).sort("created", -1).to_list(100)
    return [
        {
            "id": row["_id"],
            "email": row.get("email"),
            "role": row.get("role"),
            "name": row.get("name") or "",
            "expires": row.get("expires"),
            "created": row.get("created"),
            "revoked": bool(row.get("revoked")),
        }
        for row in rows
    ]


async def resend_invite(user, invite_id, link_for, shop_name):
    invite = await db.invites.find_one({"_id": invite_id})
    if not invite or invite.get("accepted"):
        raise AppError("This invite is no longer pending.", 404)
    raw = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    await db.invites.update_one(
        {"_id": invite_id},
        {"$set": {
            "token_hash": sha256(raw),
            "expires": expires,
            "revoked": False,
            "resent_by": user["id"],
            "resent": now(),
        }},
    )
    invite["expires"] = expires
    invite["revoked"] = False
    delivery = deliver_invite(invite["email"], shop_name, invite["role"], link_for(raw))
    return _public_invite(invite, raw, delivery)


async def revoke_invite(invite_id):
    result = await db.invites.update_one(
        {"_id": invite_id, "accepted": {"$ne": True}},
        {"$set": {"revoked": True}},
    )
    if not getattr(result, "modified_count", 0):
        raise AppError("This invite is no longer pending.", 404)
    return {"ok": True}


async def accept_invite(payload):
    raw = str((payload or {}).get("token") or "")
    password = str((payload or {}).get("password") or "")
    name = str((payload or {}).get("name") or "").strip()
    if len(raw) < 20:
        raise AppError("This invite is invalid or expired.", 400)
    if not name or len(name) > 80:
        raise AppError("Enter your name.", 400)
    if not 12 <= len(password) <= 200:
        raise AppError("Use a password of at least 12 characters.", 400)
    with unscoped():
        invite = await db.invites.find_one({"token_hash": sha256(raw), "accepted": {"$ne": True}})
    if (
        not invite
        or invite.get("shop_id") is None
        or invite.get("revoked")
        or invite.get("expires", "") <= now()
    ):
        raise AppError("This invite is invalid or expired.", 400)
    email = invite["email"]
    with unscoped():
        if await db.users.find_one({"email": email, "role": "superadmin"}):
            raise AppError("That email cannot be used for a shop.", 409)
    user = {
        "id": new_id(),
        "name": name,
        "email": email,
        "role": invite["role"],
        "password": password_hash(password),
        "shop_id": invite["shop_id"],
        "created": now(),
    }
    with shop_scope(invite["shop_id"]):
        if await db.users.find_one({"email": email}):
            raise AppError("That email is already in this shop.", 409)
        await db.users.insert_one(user)
        await db.invites.update_one({"_id": invite["_id"]}, {"$set": {"accepted": True}})
    user.pop("password", None)
    return user


async def issue_password_reset(user_id, email, shop_id):
    raw = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    with shop_scope(shop_id):
        await db.password_resets.insert_one({
            "_id": new_id(),
            "user_id": user_id,
            "email": email,
            "token_hash": sha256(raw),
            "expires": expires,
            "used": False,
            "created": now(),
        })
    return raw


async def confirm_password_reset(raw, password):
    if len(str(raw or "")) < 20:
        raise AppError(PUBLIC_RESET_ERROR, 400)
    if not 12 <= len(str(password or "")) <= 200:
        raise AppError("Use a password of at least 12 characters.", 400)
    with unscoped():
        record = await db.password_resets.find_one({"token_hash": sha256(raw)})
    if reset_token_state(record, now()) != "ok" or not record.get("shop_id"):
        raise AppError(PUBLIC_RESET_ERROR, 400)
    with shop_scope(record["shop_id"]):
        updated = await db.password_resets.update_one(
            {"_id": record["_id"], "used": {"$ne": True}, "expires": {"$gt": now()}},
            {"$set": {"used": True}},
        )
        if not getattr(updated, "modified_count", 0):
            raise AppError(PUBLIC_RESET_ERROR, 400)
        user = await db.users.find_one({"id": record["user_id"]})
        if not user or user.get("role") == "superadmin" or not user.get("shop_id"):
            raise AppError(PUBLIC_RESET_ERROR, 400)
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"password": password_hash(password)}},
        )
    return {"ok": True}
