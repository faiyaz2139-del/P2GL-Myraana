"""One backup before shop fields are added, and the index rollback old code expects.

TENANT_MIGRATION_BACKUP defaults to on. Set it to off, false, or 0 to skip.
The copy runs once. A second boot finds the marker and does not copy again.
GridFS chunks are not copied. pdf_files.files metadata is.

The previous Print2Go code looks up settings by _id "shop" and the connector
by _id "agent". shop_id, kind, and role can stay. This module only puts back
the global unique indexes that code creates on startup.
"""
import os
from datetime import datetime, timezone


BACKUP_COLLECTION = "tenant_migration_backups"
BACKUP_ID = "tenants"
FILES_METADATA = "pdf_files.files"

# Names match MongoDB's default for create_index("email") and create_index("id").
LEGACY_UNIQUE_INDEXES = (
    {"collection": "users", "name": "email_1", "keys": [("email", 1)]},
    {"collection": "cost_profiles", "name": "id_1", "keys": [("id", 1)]},
)
# Created by the shop-scoped build. Removed only after the legacy indexes exist.
NEW_COMPOUND_INDEXES = (
    {"collection": "users", "name": "shop_email"},
    {"collection": "cost_profiles", "name": "shop_cost"},
)


def backup_enabled():
    value = os.environ.get("TENANT_MIGRATION_BACKUP", "on").strip().lower() or "on"
    return value not in {"0", "false", "off", "no"}


def supports_server_backup(raw):
    """Motor databases can copy on the server. The unit-test memory database cannot."""
    return callable(getattr(type(raw), "list_collection_names", None))


def shared_values(documents, field):
    counts = {}
    for document in documents or []:
        value = document.get(field)
        if value in (None, ""):
            continue
        counts[value] = counts.get(value, 0) + 1
    return sorted(value for value, count in counts.items() if count > 1)


def _pairs(key):
    if hasattr(key, "items"):
        items = key.items()
    else:
        items = key
    return [[str(field), int(direction)] for field, direction in items]


def plain_indexes(info):
    found = []
    for name, spec in (info or {}).items():
        if name == "_id_":
            continue
        entry = {"name": name, "key": _pairs(spec.get("key") or [])}
        if spec.get("unique"):
            entry["unique"] = True
        if "expireAfterSeconds" in spec:
            entry["expireAfterSeconds"] = spec["expireAfterSeconds"]
        found.append(entry)
    return found


def restore_legacy_indexes(database):
    """Recreate the single-shop unique indexes. Leaves shop_id, kind, and role."""
    emails = list(database.users.find({}, {"email": 1, "_id": 0}))
    shared_emails = shared_values(emails, "email")
    if shared_emails:
        raise RuntimeError(
            "Refusing to restore a global unique email index. "
            "These addresses are on more than one user: " + ", ".join(shared_emails)
        )
    profiles = list(database.cost_profiles.find({}, {"id": 1, "_id": 0}))
    shared_ids = shared_values(profiles, "id")
    if shared_ids:
        raise RuntimeError(
            "Refusing to restore a global unique cost-profile index. "
            "These ids are on more than one profile: " + ", ".join(shared_ids)
        )
    restored = []
    for spec in LEGACY_UNIQUE_INDEXES:
        database[spec["collection"]].create_index(
            list(spec["keys"]),
            unique=True,
            name=spec["name"],
        )
        restored.append(spec["name"])
    dropped = []
    for spec in NEW_COMPOUND_INDEXES:
        try:
            database[spec["collection"]].drop_index(spec["name"])
        except Exception:
            continue
        dropped.append(spec["name"])
    return {"restored": restored, "dropped": dropped}


async def backup_before_migration(raw):
    """Copy affected collections inside the same database. Returns the marker or None."""
    if not backup_enabled() or not supports_server_backup(raw):
        return None
    marker = raw[BACKUP_COLLECTION]
    existing = await marker.find_one({"_id": BACKUP_ID})
    if existing and existing.get("status") == "complete":
        return existing
    from p2g.tenancy import TENANT_COLLECTIONS

    present = set(await raw.list_collection_names())
    wanted = [name for name in sorted(TENANT_COLLECTIONS) if name in present]
    if FILES_METADATA in present:
        wanted.append(FILES_METADATA)
    if "shops" in present:
        wanted.append("shops")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    copied = []
    for name in wanted:
        if name.endswith(".chunks"):
            continue
        destination = name.replace(".", "_") + f"_backup_{stamp}"
        cursor = raw[name].aggregate([{"$match": {}}, {"$out": destination}])
        await cursor.to_list(length=None)
        info = await raw[name].index_information()
        copied.append({
            "source": name,
            "dest": destination,
            "indexes": plain_indexes(info),
        })
    record = {
        "_id": BACKUP_ID,
        "status": "complete",
        "suffix": stamp,
        "collections": copied,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    await marker.replace_one({"_id": BACKUP_ID}, record, upsert=True)
    return record
