"""Cross-tenant isolation without Mongo. The wrapper is the same one the API uses."""
import asyncio
import copy
import os

from p2g.public_forms import signup_result
from p2g.tenancy import (
    PRINT2GO_SHOP_ID,
    TenantDatabase,
    TenantScopeError,
    bound_shop,
    download_allowed,
    invite_role,
    is_shop_admin,
    is_superadmin,
    login_matches,
    migrate_tenants,
    new_shop_records,
    shop_scope,
    shop_slug,
    signup_is_open,
    unscoped,
)


MISSING = object()


class WriteResult:
    def __init__(self, matched, modified):
        self.matched_count = matched
        self.modified_count = modified


def _get_path(doc, path):
    current = doc
    for part in str(path).split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def _set_path(doc, path, value):
    parts = str(path).split(".")
    cursor = doc
    for part in parts[:-1]:
        nxt = cursor.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[part] = nxt
        cursor = nxt
    cursor[parts[-1]] = value


def _compare(value, op, target):
    if value is MISSING:
        return False
    try:
        if op == "$gt":
            return value > target
        if op == "$lt":
            return value < target
        if op == "$gte":
            return value >= target
    except TypeError:
        return False
    return False


def _match_ops(value, spec):
    if "$exists" in spec and (value is not MISSING) != bool(spec["$exists"]):
        return False
    if "$ne" in spec and value == spec["$ne"]:
        return False
    if "$in" in spec and value not in spec["$in"]:
        return False
    for op in ("$gt", "$lt", "$gte"):
        if op in spec and not _compare(value, op, spec[op]):
            return False
    return True


def matches(doc, filt):
    if not filt:
        return True
    for key, expected in filt.items():
        if key == "$or":
            if not any(matches(doc, clause) for clause in expected):
                return False
            continue
        if key == "$and":
            if not all(matches(doc, clause) for clause in expected):
                return False
            continue
        value = _get_path(doc, key)
        if isinstance(expected, dict) and any(str(op).startswith("$") for op in expected):
            if not _match_ops(value, expected):
                return False
        elif value != expected:
            return False
    return True


def apply_update(doc, update, insert):
    if insert and isinstance(update.get("$setOnInsert"), dict):
        for key, value in update["$setOnInsert"].items():
            _set_path(doc, key, copy.deepcopy(value))
    if isinstance(update.get("$set"), dict):
        for key, value in update["$set"].items():
            _set_path(doc, key, copy.deepcopy(value))


def project(doc, projection):
    if not projection:
        return doc
    excluded = [key for key, value in projection.items() if value == 0]
    if excluded:
        for key in excluded:
            doc.pop(key, None)
        return doc
    included = {key for key, value in projection.items() if value}
    out = {}
    if "_id" not in projection and "_id" in doc:
        out["_id"] = doc["_id"]
    for key in included:
        if key in doc:
            out[key] = doc[key]
    return out


class MemoryCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction=1):
        spec = [(key, direction)] if isinstance(key, str) else list(key)
        for field, way in reversed(spec):
            self.docs.sort(key=lambda doc: (doc.get(field) is None, str(doc.get(field))), reverse=way < 0)
        return self

    async def to_list(self, length=None):
        if length is None:
            return list(self.docs)
        return list(self.docs[:length])


