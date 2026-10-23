"""Session and membership checks that do not open a database client.

Login and invite acceptance both store a session through save_session.
The next request resolves it with user_for_session, which is what current_user uses.
"""
import hashlib

from p2g.account_access import account_is_active, shop_allows_sign_in
from p2g.tenancy import activate_shop, shop_scope, unscoped


def session_token_hash(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


async def save_session(database, *, token, user_id, shop_id, session_id, expires, keep=False, issued=""):
    record = {
        "id": session_id,
        "user_id": user_id,
        "token_hash": session_token_hash(token),
        "expires": expires,
        "keep": bool(keep),
        "issued": issued or expires,
    }
    if shop_id:
        with shop_scope(shop_id):
            await database.sessions.insert_one(record)
        return
    with unscoped():
        record["shop_id"] = None
        await database.sessions.insert_one(record)


async def end_user_sessions(database, user_id):
    await database.sessions.delete_many({"user_id": user_id})


async def user_for_session(database, token, now_iso):
    if not token:
        return None
    with unscoped():
        session = await database.sessions.find_one(
            {"token_hash": session_token_hash(token), "expires": {"$gt": now_iso}},
            {"_id": 0},
        )
        if not session:
            return None
        user = await database.users.find_one(
            {"id": session["user_id"]},
            {"_id": 0, "password": 0},
        )
    if not account_is_active(user):
        return None
    user = dict(user)
    user.pop("password", None)
    if user.get("shop_id"):
        shop = await database.shops.find_one({"_id": user["shop_id"]}, {"_id": 1, "status": 1})
        if shop and shop_allows_sign_in(shop.get("status")):
            user["shop_status"] = shop.get("status") or "active"
        else:
            user["shop_status"] = "suspended"
        activate_shop(user["shop_id"])
    return user
