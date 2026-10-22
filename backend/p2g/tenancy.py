"""Shop scope for every tenant-owned record.

Queries, inserts, updates, and deletes on tenant collections go through
TenantDatabase. A request with no shop fails closed. SAAS_TENANT_ISOLATION
does not turn that off. The two signup flags only decide whether a new shop
can be created. The live Print2Go rows are backfilled to shop_id "print2go".
"""
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

from p2g.products import default_artwork_rules


PRINT2GO_SHOP_ID = "print2go"

TENANT_COLLECTIONS = frozenset({
    "users",
    "jobs",
    "settings",
    "recipes",
    "connector_pairings",
    "connector_devices",
    "connector_state",
    "executions",
    "cost_profiles",
    "machine_capabilities",
    "assistant_leases",
    "sessions",
    "invites",
    "password_resets",
})

_shop = ContextVar("myraana_shop", default=None)
_unscoped = ContextVar("myraana_unscoped", default=False)


class TenantScopeError(Exception):
    def __init__(self, message, status=403, code="shop-mismatch"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def _flag(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "on", "yes"}


def signup_is_open():
    """A new shop is created only when isolation and signup are both enabled."""
    return _flag("SAAS_TENANT_ISOLATION") and _flag("SAAS_SIGNUP_ENABLED")


def is_shop_admin(user):
    return bool(user) and user.get("role") == "admin" and bool(user.get("shop_id"))


def is_superadmin(user):
    return bool(user) and user.get("role") == "superadmin" and not user.get("shop_id")


def invite_role(role):
    value = str(role or "").strip().lower()
    if value not in {"operator", "admin"}:
        raise TenantScopeError(
            "Invite an operator or a shop administrator.",
            400,
            "invite-role",
        )
    return value


def login_matches(users, shop_id, slug_provided):
    """Pick the accounts that may sign in for an email.

    No shop address means every match, so the caller can ask for one when
    several shops share the email. An unknown address matches nobody, including
    a platform administrator whose shop_id is null.
    """
    if not slug_provided:
        return list(users or [])
    if not shop_id:
        return []
    return [user for user in users or [] if user.get("shop_id") == shop_id]


def shop_slug(name):
    slug = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    slug = slug[:40].strip("-")
    return slug or "shop"


def bound_shop(owner_shop, requested_shop):
    """A connector credential belongs to one shop. A different declared shop is rejected."""
    owner = str(owner_shop or "").strip()
    requested = str(requested_shop or "").strip()
    if not owner:
        raise TenantScopeError("Connector is not bound to a shop.", 401, "connector-shop")
    if requested and requested != owner:
        raise TenantScopeError("Connector token is for a different shop.", 401, "connector-shop")
    return owner


def download_allowed(actor_shop, job_shop, metadata_shop):
    """File bytes are returned only when the actor, the job, and any stored shop agree.

    Metadata written before the backfill may omit shop_id. Those files follow the job.
    """
    if not actor_shop or actor_shop != job_shop:
        return False
    if metadata_shop and metadata_shop != actor_shop:
        return False
    return True


def current_shop_id():
    if _unscoped.get():
        return None
    return _shop.get()


def activate_shop(shop_id):
    if not shop_id:
        raise TenantScopeError("Sign in to your shop.", 401, "shop-required")
    _shop.set(str(shop_id))


def clear_shop():
    return (_shop.set(None), _unscoped.set(False))


def reset_shop(tokens):
    shop_token, unscoped_token = tokens
    _shop.reset(shop_token)
    _unscoped.reset(unscoped_token)


@contextmanager
def unscoped():
    token = _unscoped.set(True)
    try:
        yield
    finally:
        _unscoped.reset(token)


@contextmanager
def shop_scope(shop_id):
    if not shop_id:
        raise TenantScopeError("Sign in to your shop.", 401, "shop-required")
    token = _shop.set(str(shop_id))
    try:
        yield str(shop_id)
    finally:
        _shop.reset(token)


def starter_settings(shop_name):
    return {
        "kind": "settings",
        "printer": "",
        "stocks": ["14pt matte", "16pt soft touch", "100lb Gloss Text", "28lb Smooth Text"],
        "sides": [1, 2],
        "instructions": "Operator-assisted RIP handoff. No automatic printing.",
        "version": 1,
        "shopName": shop_name,
        "verifiedPrinters": [],
        "jobDefaults": None,
        "artworkRules": default_artwork_rules(),
    }


def starter_recipes():
    """Business card and flyer presets every new shop starts with."""
    return [
        {
            "id": "business-card",
            "version": 1,
            "name": "Business card",
            "width": 3.5,
            "height": 2.0,
            "bleed": 0.125,
            "safe": 0.25,
            "minDpi": 300,
            "cutInstructions": "Cut to 3.5 × 2 inches using the verified trim box.",
        },
        {
            "id": "flyer",
            "product": "flyer",
            "version": 1,
            "name": "Flyer",
            "width": 8.5,
            "height": 11.0,
            "bleed": 0.125,
            "safe": 0.25,
            "minDpi": 300,
            "cutInstructions": "Cut to 8.5 × 11 in using the verified trim box. No fold.",
        },
    ]


def new_shop_records(*, shop_id, name, slug, email, owner_name, owner_id, password_hash, created):
    settings = starter_settings(name)
    settings["_id"] = shop_id
    return {
        "shop": {
            "_id": shop_id,
            "name": name,
            "slug": slug,
            "created": created,
            "billing": {"enabled": False, "provider": "stripe"},
        },
        "user": {
            "id": owner_id,
            "name": owner_name,
            "email": email,
            "role": "admin",
            "password": password_hash,
            "shop_id": shop_id,
            "created": created,
        },
        "settings": settings,
        "recipes": [{**recipe, "created": created} for recipe in starter_recipes()],
    }


def _reject_foreign_shop(value, shop):
    if isinstance(value, dict):
        raise TenantScopeError("Shop filter is not allowed.", 403, "shop-mismatch")
    if value is not None and value != shop:
        raise TenantScopeError("That record belongs to another shop.", 403, "shop-mismatch")


class TenantCollection:
    def __init__(self, collection):
        self._collection = collection

    def _bypassed(self):
        return bool(_unscoped.get())

    def _require_shop(self):
        shop = _shop.get()
        if not shop:
            raise TenantScopeError("Sign in to your shop.", 401, "shop-required")
        return shop

    def _scope_filter(self, filt):
        scoped = dict(filt or {})
        if self._bypassed():
            return scoped
        shop = self._require_shop()
        _reject_foreign_shop(scoped.get("shop_id"), shop)
        scoped["shop_id"] = shop
        return scoped

    def _scope_document(self, document):
        scoped = dict(document)
        if self._bypassed():
            return scoped
        shop = self._require_shop()
        _reject_foreign_shop(scoped.get("shop_id"), shop)
        scoped["shop_id"] = shop
        return scoped

    def _scope_update(self, update):
        if self._bypassed():
            return update
        shop = self._require_shop()
        scoped = dict(update)
        for operator in ("$set", "$setOnInsert"):
            block = scoped.get(operator)
            if not isinstance(block, dict):
                continue
            copied = dict(block)
            _reject_foreign_shop(copied.get("shop_id"), shop)
            if operator == "$set" or "shop_id" in copied:
                copied["shop_id"] = shop
            scoped[operator] = copied
        if not isinstance(scoped.get("$set"), dict):
            scoped["$set"] = {"shop_id": shop}
        else:
            scoped["$set"]["shop_id"] = shop
        return scoped

    def find(self, filt=None, *args, **kwargs):
        return self._collection.find(self._scope_filter(filt), *args, **kwargs)

    async def find_one(self, filt=None, *args, **kwargs):
        return await self._collection.find_one(self._scope_filter(filt), *args, **kwargs)

    async def insert_one(self, document, *args, **kwargs):
        return await self._collection.insert_one(self._scope_document(document), *args, **kwargs)

    async def update_one(self, filt, update, *args, **kwargs):
        return await self._collection.update_one(
            self._scope_filter(filt), self._scope_update(update), *args, **kwargs
        )

    async def update_many(self, filt, update, *args, **kwargs):
        return await self._collection.update_many(
            self._scope_filter(filt), self._scope_update(update), *args, **kwargs
        )

    async def delete_one(self, filt, *args, **kwargs):
        return await self._collection.delete_one(self._scope_filter(filt), *args, **kwargs)

    async def delete_many(self, filt, *args, **kwargs):
        return await self._collection.delete_many(self._scope_filter(filt), *args, **kwargs)

    async def replace_one(self, filt, replacement, *args, **kwargs):
        return await self._collection.replace_one(
            self._scope_filter(filt), self._scope_document(replacement), *args, **kwargs
        )

    async def count_documents(self, filt=None, *args, **kwargs):
        return await self._collection.count_documents(self._scope_filter(filt), *args, **kwargs)

    async def find_one_and_update(self, filt, update, *args, **kwargs):
        return await self._collection.find_one_and_update(
            self._scope_filter(filt), self._scope_update(update), *args, **kwargs
        )

    def create_index(self, *args, **kwargs):
        return self._collection.create_index(*args, **kwargs)

    def drop_index(self, *args, **kwargs):
        return self._collection.drop_index(*args, **kwargs)

    def list_indexes(self, *args, **kwargs):
        return self._collection.list_indexes(*args, **kwargs)

    def index_information(self, *args, **kwargs):
        return self._collection.index_information(*args, **kwargs)


class TenantDatabase:
    def __init__(self, raw):
        self._raw = raw

    @property
    def raw(self):
        return self._raw

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._wrap(name)

    def __getitem__(self, name):
        return self._wrap(name)

    def _wrap(self, name):
        collection = self._raw[name]
        if name in TENANT_COLLECTIONS:
            return TenantCollection(collection)
        return collection


def _stamp():
    return datetime.now(timezone.utc).isoformat()


async def _drop_index_if_present(collection, name):
    info = getattr(collection, "index_information", None)
    if info is None:
        return
    try:
        found = await info()
    except Exception:
        return
    if name in found:
        await collection.drop_index(name)


async def migrate_tenants(database):
    """Create the Print2Go shop and backfill shop_id. Safe to run again.

    A field that is already set is left alone, including a platform
    administrator whose shop_id is explicitly null. Missing shop_id means
    the row belonged to the original single shop.
    """
    with unscoped():
        raw = database.raw if hasattr(database, "raw") else database
        await raw.shops.update_one(
            {"_id": PRINT2GO_SHOP_ID},
            {"$setOnInsert": {
                "name": "Print2Go",
                "slug": "print2go",
                "created": _stamp(),
                "billing": {"enabled": False, "provider": "stripe"},
            }},
            upsert=True,
        )
        await raw.shops.update_one(
            {"_id": PRINT2GO_SHOP_ID, "slug": {"$exists": False}},
            {"$set": {"slug": "print2go"}},
        )
        await raw.shops.update_one(
            {"_id": PRINT2GO_SHOP_ID, "billing": {"$exists": False}},
            {"$set": {"billing": {"enabled": False, "provider": "stripe"}}},
        )
        for name in TENANT_COLLECTIONS:
            await raw[name].update_many(
                {"shop_id": {"$exists": False}},
                {"$set": {"shop_id": PRINT2GO_SHOP_ID}},
            )
        await raw["pdf_files.files"].update_many(
            {"metadata.shop_id": {"$exists": False}},
            {"$set": {"metadata.shop_id": PRINT2GO_SHOP_ID}},
        )
        await raw.settings.update_one(
            {"_id": "shop", "kind": {"$exists": False}},
            {"$set": {"kind": "settings"}},
        )
        await raw.connector_state.update_one(
            {"_id": "agent", "role": {"$exists": False}},
            {"$set": {"role": "agent"}},
        )
        await _drop_index_if_present(raw.users, "email_1")
        await _drop_index_if_present(raw.cost_profiles, "id_1")