class MemoryCollection:
    def __init__(self):
        self.docs = []
        self.indexes = {"_id_": {}}

    async def insert_one(self, document, *args, **kwargs):
        self.docs.append(copy.deepcopy(document))

    def find(self, filt=None, *args, **kwargs):
        projection = args[0] if args else None
        rows = [project(copy.deepcopy(doc), projection) for doc in self.docs if matches(doc, filt or {})]
        return MemoryCursor(rows)

    async def find_one(self, filt=None, *args, **kwargs):
        projection = args[0] if args else None
        rows = [doc for doc in self.docs if matches(doc, filt or {})]
        if kwargs.get("sort"):
            rows = MemoryCursor([copy.deepcopy(doc) for doc in rows]).sort(kwargs["sort"]).docs
        if not rows:
            return None
        return project(copy.deepcopy(rows[0]), projection)

    async def update_one(self, filt, update, *args, **kwargs):
        for doc in self.docs:
            if matches(doc, filt or {}):
                apply_update(doc, update, insert=False)
                return WriteResult(1, 1)
        if kwargs.get("upsert"):
            created = {}
            for key, value in (filt or {}).items():
                if not str(key).startswith("$") and not isinstance(value, dict):
                    _set_path(created, key, copy.deepcopy(value))
            apply_update(created, update, insert=True)
            self.docs.append(created)
        return WriteResult(0, 0)

    async def update_many(self, filt, update, *args, **kwargs):
        count = 0
        for doc in self.docs:
            if matches(doc, filt or {}):
                apply_update(doc, update, insert=False)
                count += 1
        return WriteResult(count, count)

    async def delete_one(self, filt, *args, **kwargs):
        for index, doc in enumerate(self.docs):
            if matches(doc, filt or {}):
                self.docs.pop(index)
                return WriteResult(1, 1)
        return WriteResult(0, 0)

    async def delete_many(self, filt, *args, **kwargs):
        kept = [doc for doc in self.docs if not matches(doc, filt or {})]
        removed = len(self.docs) - len(kept)
        self.docs = kept
        return WriteResult(removed, removed)

    async def replace_one(self, filt, replacement, *args, **kwargs):
        for index, doc in enumerate(self.docs):
            if matches(doc, filt or {}):
                self.docs[index] = copy.deepcopy(replacement)
                return WriteResult(1, 1)
        if kwargs.get("upsert"):
            self.docs.append(copy.deepcopy(replacement))
        return WriteResult(0, 0)

    async def count_documents(self, filt=None, *args, **kwargs):
        return sum(1 for doc in self.docs if matches(doc, filt or {}))

    async def index_information(self):
        return dict(self.indexes)

    async def drop_index(self, name):
        self.indexes.pop(name, None)

    async def create_index(self, keys, **kwargs):
        self.indexes[kwargs.get("name") or "index"] = {}
        return kwargs.get("name") or "index"


class MemoryDB:
    def __init__(self):
        self._collections = {}

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = MemoryCollection()
        return self._collections[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]


def test_signup_stays_closed_unless_both_flags_are_on():
    previous = {key: os.environ.get(key) for key in ("SAAS_TENANT_ISOLATION", "SAAS_SIGNUP_ENABLED")}
    try:
        os.environ["SAAS_TENANT_ISOLATION"] = "off"
        os.environ["SAAS_SIGNUP_ENABLED"] = "true"
        assert signup_is_open() is False
        os.environ["SAAS_TENANT_ISOLATION"] = "on"
        os.environ["SAAS_SIGNUP_ENABLED"] = "false"
        assert signup_is_open() is False
        os.environ["SAAS_SIGNUP_ENABLED"] = "true"
        assert signup_is_open() is True
        closed = signup_result()
        assert closed["workspace"] is False
        assert "not open" in closed["message"]
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_roles_and_invites_keep_platform_admin_separate():
    assert is_shop_admin({"role": "admin", "shop_id": "print2go"}) is True
    assert is_shop_admin({"role": "operator", "shop_id": "print2go"}) is False
    assert is_shop_admin({"role": "admin"}) is False
    assert is_shop_admin({"role": "superadmin"}) is False
    assert is_superadmin({"role": "superadmin"}) is True
    assert is_superadmin({"role": "superadmin", "shop_id": "print2go"}) is False
    assert is_superadmin({"role": "admin", "shop_id": "print2go"}) is False
    assert invite_role("operator") == "operator"
    assert invite_role("admin") == "admin"
    try:
        invite_role("superadmin")
        raise AssertionError("superadmin invite should be rejected")
    except TenantScopeError as error:
        assert error.code == "invite-role"


def test_unknown_shop_address_does_not_select_a_platform_admin():
    users = [
        {"id": "root", "role": "superadmin", "shop_id": None, "email": "a@shop.test"},
        {"id": "owner", "role": "admin", "shop_id": "shop-a", "email": "a@shop.test"},
    ]
    assert len(login_matches(users, None, False)) == 2
    assert [user["id"] for user in login_matches(users, "shop-a", True)] == ["owner"]
    assert login_matches(users, None, True) == []


def test_shop_slug_and_starter_records():
    assert shop_slug("Print2Go") == "print2go"
    assert shop_slug("North Shore Print") == "north-shore-print"
    assert shop_slug("") == "shop"
    bundle = new_shop_records(
        shop_id="shop-a",
        name="North Shore",
        slug="north-shore",
        email="owner@north.test",
        owner_name="Ada",
        owner_id="user-a",
        password_hash="hashed",
        created="2026-10-22T00:00:00+00:00",
    )
    assert bundle["shop"]["billing"]["enabled"] is False
    assert bundle["user"]["role"] == "admin"
    assert bundle["user"]["shop_id"] == "shop-a"
    assert bundle["settings"]["_id"] == "shop-a"
    assert bundle["settings"]["artworkRules"]["bleedInches"] == 0.125
    assert [recipe["id"] for recipe in bundle["recipes"]] == ["business-card", "flyer"]


