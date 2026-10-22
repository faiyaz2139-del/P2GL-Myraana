#!/usr/bin/env python3
"""Restore the unique indexes the single-shop Print2Go code expects.

shop_id, settings kind, and connector role are left in place. That code looks
up settings by _id "shop" and the connector by _id "agent", and it ignores
the extra fields.

Run this while this checkout is still on disk, before an Emergent rollback
replaces the files. Copy it aside first if the workspace will be git-reset:

    mkdir -p /tmp/myraana-rollback
    cp backend/scripts/rollback_tenants.py /tmp/myraana-rollback/
    cp -a backend/p2g /tmp/myraana-rollback/p2g
    MONGO_URL=... DB_NAME=... python3 /tmp/myraana-rollback/rollback_tenants.py

Requires MONGO_URL and DB_NAME. Safe to run twice. Refuses to continue when
two user documents share an email, or two cost profiles share an id, because
the old global unique indexes cannot represent that.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from p2g.migration_backup import restore_legacy_indexes
from pymongo import MongoClient


def main():
    url = os.environ.get("MONGO_URL", "").strip()
    name = os.environ.get("DB_NAME", "").strip()
    if not url or not name:
        raise SystemExit("Set MONGO_URL and DB_NAME. No database was changed.")
    client = MongoClient(url)
    try:
        result = restore_legacy_indexes(client[name])
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
    finally:
        client.close()
    print(
        "Restored "
        + ", ".join(result["restored"])
        + ". Dropped "
        + (", ".join(result["dropped"]) if result["dropped"] else "no compound indexes")
        + ". shop_id, kind, and role were left in place."
    )


if __name__ == "__main__":
    main()
