# Myraana SaaS readiness

Myraana is the production studio at myraana.com. Print2Go is the shop that uses it today: the London, Ontario store at 201 Queens Ave, one location of the print2go.com franchise. The product name in the studio, the browser title, and the assistant is Myraana. The shop name stored on the workspace stays Print2Go until that shop changes it in settings.

This pass does not deploy, does not touch production data, and does not add a second shop.

## What already exists

- One FastAPI app under `/api`, one MongoDB database, GridFS for artwork, and a React studio.
- First-run administrator setup, then email and password sign-in. Roles are `admin` and `operator`. The session cookie is `p2g_session`.
- Jobs, pinned recipes, proof approval, a Windows connector, and an assistant that only runs when API keys are set on the server.
- Stripe is listed in `backend/requirements.txt` and was not called.

## Tenancy

The database is one shared workspace. Users have no `shop_id`. Email is unique across the whole database. Settings live on a single document, `_id: shop`. A new account created in this database would see Print2Go’s jobs.

Because of that, public signup does not create a user, a password, or a workspace. `POST /api/public/signup` and `POST /api/public/leads` store a lead (shop, email, city, message, intent) and return `workspace: false`. The same address is limited to 8 requests a day. `SAAS_SIGNUP_ENABLED` stays false in `.env.example`.

Isolating shops means a `shop_id` on users, jobs, recipes, settings, files, and leads; a unique email per shop; and a query filter on every read and write. That migration has to be rehearsed against a copy of the live database. It is not in this change.

## Auth and roles

Operators can run jobs. Administrators can change shop settings, artwork rules, recipes, verified printers, operators, and cost inputs. There is no public self-serve shop, no password reset, and no SSO.

## Billing

Billing stays off unless `BILLING_ENABLED=true` and `STRIPE_SECRET_KEY` (`sk_test_` or `sk_live_`), `STRIPE_PRICE_ID` (`price_`), and `STRIPE_WEBHOOK_SECRET` (`whsec_`) are all set. `GET /api/billing` reports that state and never returns the key. `POST /api/billing/checkout` returns 503 even when the flag is on, because checkout is not turned on. The webhook verifies a signature only when billing is enabled and does not change jobs. No price is invented here.

## Deploy and config

The app was built on Emergent. `.emergent/emergent.yml` and the dev-only Craco overlay (`@emergentbase/overlay`, visual edits) are still in the repo. Production should not load that overlay. There is no production Dockerfile.

A small VM can host this without Emergent:

1. Build `frontend/` (`npm run build`).
2. Run the API with uvicorn on `127.0.0.1:8000`, with `MONGO_URL`, `DB_NAME`, and `CORS_ORIGINS` set. Copy `.env.example` and fill it on the server. Do not commit the filled file.
3. Run Caddy from `deploy/Caddyfile`. It terminates TLS for myraana.com, proxies `/api`, serves the studio as a single-page app, and returns `404.html` for unknown public paths.
4. Move the existing MongoDB data only when the founder chooses a window. This change does not migrate it.

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
- Email: leads are stored in MongoDB only. There is no mailbox, no “from” address, and no password-reset mail. Do not invent a Myraana support address. Print2Go London’s published store address stays on print2go.com.
- Hosting: the VM size, who holds MongoDB, and the window to copy production data off Emergent.
- Legal: Privacy and Terms in the site are drafts. Replace them before another shop relies on them.
- Tenant isolation: the shop_id migration, and only then a real signup that creates a workspace.
