# Myraana SaaS readiness

Myraana is the production studio at myraana.com. Print2Go is the shop that uses it today: the London, Ontario store at 201 Queens Ave, one location of the print2go.com franchise. The product name in the studio, the browser title, and the assistant is Myraana. The shop name stored on the workspace stays Print2Go until that shop changes it in settings.

This pass does not deploy, does not touch production data, and does not change hosting. Shop data is isolated in the API. A second shop is not created unless both signup flags are turned on.

## What already exists

- One FastAPI app under `/api`, one MongoDB database, GridFS for artwork, and a React studio.
- First-run administrator setup, then email and password sign-in. Shop roles are `admin` and `operator`. A separate platform `superadmin` is not a shop member. The session cookie is `p2g_session`.
- Jobs, pinned recipes, proof approval, a Windows connector, and an assistant that only runs when API keys are set on the server.
- Stripe is listed in `backend/requirements.txt` and was not called.

## Tenancy

Every shop-owned query goes through `TenantDatabase` in `backend/p2g/tenancy.py`. The signed-in user’s `shop_id` is applied to reads and writes. A request with no shop is rejected. `SAAS_TENANT_ISOLATION` does not turn that off. The live Print2Go install keeps working because existing rows are stamped `shop_id: "print2go"`.

Shop-owned collections: users, jobs, settings, recipes, connector pairings, connector devices, connector state, executions, cost profiles, machine capabilities, assistant leases, sessions, invites, and password resets. Chat messages and the job audit trail stay on the job, so they follow the job’s shop. GridFS `pdf_files` metadata gets `shop_id`, and a download checks that metadata against the job before any bytes are returned. Chunks are not tagged; the file API is the only read path.

These stay global: the `shops` directory itself, early-access leads, the first-run bootstrap lock, connector nonces, and password-reset attempt counters. The print2go.com catalog JSON is a shared preset library. The recipes a shop saves are private. Billing is still one server-wide switch, left off, with a `billing.enabled: false` placeholder on the shop document. Checkout still returns 503.

Email is unique per shop, not across the whole database. The same address can belong to two shops. Sign-in then asks for the shop address (the slug) and does not list the other shop’s name. A platform administrator’s email cannot also be a shop email.

### Migration

`ensure_collections` runs `migrate_tenants` on API startup. It is safe to run again.

1. Leave `SAAS_SIGNUP_ENABLED` false and `SAAS_TENANT_ISOLATION` off. Back up Mongo before the first boot of this build. This repository does not run that boot against production.
2. The migration upserts a shop `_id: "print2go"`, name Print2Go, slug `print2go`. An existing name is not overwritten.
3. It sets `shop_id: "print2go"` only where the field is missing. A platform user with `shop_id: null` is left alone.
4. It sets `metadata.shop_id` on `pdf_files.files` the same way, without clearing the checksum or job id.
5. The existing settings document `_id: "shop"` gains `kind: "settings"`. The connector document `_id: "agent"` gains `role: "agent"`. Later shops use their own ids. Lookups use `kind` and `role`, so a second shop can have its own settings and connector.
6. It drops the global unique indexes `users.email_1` and `cost_profiles.id_1`, then creates unique `(shop_id, email)` and `(shop_id, id)`.
7. Print2Go’s business-card and flyer recipes are seeded only if that shop does not already have them.

After that boot, confirm a Print2Go user can still sign in and open a job before either signup flag is turned on.

### Signup, invites, and the platform role

`GET /api/public/signup-status` reports `signupOpen`. Both `SAAS_TENANT_ISOLATION` and `SAAS_SIGNUP_ENABLED` must be on (`on`, `true`, or `1`). Otherwise `POST /api/public/signup` stores a lead, drops any password, and returns `workspace: false`. The same address is still limited to 8 requests a day.

When both flags are on, signup creates a shop, an `admin` owner, the default artwork rules, and the business-card and flyer presets, then sets the session cookie. The lead is stored without the password.

