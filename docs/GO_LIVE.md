# Go live on Emergent

Print2Go stays the only shop. Signup and billing stay off. No new environment variable is required. If `EMAIL_PROVIDER` is unset, mail is written to the log. If `TENANT_MIGRATION_BACKUP` is unset, the first boot copies the affected collections once inside the same database. `PLATFORM_SETUP_TOKEN` stays unset until a platform admin is needed.

Emergent's rollback restores the previous code and leaves Mongo as it is. The first boot of this release therefore copies data before it adds `shop_id`. Settings keep `_id` `shop`. The connector keeps `_id` `agent`.

## 1. Back up Mongo

The app backup runs on the first boot of this release when `TENANT_MIGRATION_BACKUP` is on, which is the default. It copies each affected collection to a name like `users_backup_20261022T120000Z` in the same database, stores the index definitions on `tenant_migration_backups`, and copies `pdf_files.files` metadata. It does not copy GridFS chunks.

Do this in the Emergent workspace before that boot if you also want a file you can hold outside the database. From a machine that can reach the database (the workspace terminal can; a laptop cannot):

```text
mongodump --uri="$MONGO_URL" --db="$DB_NAME" --out=/tmp/myraana-mongodump
```

Keep that directory until the smoke tests pass. A second boot does not copy again.

## 2. Point the workspace at main

The Emergent workspace history does not share commits with GitHub `main`. Reset it to `origin/main` before publishing. Keep the env files. Dashboard environment variables can stay as they are. Do not add signup, billing, or mail keys.

```text
mkdir -p /tmp/myraana-keep /tmp/myraana-rollback
cp backend/.env /tmp/myraana-keep/backend.env 2>/dev/null || true
cp frontend/.env /tmp/myraana-keep/frontend.env 2>/dev/null || true
cp backend/scripts/rollback_tenants.py /tmp/myraana-rollback/
cp -a backend/p2g /tmp/myraana-rollback/p2g
git fetch origin
git reset --hard origin/main
cp /tmp/myraana-keep/backend.env backend/.env 2>/dev/null || true
cp /tmp/myraana-keep/frontend.env frontend/.env 2>/dev/null || true
```

`git reset --hard` deletes uncommitted work in the workspace. The copies above are the files to put back.

## 3. Verify the preview

Open the Emergent preview URL after the workspace has restarted.

- `GET /api/` returns `{"name":"Myraana","status":"ready","shop":"Print2Go"}`.
- Sign in as the existing Print2Go admin. The shop address field can stay empty.
- Open an existing job and its file.
- Signup still says a workspace is not open. Billing stays off.

The preview can show "Resuming…" for a minute or two while the pod wakes. That is the preview, not the published site.

## 4. Re-publish

Use Emergent's publish action for the `p2g-production` deployment. Do not change DNS or the custom domain. `myraana.com` already points at that deployment.

After publish, the first request runs the migration. Confirm in the database that `tenant_migration_backups` has one document with `"status": "complete"` and that a Print2Go user has `shop_id` `print2go`.

## 5. Smoke tests

On https://myraana.com:

1. Sign in as the Print2Go admin, then as an operator.
2. Create a business-card job.
3. Upload a PDF with bleed.
4. Run the artwork check through to a `PRINT_READY` file.
5. From the shop computer, confirm the existing connector still heartbeats with `CONNECTOR_SECRET` (`POST /api/connector`). It remains the Print2Go connector only.

## 6. Rollback

Rolling back the Emergent deployment returns the previous code and does not return the previous database. Put the old unique indexes back before, or immediately after, that code rollback. Run this while `MONGO_URL` and `DB_NAME` are the production values:

```text
MONGO_URL="$MONGO_URL" DB_NAME="$DB_NAME" python3 /tmp/myraana-rollback/rollback_tenants.py
```

The script restores `email_1` on users and `id_1` on cost profiles, and drops `shop_email` and `shop_cost`. It leaves `shop_id`, `kind`, and `role` in place. The previous code ignores those fields and still finds settings at `_id` `shop` and the connector at `_id` `agent`. It refuses to run if two users share an email or two cost profiles share an id.

Then use Emergent's rollback to redeploy the previous release. Sign in again. The backup collections from step 1 are still in the database if a document has to be restored by hand. Do not drop them until this sign-in works.

Booting this release again after the down script will drop `email_1` once more and recreate `shop_email`. That is the forward migration, not a second data copy.