def test_connector_and_download_rules():
    assert bound_shop("shop-a", None) == "shop-a"
    assert bound_shop("shop-a", "") == "shop-a"
    assert bound_shop("shop-a", "shop-a") == "shop-a"
    assert bound_shop(PRINT2GO_SHOP_ID, PRINT2GO_SHOP_ID) == PRINT2GO_SHOP_ID
    for owner, requested in (("shop-a", "shop-b"), ("", "shop-b"), (None, None), (PRINT2GO_SHOP_ID, "shop-b")):
        try:
            bound_shop(owner, requested)
            raise AssertionError(f"{owner} should not bind to {requested}")
        except TenantScopeError as error:
            assert error.code == "connector-shop"
            assert error.status == 401
    assert download_allowed("shop-a", "shop-a", None) is True
    assert download_allowed("shop-a", "shop-a", "shop-a") is True
    assert download_allowed("shop-a", "shop-b", None) is False
    assert download_allowed("shop-a", "shop-a", "shop-b") is False
    assert download_allowed(None, "shop-a", None) is False
    assert download_allowed("", "shop-a", "shop-a") is False


def test_migration_backfills_print2go_and_can_run_twice():
    asyncio.run(_migration_backfills_print2go_and_can_run_twice())


async def _migration_backfills_print2go_and_can_run_twice():
    raw = MemoryDB()
    raw.users.indexes["email_1"] = {}
    raw.cost_profiles.indexes["id_1"] = {}
    await raw.jobs.insert_one({"_id": "j1", "customer": "Ada"})
    await raw.jobs.insert_one({"_id": "kept", "customer": "Other", "shop_id": "already"})
    await raw.users.insert_one({"id": "u1", "email": "a@print.test"})
    await raw.users.insert_one({
        "id": "root",
        "role": "superadmin",
        "email": "root@platform.test",
        "shop_id": None,
    })
    await raw.settings.insert_one({"_id": "shop", "printer": "Press"})
    await raw.connector_state.insert_one({"_id": "agent", "writable": True})
    await raw["pdf_files.files"].insert_one({
        "_id": "f1",
        "metadata": {"sha": "abc", "job_id": "j1"},
    })
    database = TenantDatabase(raw)
    await migrate_tenants(database)
    await raw.shops.update_one({"_id": PRINT2GO_SHOP_ID}, {"$set": {"name": "Print2Go London"}})
    await migrate_tenants(database)
    shops = await raw.shops.find({}).to_list(10)
    assert len(shops) == 1
    assert shops[0]["_id"] == PRINT2GO_SHOP_ID
    assert shops[0]["name"] == "Print2Go London"
    assert shops[0]["slug"] == "print2go"
    assert shops[0]["billing"]["enabled"] is False
    job = await raw.jobs.find_one({"_id": "j1"})
    assert job["shop_id"] == PRINT2GO_SHOP_ID
    assert job["customer"] == "Ada"
    kept = await raw.jobs.find_one({"_id": "kept"})
    assert kept["shop_id"] == "already"
    user = await raw.users.find_one({"id": "u1"})
    assert user["shop_id"] == PRINT2GO_SHOP_ID
    root = await raw.users.find_one({"id": "root"})
    assert root["shop_id"] is None
    settings = await raw.settings.find_one({"_id": "shop"})
    assert settings["kind"] == "settings"
    assert settings["shop_id"] == PRINT2GO_SHOP_ID
    assert settings["printer"] == "Press"
    agent = await raw.connector_state.find_one({"_id": "agent"})
    assert agent["role"] == "agent"
    stored = await raw["pdf_files.files"].find_one({"_id": "f1"})
    assert stored["metadata"]["shop_id"] == PRINT2GO_SHOP_ID
    assert stored["metadata"]["sha"] == "abc"
    assert "email_1" not in await raw.users.index_information()
    assert "id_1" not in await raw.cost_profiles.index_information()


def test_shop_cannot_read_or_change_another_shops_records():
    asyncio.run(_shop_cannot_read_or_change_another_shops_records())