Shop administrators invite an operator or another shop administrator with `POST /api/invites`. The response includes a one-time token. The link is `/login?invite=TOKEN` so the existing Caddy routes do not need a new path. The same link is emailed when a provider is configured. `EMAIL_PROVIDER` defaults to `log`, which writes the message to the server log and still returns the token so the administrator can copy it. `off` does not send. `smtp`, `resend`, `postmark`, and `ses` deliver and do not log the body. A failed send still returns the token. `GET /api/invites` lists pending invites without the token hash. Resend rotates the token and the expiry. Revoke marks the invite unusable. Accepting a revoked, accepted, or expired invite fails. The invite cannot grant `superadmin`.

`POST /api/auth/platform-setup` creates one platform `superadmin` when the `X-Platform-Setup-Token` header matches `PLATFORM_SETUP_TOKEN`. If the variable is unset, the route returns 503. Nobody is promoted automatically, including the Print2Go administrator.

`GET /api/platform/shops` returns id, name, slug, status, created time, user count, job count, and last activity. It does not return customers, files, messages, or job documents. The studio screen for this role lists those rows and can approve or suspend a shop. It cannot open a shop workspace. `GET /api/platform/leads` lists signup requests that are not yet shops. Approving one creates an active shop, the starter presets, and an owner invite. The lead has no password, so none is invented. A second approve of the same lead does not create another shop.

A shop status of `suspended` or `pending` blocks password sign-in and the next API call for that shop’s users. A missing status is treated as active so Print2Go keeps working before the backfill, and a later suspend is not cleared when the migration runs again. Self-serve signup, when both flags are on, still creates an active shop and sets the session cookie.

Each shop pairs its own Windows Connector from Shop settings. The pairing code and the device credential are stored as SHA-256 and are scoped to that shop. Pairing works when `CONNECTOR_SECRET` is unset. Another shop cannot list or approve the code.

`CONNECTOR_SECRET` is the legacy bearer path for Print2Go only (`POST /api/connector` and `GET /api/connector/file`). Any other `X-Shop-Id` is rejected with `connector-shop`. A device credential that was hashed with that secret is accepted only when the device belongs to Print2Go, including a device saved before shop ids existed. The same hash on any other shop is rejected.

## Auth and roles

Operators can run jobs in their own shop. Shop administrators can change that shop’s settings, artwork rules, recipes, verified printers, operators, invites, and cost inputs. Platform administrators are separate and cannot use those shop routes. There is no SSO. Self-serve shop creation stays off until both flags are on.

Password reset is `POST /api/public/password-reset` with the email and the shop address. The response is the same sentence whether or not that shop has the address. An empty shop address does not pick a shop. The token is stored as a hash, expires in one hour, and works once. The page is `/login?reset=TOKEN`. Five requests per email and shop in an hour return 429. The limit counts attempts even when no account exists, so the 429 does not reveal that an address is missing. A platform administrator is not reset through this path. A shop that is not active does not receive a reset email, and the public reply stays the same.

## Billing

Billing stays off unless `BILLING_ENABLED=true` and `STRIPE_SECRET_KEY` (`sk_test_` or `sk_live_`), `STRIPE_PRICE_ID` (`price_`), and `STRIPE_WEBHOOK_SECRET` (`whsec_`) are all set. `GET /api/billing` reports that state and never returns the key. `POST /api/billing/checkout` returns 503 even when the flag is on, because checkout is not turned on. The webhook verifies a signature only when billing is enabled and does not change jobs. No price is invented here.

## Deploy and config

The app was built on Emergent. `.emergent/emergent.yml` and the dev-only Craco overlay (`@emergentbase/overlay`, visual edits) are still in the repo. Production should not load that overlay. There is no production Dockerfile.

A small VM can host this without Emergent:

1. Build `frontend/` (`npm run build`).
2. Run the API with uvicorn on `127.0.0.1:8000`, with `MONGO_URL`, `DB_NAME`, and `CORS_ORIGINS` set. Copy `.env.example` and fill it on the server. Do not commit the filled file.
3. Run Caddy from `deploy/Caddyfile`. It terminates TLS for myraana.com, proxies `/api`, serves the studio as a single-page app, and returns `404.html` for unknown public paths.
4. Move the existing MongoDB data only when the founder chooses a window. Hosting is unchanged. The shop backfill described above runs inside the current database when this API boots. It does not move the database to a new host.

The health check is now `{"name":"Myraana","status":"ready","shop":"Print2Go"}`. Connector environment names (`PRINT2GO_*`), the cookie name, and the `p2g` package name are unchanged so the live shop connector keeps working.

The dev server still falls back to the SPA for every path, so a real HTTP 404 shows up with the Caddy config, not inside `npm start`.

## Secrets scan

Searched the repo for private keys and for assigned `sk_live_` / `sk_test_` values. The only hit is the prefix check in `backend/p2g/billing.py`. No `.env` file is committed. `.env.example` contains placeholders only. Do not paste live Stripe, connector, or model keys into git.

## Products

Jobs are not limited to a fixed catalog. A catalog entry is a preset: it prefills size, stock, finish, and options. The values on the job win. `POST /api/jobs` requires `confirmed: true`, a customer, a quantity, and a due date `YYYY-MM-DD`. The pinned recipe is in inches and is what the PDF pipeline checks.

Shop artwork rules, editable by an administrator at `POST /api/artwork-rules`, supply the defaults for new jobs. Print2Go’s design guide is the starting point:

| Rule | Default |
| --- | --- |
| Bleed | 1/8 in (0.125) |
| Safe zone | 1/4 in inside trim (0.25) |
| Colour | CMYK, Pantone kept as spot colour |
| RGB uploads | Warn. A shop can switch this to reject. Nothing is converted. |
| Image DPI | 300, blocking below that |
| Raster text and logos | 1200, recorded as guidance |
| Accepted uploads | JPG, JPEG, GIF, PNG, EPS, AI, PDF, PSD, about 150 MB |
| Output | 300 dpi PDF |

Existing jobs keep the recipe they were given. Older business-card jobs were pinned with a 1/8 in safe zone. New jobs use 1/4 in unless the job or the saved shop rules say otherwise. The integration fixture still sends 0.125 so the historical card file matches.

JPG, PNG, and GIF are placed at their native size and DPI. AI, EPS, and PSD are stored and blocked until the operator exports a PDF (an AI file that is actually a PDF is treated as a PDF). Raster-text at 1200 dpi cannot be separated from a photograph, so it does not block the file. Exact 300 dpi passes.

### Catalog seed

`backend/p2g/data/print2go_catalog.json` is the print2go.com catalog crawled on 2026-10-21. Specs the site does not show stay unknown. `GET /api/products` serves the presets. They are not written as 134 Mongo recipes, so the live recipe history stays the shop’s own versions. A missing database still gets a business-card recipe and a flyer recipe.

| | Count |
| --- | --- |
| Catalog items | 139 |
| Print products | 134 |
| Services | 5 |
| Presets with a parsed size or a custom-size range | 101 |
| Presets with no parsed size | 33 |
| End-to-end tested through PRINT_READY | Business card, flyer |

Featured presets are Business card, Flyer, and Custom product. Card sizes include the US 3.5 × 2 in card. Flyer sizes include 4×6, 5×7, 5.5×8.5, and 8.5×11 in, plus a custom size and an optional fold (half, tri, Z, gate, accordion). The flyer page itself does not list folds; those folds come from the menu pages and stay optional. Fold defaults to none.

The other 101 sized presets can prefill a job: posters, labels, booklets, placemats, and the rest of the parsed catalog. Custom size, stock, finish, sides, fold, shape, die-cut, grommets, binding, and hardware are fields on every print job. A custom-size range on a preset is a hint. The pipeline accepts another size from 0.4 to 150 inches after converting in, mm, cm, or ft. One catalog poster listed 1200 inches; that value is not sent to the PDF builder.

