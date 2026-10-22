"""Create a shop and keep its settings, connector, and invites inside that shop."""
import secrets
from datetime import datetime, timedelta, timezone

from p2g.core import AppError, db, new_id, now, sha256
from p2g.tenancy import (
    current_shop_id,
    invite_role,
    new_shop_records,
    shop_scope,
    shop_slug,
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
        slug = shop_slug(name)
        candidate = slug
        for _ in range(6):
            if not await db.shops.find_one({"slug": candidate}):
                break
            candidate = f"{slug[:32].rstrip('-')}-{new_id()[:6]}"
        else:
            candidate = f"shop-{new_id()[:8]}"
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


async def create_invite(user, payload):
    email = str((payload or {}).get("email") or "").strip().lower()
    if "@" not in email or len(email) > 200 or " " in email:
        raise AppError("Enter a valid email address.", 400)
    role = invite_role((payload or {}).get("role") or "operator")
    name = str((payload or {}).get("name") or "").strip()[:80]
    raw = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    await db.invites.insert_one({
        "_id": new_id(),
        "email": email,
        "role": role,
        "name": name,
        "token_hash": sha256(raw),
        "expires": expires,
        "created_by": user["id"],
        "created": now(),
        "accepted": False,
    })
    return {"ok": True, "token": raw, "expires": expires, "email": email, "role": role}


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
    if not invite or invite.get("shop_id") is None or invite.get("expires", "") <= now():
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