async def _shop_cannot_read_or_change_another_shops_records():
    database = TenantDatabase(MemoryDB())
    with shop_scope("shop-a"):
        await database.jobs.insert_one({"_id": "job-a", "customer": "Ada"})
        await database.settings.insert_one({"_id": "settings-a", "kind": "settings", "printer": "Press A"})
        await database.users.insert_one({"id": "user-a", "email": "a@shop.test", "role": "admin"})
        await database.connector_pairings.insert_one({"_id": "pair-a", "status": "Searching"})
        await database.connector_devices.insert_one({"_id": "device-a", "enabled": True})
        await database.sessions.insert_one({"id": "session-a", "token_hash": "token-a"})
    with shop_scope("shop-b"):
        await database.jobs.insert_one({"_id": "job-b", "customer": "Bea"})
        listed = await database.jobs.find({}).to_list(20)
        assert [row["_id"] for row in listed] == ["job-b"]
        assert await database.jobs.find_one({"_id": "job-a"}) is None
        assert (await database.jobs.update_one({"_id": "job-a"}, {"$set": {"customer": "Stolen"}})).matched_count == 0
        assert (await database.jobs.delete_one({"_id": "job-a"})).matched_count == 0
        assert await database.settings.find_one({"kind": "settings"}) is None
        assert await database.users.find_one({"email": "a@shop.test"}) is None
        assert await database.connector_pairings.find_one({"_id": "pair-a"}) is None
        assert await database.connector_devices.find_one({"_id": "device-a"}) is None
        assert await database.sessions.find_one({"token_hash": "token-a"}) is None
        assert await database.jobs.count_documents({}) == 1
    with shop_scope("shop-a"):
        job = await database.jobs.find_one({"_id": "job-a"})
        assert job["customer"] == "Ada"
        assert job["shop_id"] == "shop-a"
        settings = await database.settings.find_one({"kind": "settings"})
        assert settings["printer"] == "Press A"
        assert await database.users.find_one({"id": "user-a"}) is not None
    with unscoped():
        session = await database.sessions.find_one({"token_hash": "token-a"})
        assert session["shop_id"] == "shop-a"
    try:
        bound_shop("shop-a", "shop-b")
        raise AssertionError("shop A token must be rejected for shop B")
    except TenantScopeError as error:
        assert error.code == "connector-shop"
    with shop_scope(bound_shop("shop-a", None)):
        assert await database.jobs.find_one({"_id": "job-b"}) is None
        assert (await database.jobs.find_one({"_id": "job-a"}))["customer"] == "Ada"


def test_queries_without_a_shop_fail_closed():
    asyncio.run(_queries_without_a_shop_fail_closed())


async def _queries_without_a_shop_fail_closed():
    database = TenantDatabase(MemoryDB())
    try:
        await database.jobs.find_one({"_id": "job-a"})
        raise AssertionError("missing shop should fail")
    except TenantScopeError as error:
        assert error.code == "shop-required"
        assert error.status == 401
    with shop_scope("shop-a"):
        try:
            await database.jobs.insert_one({"_id": "job-a", "shop_id": "shop-b"})
            raise AssertionError("foreign shop_id should be rejected")
        except TenantScopeError as error:
            assert error.code == "shop-mismatch"


def test_new_shop_records_stay_inside_that_shop():
    asyncio.run(_new_shop_records_stay_inside_that_shop())


async def _new_shop_records_stay_inside_that_shop():
    database = TenantDatabase(MemoryDB())
    bundle = new_shop_records(
        shop_id="shop-a",
        name="North Shore",
        slug="north-shore",
        email="owner@north.test",
        owner_name="Ada",
        owner_id="user-a",
        password_hash="hashed",
        created="2026-10-22T00:00:00+00:00",
    )
    await database.raw.shops.insert_one(bundle["shop"])
    with shop_scope("shop-a"):
        await database.users.insert_one(bundle["user"])
        await database.settings.insert_one(bundle["settings"])
        for recipe in bundle["recipes"]:
            await database.recipes.insert_one(recipe)
    with shop_scope("shop-b"):
        assert await database.users.find_one({"email": "owner@north.test"}) is None
        assert await database.settings.find_one({"kind": "settings"}) is None
        assert await database.recipes.count_documents({}) == 0
    with shop_scope("shop-a"):
        owner = await database.users.find_one({"email": "owner@north.test"})
        assert owner["role"] == "admin"
        assert owner["shop_id"] == "shop-a"
        rules = await database.settings.find_one({"kind": "settings"})
        assert rules["artworkRules"]["safeInches"] == 0.25
        names = sorted(row["id"] for row in await database.recipes.find({}).to_list(10))
        assert names == ["business-card", "flyer"]