Services cannot become print jobs: Fax Services, Graphic Design and Digital Services, Product Photography, Scanning Services, Shipping Services.

### What is seeded but not fully produced

These 33 catalog rows have no size the parser could trust. They still appear in the product list as custom-spec jobs, and the same options (fold, binding, shape, hardware) can be stored on any print job. The studio does not run a separate machine path for them:

Business Laser Cheques, 3 Hole Punch, Cerlox (Comb) Binding, Coil (Spiral) Binding, Custom Tab Printing, Folding, Perfect Binding, Saddle Stitch Binding, Scoring & Perforation, Stapling, Wire-O Binding, Store Front Signs, Office & Store Branding Signs, Clear Labels & Stickers, Die-Cut Stickers, Kiss-Cut Sticker Singles, Perforated Window Stickers, UV DTF Image Transfer Stickers, Travel Tumbler, Water Bottle, Wine Cup, Custom Gift Wrap, Custom Mugs, Print2Go Studio, Fabric Banners, Popup Counter, Snap Frame, Feather Flags, Tear Drop Flags, Wall Flags, Blue Backed Posters, Giant Cheques, Sold Key Sign.

Also not built, on purpose:

- Booklet or multi-page imposition. Sides stay 1 or 2. Binding and fold are written into the cut instructions.
- Colour conversion. RGB is warned or rejected. It is not turned into CMYK.
- A check that can tell a 1200 dpi logo from a 300 dpi photo.
- Apparel, drinkware, engraving, and sign hardware as manufactured products.
- Pricing from the catalog. The site’s prices were not copied.

## QA behaviour in this pass

- Production route requires a printer name and a stock the shop lists. If any printer has been verified, the route printer must be one of them. An empty verified list still allows a typed printer name, so the current shop is not locked out. The error code is `machine-required`. Proof-only sets the route and does not authorize printing.
- Virtual printers (Print to PDF, XPS, OneNote, Adobe PDF, and the same class of drivers and ports) are dropped when a connector inventory is saved. The settings screen shows device status and production status separately: Connected or Offline, Verified or Not verified.
- After proof approval, the job badge says Proof approved while the active step is Choose production route.
- Capturing the order, uploading artwork, and confirming bleed each wait for an explicit confirmation. A correct bleed does not mark that step done by itself.
- A production review that passes some checks and then stops says how many checks passed. “Not production-ready” is only the headline when nothing passed. The review still stops at the first stop.
- Due date is a calendar date. The last job’s product, size, stock, finish, and options are stored on the shop and in this browser.

## Founder decisions still open

- Stripe: live or test mode, the price, and the webhook endpoint. Checkout code stays unwired until those exist.
- Domains: myraana.com is assumed in the sitemap, robots file, and Caddy config. Confirm DNS and whether www is required.
- Email: invite and password-reset mail can be sent when `EMAIL_PROVIDER` is smtp, resend, postmark, or ses. The default is log, which is not a mailbox. Do not invent a Myraana support address. Print2Go London’s published store address stays on print2go.com.
- Hosting: republish on Emergent from `origin/main` using `docs/GO_LIVE.md`. The first boot copies the affected collections once, then adds `shop_id`. Emergent rollback restores code only, so the down script in that checklist puts the old unique indexes back.
- Legal: Privacy and Terms in the site are drafts. Replace them before another shop relies on them.
- Second shop go-live, after a copy of the database has been booted with this build and Print2Go sign-in still works. Flags stay off until that check. Invite email, password reset, the platform shop screen, and per-shop connector pairing exist. A live mailbox still needs `EMAIL_PROVIDER` set to smtp, resend, postmark, or ses, because the default is log. Still missing before that is safe: per-shop Stripe (billing stays global and off), a data export or delete tool, and finished legal text. The shared connector secret stays Print2Go’s legacy path. GridFS chunks are not tagged. Hosting and DNS remain on hold. There is no SSO.
