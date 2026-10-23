import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.cors import CORSMiddleware


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from p2g.ai import configured as ai_configured, conversation_events
from p2g.agent_bridge import evaluate_agents
from p2g.billing import billing_status, checkout_available
from p2g.build_metadata import read_build_metadata
from p2g.card_flow import (
    AUTO_ACTOR,
    apply_card_defaults,
    apply_known_stock,
    auto_send_ready,
    clamp_limit,
    duplo_line,
    encode_cursor,
    fiery_target,
    keep_production_route,
    known_finish,
    manual_press_message,
    mark_sent_to_fiery,
    stage_fiery_hold,
    print_order,
    queue_bucket,
    queue_page_query,
    QUEUE_IDS,
)
from p2g.automatic import automatic_mode, timeline
from p2g.connector_pairing import (
    approve_pairing,
    approve_proof_token,
    claim_pairing,
    create_enrollment_package,
    create_pairing,
    create_proof_link,
    heartbeat as paired_heartbeat,
    devices as paired_devices,
    hold_pdf,
    list_enrollments,
    note_prepared_route,
    pairings,
    pairing_status,
    proof_for_token,
    queue_automatic_hold,
    redeem_enrollment,
    revoke_enrollment,
)
from p2g.catalog_seed import SpecError
from p2g.costing import CostValidationError, cost_profile
from p2g.core import AppError, db, new_id, now
from p2g.present import status_label
from p2g.printer_discovery import normalise_reported, preferred_printer, scan_is_due
from p2g.printers import filter_printers, is_virtual_printer, printer_status
from p2g.london_card import (
    WORKFLOW_NAME,
    apply_production_event,
    chart_file_rules,
    connector_production_hook,
    fresh_checklist,
    is_london_card,
    london_business_card_recipe,
    merge_production,
    normalise_stock_list,
    pin_job_recipe,
)
from p2g.products import (
    artwork_rules_from_settings,
    normalize_artwork_rules,
    preset_by_id,
    public_catalog,
    resolve_spec,
)
from p2g.public_forms import FormError, lead_from_payload, signup_result
from p2g.account_access import (
    SUSPENDED_MESSAGE,
    exclude_archived,
    public_lead,
    removal_denial,
    reset_is_limited,
    reset_request_message,
    shop_allows_sign_in,
    shop_directory_row,
)
from p2g.mail import MailError, public_base, send_email
from p2g.membership import end_user_sessions
from p2g.shops import (
    accept_invite,
    confirm_password_reset,
    create_invite,
    issue_password_reset,
    list_invites,
    open_shop_from_lead,
    provision_shop,
    replace_settings,
    resend_invite,
    revoke_invite,
    save_connector_agent,
)
from p2g.tenancy import (
    PRINT2GO_SHOP_ID,
    TenantScopeError,
    bound_shop,
    clear_shop,
    is_superadmin,
    login_matches,
    reset_shop,
    shop_scope,
    signup_is_open,
    unscoped,
)
from p2g.uploads import classify_upload
from p2g.pdfcheck import render_page
from p2g.workflow import (
    DEFAULT_RECIPE,
    create_file,
    current_user,
    ensure_collections,
    file_bytes,
    get_job,
    latest,
    password_hash,
    password_matches,
    issue_session,
    public,
    readiness,
    record_event,
    recover_interrupted_executions,
    require_admin,
    require_completed,
    require_user,
    reset_from,
    process_with_lease,
    save_job,
    tasks,
    update_task,
)


app = FastAPI(title="Myraana")
api = APIRouter(prefix="/api")


class ShopContextMiddleware:
    """Clear shop scope around each request without buffering the body."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        tokens = clear_shop()
        try:
            await self.app(scope, receive, send)
        finally:
            reset_shop(tokens)


def error_response(error):
    if isinstance(error, AppError):
        body = {"error": error.message}
        if getattr(error, "code", None):
            body["code"] = error.code
        return JSONResponse(body, status_code=error.status)
    return JSONResponse({"error": "Unable to complete the request. Retry safely."}, status_code=500)


def assert_origin(request):
    origin = request.headers.get("origin")
    configured = {
        value.strip().rstrip("/")
        for value in os.environ["CORS_ORIGINS"].split(",")
        if value.strip()
    }
    configured.add(str(request.base_url).rstrip("/"))
    forwarded_host = request.headers.get("x-forwarded-host")
    forwarded_proto = request.headers.get("x-forwarded-proto", "https")
    request_host = request.headers.get("host")
    if forwarded_host:
        configured.add(f"{forwarded_proto}://{forwarded_host}".rstrip("/"))
    if request_host:
        configured.add(f"{forwarded_proto}://{request_host}".rstrip("/"))
    if origin and origin.rstrip("/") not in configured:
        raise AppError("Request origin is not allowed.", 403)


def valid_text(value, label, maximum, minimum=1):
    value = str(value or "").strip()
    if not minimum <= len(value) <= maximum:
        raise AppError(f"{label} must be between {minimum} and {maximum} characters.", 400)
    return value


def valid_due(value):
    value = valid_text(value, "Due date", 10)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise AppError("Due date must be a real date in YYYY-MM-DD format.", 400) from error
    return value


def connector_online(devices, agent):
    if any((device or {}).get("status") == "Connected" for device in devices or []):
        return True
    return bool(agent and agent.get("writable"))


def discovered_printers(settings_data, devices):
    verified = settings_data.get("verifiedPrinters") or []
    online = "Connected" if any((device or {}).get("status") == "Connected" for device in devices or []) else "Offline"
    hostname = ""
    stored = settings_data.get("discoveredPrinters")
    if isinstance(stored, list):
        source = stored
    else:
        source = []
        for device in devices or []:
            inventory = device.get("inventory") or {}
            hostname = inventory.get("hostname") or hostname
            source.extend(filter_printers(inventory.get("printers")))
            if device.get("status") == "Connected":
                online = "Connected"
    for device in devices or []:
        hostname = ((device.get("inventory") or {}).get("hostname")) or hostname
    rows = []
    for printer in normalise_reported(filter_printers(source)):
        row = printer_status(printer, verified, online)
        row.update({
            "model": printer.get("model") or "",
            "address": printer.get("address") or "",
            "protocol": printer.get("protocol") or "",
            "isFiery": bool(printer.get("isFiery")),
            "device": hostname or "Shop connector",
        })
        rows.append(row)
    return rows


async def shop_settings():
    settings = await db.settings.find_one({"kind": "settings"})
    if settings:
        settings.pop("_id", None)
        settings.pop("kind", None)
        settings.pop("shop_id", None)
        settings.setdefault("shopName", "Print2Go")
        settings.setdefault("verifiedPrinters", [])
        settings.setdefault("jobDefaults", None)
        settings.setdefault("automaticMode", True)
        return settings
    return {
        "printer": "",
        "stocks": ["14pt matte", "16pt soft touch", "100lb Gloss Text", "28lb Smooth Text"],
        "sides": [1, 2],
        "instructions": "Operator-assisted RIP handoff. No automatic printing.",
        "version": 1,
        "shopName": "Print2Go",
        "verifiedPrinters": [],
        "jobDefaults": None,
        "automaticMode": True,
    }


@app.on_event("startup")
async def startup():
    await ensure_collections()
    await recover_interrupted_executions()


@api.get("/")
async def health():
    return {"name": "Myraana", "status": "ready", "shop": "Print2Go"}


@api.get("/build-info")
async def build_info():
    return read_build_metadata()


@api.get("/auth")
async def auth_status(request: Request):
    user = await current_user(request)
    with unscoped():
        count = await db.users.count_documents({})
    return {"user": user, "needsSetup": count == 0}


@api.post("/auth/setup")
async def auth_setup(request: Request):
    assert_origin(request)
    payload = await request.json()
    name = valid_text(payload.get("name"), "Name", 80)
    email = valid_text(payload.get("email"), "Email", 200).lower()
    password = str(payload.get("password") or "")
    if "@" not in email or len(password) < 12 or len(password) > 200:
        raise AppError("Use a valid email and a password of at least 12 characters.", 400)
    claim = await db.bootstrap.find_one_and_update(
        {"_id": "first-run", "configured": False},
        {"$set": {"configured": True, "claimed": now()}},
        return_document=False,
    )
    if not claim:
        raise AppError("An administrator is already configured.")
    user = {
        "id": new_id(),
        "name": name,
        "email": email,
        "role": "admin",
        "shop_id": PRINT2GO_SHOP_ID,
    }
    try:
        with shop_scope(PRINT2GO_SHOP_ID):
            await db.users.insert_one({**user, "password": password_hash(password), "created": now()})
    except Exception as error:
        await db.bootstrap.update_one({"_id": "first-run"}, {"$set": {"configured": False}})
        raise AppError("Administrator setup could not be saved. Retry safely.") from error
    cookie, safe_user = await issue_session(request, user)
    response = JSONResponse({"user": safe_user})
    response.set_cookie(**cookie)
    return response


@api.post("/auth/login")
async def auth_login(request: Request):
    assert_origin(request)
    payload = await request.json()
    email = valid_text(payload.get("email"), "Email", 200).lower()
    password = str(payload.get("password") or "")
    shop_slug = str(payload.get("shop") or payload.get("shopSlug") or "").strip().lower()
    with unscoped():
        found = await db.users.find({"email": email}).to_list(20)
    shop_id = None
    if shop_slug:
        shop = await db.shops.find_one({"slug": shop_slug})
        shop_id = shop["_id"] if shop else None
    matches = login_matches(found, shop_id, bool(shop_slug))
    if len(matches) > 1:
        raise AppError(
            "This email is used by more than one shop. Enter the shop address.",
            400,
        )
    user = matches[0] if matches else None
    if not user or not password_matches(password, user["password"]):
        raise AppError("Email or password is incorrect.", 401)
    if user.get("shop_id"):
        shop = await db.shops.find_one({"_id": user["shop_id"]}, {"status": 1})
        if not shop or not shop_allows_sign_in(shop.get("status")):
            raise AppError(SUSPENDED_MESSAGE, 403)
    cookie, safe_user = await issue_session(request, user)
    response = JSONResponse({"user": safe_user})
    response.set_cookie(**cookie)
    return response


@api.post("/auth/logout")
async def auth_logout(request: Request):
    assert_origin(request)
    raw = request.cookies.get("p2g_session")
    if raw:
        from p2g.core import sha256

        with unscoped():
            await db.sessions.delete_one({"token_hash": sha256(raw)})
    response = JSONResponse({"ok": True})
    response.delete_cookie("p2g_session", path="/")
    return response


@api.get("/products")
async def products(request: Request):
    require_user(await current_user(request))
    catalog = public_catalog()
    catalog["artworkRules"] = artwork_rules_from_settings(await shop_settings())
    return catalog


@api.post("/public/leads")
async def create_lead(request: Request):
    assert_origin(request)
    return await _store_lead(await request.json(), "early-access")


@api.get("/public/signup-status")
async def public_signup_status():
    return {"signupOpen": signup_is_open()}


@api.post("/public/signup")
async def public_signup(request: Request):
    """Open a shop only when both signup flags are on. Otherwise store a lead."""
    assert_origin(request)
    payload = await request.json()
    if not signup_is_open():
        payload.pop("password", None)
        await _store_lead(payload, "signup")
        return signup_result()
    password = str(payload.pop("password", "") or "")
    try:
        lead = lead_from_payload(payload, payload.get("intent") or "signup")
    except FormError as error:
        raise AppError(error.message, 400) from error
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    if await db.leads.count_documents({"email": lead["email"], "created": {"$gt": cutoff}}) >= 8:
        raise AppError("Too many requests for this email. Try again tomorrow.", 429)
    user, shop = await provision_shop(lead["shop"], lead["email"], password, lead["name"])
    await db.leads.insert_one({**lead, "id": new_id(), "created": now()})
    cookie, safe_user = await issue_session(request, user)
    response = JSONResponse({
        "ok": True,
        "workspace": True,
        "slug": shop["slug"],
        "message": "Your shop workspace is ready.",
        "user": safe_user,
    })
    response.set_cookie(**cookie)
    return response


def _platform_token_matches(supplied, expected):
    if not supplied or not expected:
        return False
    supplied_bytes = supplied.encode()
    expected_bytes = expected.encode()
    if len(supplied_bytes) != len(expected_bytes):
        return False
    return hmac.compare_digest(supplied_bytes, expected_bytes)


@api.post("/auth/platform-setup")
async def platform_setup(request: Request):
    """Create the one platform administrator. This is not a shop login."""
    assert_origin(request)
    expected = os.environ.get("PLATFORM_SETUP_TOKEN") or ""
    if not expected:
        raise AppError("Platform setup is not configured.", 503)
    supplied = request.headers.get("x-platform-setup-token") or ""
    if not _platform_token_matches(supplied, expected):
        raise AppError("Platform setup token is incorrect.", 401)
    payload = await request.json()
    name = valid_text(payload.get("name"), "Name", 80)
    email = valid_text(payload.get("email"), "Email", 200).lower()
    password = str(payload.get("password") or "")
    if "@" not in email or len(password) < 12 or len(password) > 200:
        raise AppError("Use a valid email and a password of at least 12 characters.", 400)
    with unscoped():
        if await db.users.find_one({"role": "superadmin"}):
            raise AppError("A platform administrator already exists.", 409)
        if await db.users.find_one({"email": email}):
            raise AppError("That email is already used.", 409)
        user = {
            "id": new_id(),
            "name": name,
            "email": email,
            "role": "superadmin",
            "shop_id": None,
            "password": password_hash(password),
            "created": now(),
        }
        await db.users.insert_one(user)
    cookie, safe_user = await issue_session(request, user)
    response = JSONResponse({"user": safe_user})
    response.set_cookie(**cookie)
    return response


@api.get("/platform/shops")
async def platform_shops(request: Request):
    user = await current_user(request)
    if not is_superadmin(user):
        raise AppError("Only a platform administrator can do that.", 403)
    return await _platform_directory()


def _require_platform(user):
    if not is_superadmin(user):
        raise AppError("Only a platform administrator can do that.", 403)
    return user


async def _platform_directory():
    with unscoped():
        rows = await db.shops.find({}).sort("created", -1).to_list(500)
        listed = []
        for row in rows:
            shop_id = row.get("_id")
            users = await db.users.count_documents({"shop_id": shop_id, "active": {"$ne": False}})
            jobs = await db.jobs.count_documents({"shop_id": shop_id})
            latest = await db.jobs.find(
                {"shop_id": shop_id},
                {"updated": 1, "customer": 0, "files": 0, "messages": 0, "events": 0, "spec": 0},
            ).sort("updated", -1).to_list(1)
            last = latest[0].get("updated") if latest else None
            listed.append(shop_directory_row(row, users, jobs, last))
    return listed


@api.post("/platform/shops/{shop_id}/suspend")
async def suspend_shop(shop_id: str, request: Request):
    assert_origin(request)
    _require_platform(await current_user(request))
    return await _set_shop_status(shop_id, "suspended")


@api.post("/platform/shops/{shop_id}/approve")
async def approve_shop(shop_id: str, request: Request):
    assert_origin(request)
    _require_platform(await current_user(request))
    return await _set_shop_status(shop_id, "active")


async def _set_shop_status(shop_id, status):
    with unscoped():
        result = await db.shops.update_one({"_id": shop_id}, {"$set": {"status": status}})
    if not getattr(result, "matched_count", 0):
        raise AppError("That shop was not found.", 404)
    return {"ok": True, "id": shop_id, "status": status}


@api.get("/platform/leads")
async def platform_leads(request: Request):
    _require_platform(await current_user(request))
    with unscoped():
        rows = await db.leads.find({"converted": {"$ne": True}}).sort("created", -1).to_list(200)
    return [public_lead(row) for row in rows]


@api.post("/platform/leads/{lead_id}/approve")
async def approve_platform_lead(lead_id: str, request: Request):
    assert_origin(request)
    actor = _require_platform(await current_user(request))
    with unscoped():
        lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise AppError("That request was not found.", 404)
    if lead.get("converted") and lead.get("shop_id"):
        return {"ok": True, "already": True, "shopId": lead["shop_id"]}
    shop, invite = await open_shop_from_lead(
        lead,
        actor["id"],
        link_for=lambda token: _invite_link(request, token),
    )
    await db.leads.update_one(
        {"id": lead_id},
        {"$set": {"converted": True, "shop_id": shop["_id"]}},
    )
    body = {
        "ok": True,
        "shopId": shop["_id"],
        "slug": shop["slug"],
        "emailed": bool(invite.get("emailed")),
        "provider": invite.get("provider"),
    }
    if invite.get("token"):
        body["token"] = invite["token"]
    return body


async def _store_lead(payload, default_intent):
    try:
        lead = lead_from_payload(payload, payload.get("intent") or default_intent)
    except FormError as error:
        raise AppError(error.message, 400) from error
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    if await db.leads.count_documents({"email": lead["email"], "created": {"$gt": cutoff}}) >= 8:
        raise AppError("Too many requests for this email. Try again tomorrow.", 429)
    await db.leads.insert_one({**lead, "id": new_id(), "created": now()})
    return {"ok": True}


@api.get("/billing")
async def billing(request: Request):
    require_user(await current_user(request))
    return billing_status()


@api.post("/billing/checkout")
async def billing_checkout(request: Request):
    assert_origin(request)
    require_admin(await current_user(request))
    if not checkout_available():
        raise AppError("Billing is disabled.", 503)
    raise AppError("Stripe checkout is not turned on for this shop yet.", 503)


@api.post("/billing/webhook")
async def billing_webhook(request: Request):
    if not checkout_available():
        raise AppError("Billing is disabled.", 503)
    import stripe

    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    try:
        event = stripe.Webhook.construct_event(
            await request.body(),
            request.headers.get("stripe-signature", ""),
            os.environ["STRIPE_WEBHOOK_SECRET"],
        )
    except Exception as error:
        raise AppError("Billing webhook could not be verified.", 400) from error
    return {"received": True, "type": event.get("type")}


@api.get("/recipes")
async def recipes(request: Request):
    require_user(await current_user(request))
    return await db.recipes.find({}, {"_id": 0}).sort("version", -1).to_list(100)


@api.post("/recipes")
async def create_recipe(request: Request):
    assert_origin(request)
    require_admin(await current_user(request))
    payload = await request.json()
    name = valid_text(payload.get("name"), "Recipe name", 100)
    product_id = str(payload.get("product") or payload.get("id") or "business-card")
    if preset_by_id(product_id) is None or preset_by_id(product_id)["kind"] == "service":
        raise AppError("Choose a print product for this recipe.", 400)
    fields = {}
    for key, low, high in (
        ("width", 0.4, 150),
        ("height", 0.4, 150),
        ("bleed", 0, 1),
        ("safe", 0, 1),
        ("minDpi", 72, 1200),
    ):
        try:
            fields[key] = float(payload.get(key))
        except (TypeError, ValueError) as error:
            raise AppError(f"{key} is invalid.", 400) from error
        if not low <= fields[key] <= high:
            raise AppError(f"{key} is outside the supported range.", 400)
    if fields["safe"] * 2 >= min(fields["width"], fields["height"]):
        raise AppError("Safe margin must fit within the finished size.", 400)
    latest_recipe = await db.recipes.find_one({"id": product_id}, sort=[("version", -1)])
    recipe = {
        "id": product_id,
        "product": product_id,
        "version": (latest_recipe["version"] + 1) if latest_recipe else 1,
        "name": name,
        **fields,
        "minDpi": int(fields["minDpi"]),
        "cutInstructions": valid_text(payload.get("cutInstructions"), "Instructions", 2000),
        "created": now(),
    }
    if product_id == "business-card" or (latest_recipe and latest_recipe.get("production")):
        base = latest_recipe if latest_recipe and latest_recipe.get("production") else None
        if product_id == "business-card" and base is None:
            base = london_business_card_recipe()
        if base:
            try:
                edits = payload.get("production") if isinstance(payload.get("production"), dict) else {}
                recipe["production"] = merge_production(base, edits)
            except (TypeError, ValueError) as error:
                raise AppError("Cutter settings are invalid.", 400) from error
            recipe["workflow"] = base.get("workflow") or WORKFLOW_NAME
            recipe["fileRules"] = chart_file_rules() if product_id == "business-card" else base.get("fileRules")
    await db.recipes.insert_one(recipe.copy())
    return public(recipe)


@api.get("/settings")
async def settings(request: Request):
    require_user(await current_user(request))
    settings_data = await shop_settings()
    agent = await db.connector_state.find_one({"role": "agent"}, {"_id": 0})
    devices = await paired_devices()
    return {
        **settings_data,
        "artworkRules": artwork_rules_from_settings(settings_data),
        "aiConnected": ai_configured(),
        "connectorConfigured": True,
        "legacyConnector": bool(os.environ.get("CONNECTOR_SECRET")),
        "billing": billing_status(),
        "agent": agent,
        "connected": bool(agent and agent.get("writable")),
        "pairings": await pairings(),
        "pairedDevices": devices,
        "connectorConnected": connector_online(devices, agent),
        "scanPending": scan_is_due(settings_data),
        "discoveredPrinters": discovered_printers(settings_data, devices),
        "enrollments": await list_enrollments(),
        "automaticMode": automatic_mode(settings_data),
    }


@api.post("/connector-pairings")
async def start_connector_pairing(request: Request):
    assert_origin(request)
    return await create_pairing(require_admin(await current_user(request)))


@api.post("/connector-pairings/claim")
async def claim_connector_pairing(request: Request):
    return await claim_pairing(await request.json())


@api.post("/connector-pairings/{pairing_id}/approve")
async def approve_connector_pairing(pairing_id: str, request: Request):
    assert_origin(request)
    return await approve_pairing(pairing_id, require_admin(await current_user(request)))


@api.post("/connector-pairings/{pairing_id}/poll")
async def poll_connector_pairing(pairing_id: str, request: Request):
    payload = await request.json()
    return await pairing_status(pairing_id, str(payload.get("claimSecret") or ""))


@api.post("/connector-enrollments")
async def download_connector_setup(request: Request):
    """One setup exe for this shop. Admin and operator. The token is the filename."""
    assert_origin(request)
    user = require_user(await current_user(request))
    if user.get("role") not in {"admin", "operator"}:
        raise AppError("Only an administrator or operator can connect this computer.", 403)
    origin = request.headers.get("origin") or ""
    content, filename = await create_enrollment_package(user, [origin, public_base(request)])
    safe = str(filename).replace("\\", "").replace('"', "").replace("\r", "").replace("\n", "")
    return Response(
        content,
        media_type="application/vnd.microsoft.portable-executable",
        headers={
            "Content-Disposition": f'attachment; filename="{safe}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@api.post("/connector-enrollments/redeem")
async def redeem_connector_enrollment(request: Request):
    return await redeem_enrollment(await request.json())


@api.post("/connector-enrollments/{enrollment_id}/revoke")
async def revoke_connector_enrollment(enrollment_id: str, request: Request):
    assert_origin(request)
    return await revoke_enrollment(enrollment_id, require_admin(await current_user(request)))


@api.post("/connector-devices/heartbeat")
async def paired_connector_heartbeat(request: Request):
    return await paired_heartbeat(request, await request.json())


@api.get("/connector-devices/holds/{job_id}")
async def connector_hold_file(job_id: str, request: Request):
    content, name = await hold_pdf(request, job_id)
    safe = name.replace("\r", "").replace("\n", "")[:180]
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


@api.post("/settings")
async def update_settings(request: Request):
    assert_origin(request)
    require_admin(await current_user(request))
    payload = await request.json()
    current = await shop_settings()
    stocks = normalise_stock_list([valid_text(item, "Stock", 140) for item in payload.get("stocks", [])])
    if len(stocks) > 80:
        raise AppError("Use at most 80 supported stocks.", 400)
    printer = str(payload.get("printer") or "").strip()[:120]
    if printer and is_virtual_printer({"name": printer}):
        raise AppError("Virtual printers such as Print to PDF cannot be the production route.", 400)
    data = {
        "printer": printer,
        "stocks": stocks,
        "sides": [side for side in payload.get("sides", [1, 2]) if side in [1, 2]],
        "instructions": str(payload.get("instructions") or "")[:2000],
        "version": current["version"] + 1,
        "updated": now(),
        "shopName": str(payload.get("shopName") or current.get("shopName") or "Print2Go")[:80],
        "verifiedPrinters": current.get("verifiedPrinters") or [],
        "jobDefaults": current.get("jobDefaults"),
        "artworkRules": current.get("artworkRules"),
        "fieryAutoSend": payload.get("fieryAutoSend") is True if "fieryAutoSend" in payload else current.get("fieryAutoSend") is True,
        "automaticMode": payload.get("automaticMode") is not False if "automaticMode" in payload else current.get("automaticMode") is not False,
    }
    for key in ("discoveredPrinters", "discoveredAt", "scanRequestedAt", "scanFulfilledAt"):
        if key in current:
            data[key] = current[key]
    changed = any(
        current.get(key) != data.get(key)
        for key in ("printer", "stocks", "sides", "instructions")
    )
    if not changed:
        data["version"] = current["version"]
    await replace_settings(data)
    if changed:
        affected = await db.jobs.find(
            exclude_archived({"state": "active", "tasks.12.status": {"$ne": "Completed"}}),
            {"_id": 0},
        ).to_list(500)
        for job in affected:
            if not job.get("route"):
                continue
            reset_from(
                job,
                8,
                "Shop settings changed. Choose a route and repeat readiness before authorization.",
            )
            if job.get("approval"):
                job["approval"]["generation"] = job["generation"]
            if job.get("verification"):
                job["verification"]["generation"] = job["generation"]
            record_event(
                job,
                "Verified proof approval retained because the production PDF did not change; "
                "route, readiness, and authorization were revoked.",
            )
            await save_job(job)
    return {"ok": True}


@api.post("/artwork-rules")
async def save_artwork_rules(request: Request):
    assert_origin(request)
    require_admin(await current_user(request))
    try:
        rules = normalize_artwork_rules(await request.json())
    except SpecError as error:
        raise AppError(error.message, 400) from error
    current = await shop_settings()
    await db.settings.update_one(
        {"kind": "settings"},
        {
            "$set": {
                "kind": "settings",
                "artworkRules": rules,
                "shopName": current.get("shopName") or "Print2Go",
                "printer": current.get("printer") or "",
                "stocks": current.get("stocks") or [],
                "sides": current.get("sides") or [1, 2],
                "instructions": current.get("instructions") or "",
                "version": current.get("version") or 1,
                "verifiedPrinters": current.get("verifiedPrinters") or [],
            }
        },
        upsert=True,
    )
    return {"ok": True, "artworkRules": rules}


@api.post("/printers/verify")
async def verify_printer(request: Request):
    assert_origin(request)
    user = require_admin(await current_user(request))
    payload = await request.json()
    name = valid_text(payload.get("name"), "Printer", 120)
    candidate = {"name": name, "driver": payload.get("driver"), "port": payload.get("port")}
    if is_virtual_printer(candidate):
        raise AppError("Virtual printers such as Print to PDF, OneNote and Adobe PDF cannot be verified.", 400)
    current = await shop_settings()
    verified = [item for item in (current.get("verifiedPrinters") or []) if item != name]
    verified.append(name)
    printer = name if payload.get("use", True) else (current.get("printer") or name)
    changed = printer != (current.get("printer") or "")
    version = int(current.get("version") or 1) + (1 if changed else 0)
    await db.settings.update_one(
        {"kind": "settings"},
        {
            "$set": {
                "kind": "settings",
                "printer": printer,
                "verifiedPrinters": verified,
                "stocks": current.get("stocks") or [],
                "sides": current.get("sides") or [1, 2],
                "instructions": current.get("instructions") or "",
                "version": version,
                "shopName": current.get("shopName") or "Print2Go",
                "updated": now(),
                "verifiedBy": user["id"],
            }
        },
        upsert=True,
    )
    if changed:
        affected = await db.jobs.find(
            exclude_archived({"state": "active", "tasks.12.status": {"$ne": "Completed"}}),
            {"_id": 0},
        ).to_list(500)
        for job in affected:
            if not job.get("route"):
                continue
            reset_from(
                job,
                8,
                "Shop settings changed. Choose a route and repeat readiness before authorization.",
            )
            await save_job(job)
    return {"ok": True, "printer": printer, "verifiedPrinters": verified}


@api.get("/printers/discovered")
async def list_discovered_printers(request: Request):
    require_user(await current_user(request))
    settings_data = await shop_settings()
    agent = await db.connector_state.find_one({"role": "agent"}, {"_id": 0})
    devices = await paired_devices()
    return {
        "printers": discovered_printers(settings_data, devices),
        "connectorConnected": connector_online(devices, agent),
        "scanPending": scan_is_due(settings_data),
    }


@api.post("/printers/scan")
async def request_printer_scan(request: Request):
    assert_origin(request)
    require_admin(await current_user(request))
    stamp = now()
    result = await db.settings.update_one(
        {"kind": "settings"},
        {"$set": {"scanRequestedAt": stamp}},
    )
    if not result.matched_count:
        data = await shop_settings()
        data["scanRequestedAt"] = stamp
        await replace_settings(data)
    return {"ok": True, "scan": True}


@api.get("/cost-profiles")
async def list_cost_profiles(request: Request):
    require_admin(await current_user(request))
    return await db.cost_profiles.find({}, {"_id": 0}).sort("created", -1).to_list(100)


@api.post("/cost-profiles")
async def save_cost_profile(request: Request):
    assert_origin(request)
    user = require_admin(await current_user(request))
    try:
        profile = cost_profile(await request.json())
    except CostValidationError as error:
        raise AppError(str(error), 400) from error
    profile.update({"id": new_id(), "created": now(), "created_by": user["id"]})
    await db.cost_profiles.insert_one(profile.copy())
    return public(profile)


@api.get("/users")
async def users(request: Request):
    require_admin(await current_user(request))
    return await db.users.find({"active": {"$ne": False}}, {"_id": 0, "password": 0}).to_list(100)


@api.post("/users/{user_id}/remove")
async def remove_user(user_id: str, request: Request):
    """Deactivate a shop user and end their sessions. The caller and the last admin stay."""
    assert_origin(request)
    actor = require_admin(await current_user(request))
    target = await db.users.find_one({"id": user_id}, {"_id": 0, "password": 0})
    admins = await db.users.count_documents({"role": "admin", "active": {"$ne": False}})
    denial = removal_denial(actor["id"], target, admins)
    if denial:
        status = 404 if not target or target.get("active") is False else 400
        raise AppError(denial, status)
    await db.users.update_one({"id": user_id}, {"$set": {"active": False, "removed": now()}})
    await end_user_sessions(db, user_id)
    return {"ok": True}


@api.post("/users")
async def create_user(request: Request):
    assert_origin(request)
    require_admin(await current_user(request))
    payload = await request.json()
    role = payload.get("role")
    if role == "superadmin" or role not in {"admin", "operator"}:
        raise AppError("Choose administrator or operator.", 400)
    password = str(payload.get("password") or "")
    if len(password) < 12 or len(password) > 200:
        raise AppError("Initial password must be 12 to 200 characters.", 400)
    user = {
        "id": new_id(),
        "name": valid_text(payload.get("name"), "Name", 80),
        "email": valid_text(payload.get("email"), "Email", 200).lower(),
        "role": role,
        "password": password_hash(password),
        "created": now(),
    }
    with unscoped():
        if await db.users.find_one({"email": user["email"], "role": "superadmin"}):
            raise AppError("That email cannot be used for a shop.", 409)
    try:
        await db.users.insert_one(user)
    except Exception as error:
        raise AppError("That email is already in this shop.", 409) from error
    return {"ok": True}


def _invite_link(request, token):
    return f"{public_base(request)}/login?invite={token}"


async def _shop_label(user):
    with unscoped():
        shop = await db.shops.find_one({"_id": user.get("shop_id")})
    return (shop or {}).get("name") or "your shop"


@api.get("/invites")
async def pending_invites(request: Request):
    require_admin(await current_user(request))
    return await list_invites()


@api.post("/invites")
async def invite_operator(request: Request):
    assert_origin(request)
    user = require_admin(await current_user(request))
    shop_name = await _shop_label(user)
    return await create_invite(
        user,
        await request.json(),
        link_for=lambda token: _invite_link(request, token),
        shop_name=shop_name,
    )


@api.post("/invites/{invite_id}/resend")
async def resend_operator_invite(invite_id: str, request: Request):
    assert_origin(request)
    user = require_admin(await current_user(request))
    shop_name = await _shop_label(user)
    return await resend_invite(
        user,
        invite_id,
        lambda token: _invite_link(request, token),
        shop_name,
    )


@api.post("/invites/{invite_id}/revoke")
async def revoke_operator_invite(invite_id: str, request: Request):
    assert_origin(request)
    require_admin(await current_user(request))
    return await revoke_invite(invite_id)


@api.post("/public/password-reset")
async def request_password_reset(request: Request):
    """Same reply whether or not the shop has this email. The attempt is counted either way."""
    assert_origin(request)
    payload = await request.json()
    email = str(payload.get("email") or "").strip().lower()
    shop_slug_value = str(payload.get("shop") or payload.get("shopSlug") or "").strip().lower()
    if "@" not in email or " " in email or len(email) > 200:
        raise AppError("Enter a valid email address.", 400)
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    attempt = {"email": email, "shop": shop_slug_value, "purpose": "password-reset"}
    user = None
    shop = None
    with unscoped():
        count = await db.auth_attempts.count_documents({**attempt, "created": {"$gt": cutoff}})
        if reset_is_limited(count):
            raise AppError("Too many reset requests. Try again later.", 429)
        await db.auth_attempts.insert_one({**attempt, "_id": new_id(), "created": now()})
        if shop_slug_value:
            shop = await db.shops.find_one({"slug": shop_slug_value})
        if shop:
            user = await db.users.find_one({"email": email, "shop_id": shop["_id"]})
    if (
        user
        and shop
        and user.get("role") != "superadmin"
        and shop_allows_sign_in(shop.get("status"))
    ):
        raw = await issue_password_reset(user["id"], email, shop["_id"])
        link = f"{public_base(request)}/login?reset={raw}"
        text = (
            f"A password reset was requested for {shop.get('name') or 'your shop'}.\n\n"
            "Open this link to choose a new password. It works once and expires in one hour.\n\n"
            f"{link}\n"
        )
        try:
            send_email(email, "Reset your Myraana password", text)
        except MailError:
            pass
    return {"ok": True, "message": reset_request_message(bool(user and shop))}


@api.post("/public/password-reset/confirm")
async def confirm_password_reset_request(request: Request):
    assert_origin(request)
    payload = await request.json()
    await confirm_password_reset(payload.get("token"), payload.get("password"))
    return {"ok": True, "message": "Password updated. Sign in with the new password."}


@api.post("/public/invites/accept")
async def accept_operator_invite(request: Request):
    assert_origin(request)
    user = await accept_invite(await request.json())
    cookie, safe_user = await issue_session(request, user)
    response = JSONResponse({"ok": True, "user": safe_user})
    response.set_cookie(**cookie)
    return response


async def _backfill_queues():
    """Stamp a queue on older jobs so the list can use the shop_queue_updated index."""
    for _ in range(6):
        missing = await db.jobs.find(
            {"queue": {"$exists": False}},
            {"messages": 0, "events": 0, "files": 0},
        ).to_list(400)
        if not missing:
            return
        for job in missing:
            ident = job.get("_id") or job.get("id")
            await db.jobs.update_one({"_id": ident}, {"$set": {"queue": queue_bucket(job)}})


@api.get("/jobs")
async def jobs(request: Request):
    require_user(await current_user(request))
    params = request.query_params
    group = params.get("group") or "needs-you"
    if group not in QUEUE_IDS:
        group = "needs-you"
    limit = clamp_limit(params.get("limit") or 50)
    await _backfill_queues()
    query, ordering = queue_page_query(group, params.get("cursor") or "")
    found = await db.jobs.find(
        query,
        {"messages": 0, "events": 0, "files": 0, "inspection": 0, "verification": 0, "productionChecklist": 0},
    ).sort(ordering).to_list(limit + 1)
    next_cursor = None
    if len(found) > limit:
        found = found[:limit]
        last = found[-1]
        next_cursor = encode_cursor(last.get("updated"), last.get("_id") or last.get("id"))
    slim = []
    for item in found:
        item.pop("_id", None)
        item["messages"] = []
        item["events"] = []
        item["statusLabel"] = status_label(item)
        slim.append(item)
    counts = {}
    for name in QUEUE_IDS:
        counts[name] = await db.jobs.count_documents(exclude_archived({"queue": name}))
    return {"group": group, "counts": counts, "jobs": slim, "nextCursor": next_cursor}


@api.post("/jobs")
async def create_job(request: Request):
    assert_origin(request)
    user = require_user(await current_user(request))
    payload = await request.json()
    if payload.get("confirmed") is not True:
        raise AppError("Confirm the order details before creating the job.", 400)
    settings_data = await shop_settings()
    preset_id = str(payload.get("product") or payload.get("presetId") or "business-card")
    recipe_doc = await db.recipes.find_one({"id": preset_id}, {"_id": 0}, sort=[("version", -1)])
    if preset_id == "business-card":
        payload = apply_card_defaults(payload, settings_data, recipe_doc)
    try:
        quantity = int(payload.get("quantity"))
    except (TypeError, ValueError) as error:
        raise AppError("Quantity is required.", 400) from error
    if not 1 <= quantity <= 1_000_000:
        raise AppError("Quantity is outside the supported range.", 400)
    due = valid_due(payload.get("due"))
    rules = artwork_rules_from_settings(settings_data)
    try:
        spec, recipe = resolve_spec({**payload, "product": preset_id}, rules, recipe_doc)
    except SpecError as error:
        raise AppError(error.message, 400) from error
    recipe = pin_job_recipe(recipe, recipe_doc)
    if is_london_card(recipe):
        spec["safe"] = recipe["safe"]
        spec["bleed"] = recipe["bleed"]
    job = {
        "id": new_id(),
        "customer": valid_text(payload.get("customer"), "Customer", 180),
        "product": spec["product"],
        "spec": spec,
        "quantity": quantity,
        "sides": spec["sides"],
        "stock": spec["stock"],
        "finish": spec["finish"],
        "due": due,
        "recipe": recipe,
        "sourceKind": None,
        "tasks": tasks(),
        "files": [],
        "messages": [],
        "events": [],
        "state": "active",
        "generation": 1,
        "revision": 0,
        "created": now(),
        "updated": now(),
    }
    update_task(job, 0, "Completed", f"Order details confirmed by {user['name']}.", user["name"])
    record_event(job, "Order created.", user["name"])
    job["queue"] = queue_bucket(job)
    await db.jobs.insert_one({"_id": job["id"], **job})
    await db.settings.update_one(
        {"kind": "settings"},
        {
            "$set": {
                "jobDefaults": {
                    "product": spec["product"],
                    "sizeId": spec["sizeId"],
                    "width": spec["width"],
                    "height": spec["height"],
                    "unit": spec["unit"],
                    "bleed": spec["bleed"],
                    "safe": spec["safe"],
                    "quantity": quantity,
                    "sides": spec["sides"],
                    "stock": spec["stock"],
                    "finish": spec["finish"],
                    "options": spec["options"],
                }
            }
        },
    )
    job["statusLabel"] = status_label(job)
    return job


@api.get("/jobs/{job_id}")
async def job_detail(job_id: str, request: Request):
    require_user(await current_user(request))
    job = await get_job(job_id)
    if not job:
        raise AppError("Job not found.", 404)
    job["statusLabel"] = status_label(job)
    job["timeline"] = timeline(job)
    return job


@api.post("/jobs/{job_id}/artwork")
async def upload_artwork(
    job_id: str,
    request: Request,
    file: UploadFile = File(...),
    acknowledged: str = Form(None),
):
    assert_origin(request)
    user = require_user(await current_user(request))
    job = await get_job(job_id)
    if not job or job["state"] != "active":
        raise AppError("This job is not available for artwork changes.", 409)
    if str(acknowledged).lower() not in {"true", "on", "1"}:
        raise AppError("Confirm this is the artwork for the job before upload.", 400)
    rules = artwork_rules_from_settings(await shop_settings())
    limit = int(rules["maxUploadBytes"])
    content = await file.read(limit + 1)
    if len(content) < 8 or len(content) > limit:
        raise AppError(f"Upload one file up to {max(1, limit // 1_000_000)} MB.", 400)
    try:
        kind = classify_upload(file.filename, content, rules["acceptedTypes"])
    except SpecError as error:
        raise AppError(error.message, 400) from error
    job["sourceKind"] = kind
    original = await create_file(job, "ORIGINAL", content, None, "Original upload preserved.", file.filename)
    reset_from(job, 2, "New artwork version: downstream checks and approvals invalidated.")
    job.pop("inspection", None)
    update_task(job, 1, "Completed", "Artwork saved. Checking it against this job.", user["name"], original["id"])
    await save_job(job)
    try:
        result = await process_with_lease(job["id"], job["generation"], AUTO_ACTOR)
        job = result["job"]
    except AppError:
        job = await get_job(job["id"]) or job
    job["statusLabel"] = status_label(job)
    return job


@api.post("/jobs/{job_id}/process")
async def process_job(job_id: str, request: Request):
    assert_origin(request)
    user = require_user(await current_user(request))
    payload = await request.json()
    result = await process_with_lease(job_id, payload.get("generation"), AUTO_ACTOR)
    return {"queued": result["queued"], "execution": result["execution"], "job": result["job"]}


@api.post("/jobs/{job_id}/control")
async def control_job(job_id: str, request: Request):
    assert_origin(request)
    user = require_user(await current_user(request))
    payload = await request.json()
    state = payload.get("state")
    if state not in {"active", "paused", "cancelled"}:
        raise AppError("Choose active, paused, or cancelled.", 400)
    job = await get_job(job_id)
    if not job:
        raise AppError("Job not found.", 404)
    if job.get("archived"):
        raise AppError("This job is archived.", 409)
    if job["state"] == "complete" or job["state"] == "cancelled":
        raise AppError("This job is closed.")
    job["state"] = state
    if state == "cancelled":
        for task in job["tasks"]:
            if task["status"] != "Completed":
                task["status"] = "Cancelled"
                task["result"] = "Job cancelled. Saved files and completed records were retained."
    record_event(job, f"Job {('resumed' if state == 'active' else state)}.", user["name"])
    await save_job(job)
    return job


@api.post("/jobs/{job_id}/archive")
async def archive_job(job_id: str, request: Request):
    """Hide a job from the default list. The record and its files stay in the shop."""
    assert_origin(request)
    user = require_admin(await current_user(request))
    job = await get_job(job_id)
    if not job:
        raise AppError("Job not found.", 404)
    if not job.get("archived"):
        job["archived"] = True
        job["archivedAt"] = now()
        record_event(job, "Job archived.", user["name"])
        await save_job(job)
    return public(job)


@api.post("/jobs/{job_id}/agents/evaluate")
async def evaluate_job_agents(job_id: str, request: Request):
    assert_origin(request)
    user = require_user(await current_user(request))
    if await request.body():
        raise AppError("Agent evaluation accepts no client-supplied state.", 400)
    return await evaluate_agents(job_id, user["name"])


@api.post("/jobs/{job_id}/action")
async def job_action(job_id: str, request: Request):
    assert_origin(request)
    user = require_user(await current_user(request))
    job = await get_job(job_id)
    if not job:
        raise AppError("Job not found.", 404)
    payload = await request.json()
    if job.get("archived"):
        raise AppError("This job is archived.", 409)
    if job["state"] != "active":
        raise AppError(f"This job is {job['state']}. Resume it before making changes.")
    if payload.get("generation") != job["generation"]:
        raise AppError("Job version changed. Refresh before continuing.")
    action = payload.get("action")
    auto_process = False
    print_ready = latest(job, "PRINT_READY")
    if action == "bleed":
        require_completed(job, 3)
        if job.get("inspection", {}).get("bleed") != "missing" or payload.get("decision") != "blank-border":
            raise AppError("Choose a corrected PDF or explicitly accept a blank border.")
        job["bleedDecision"] = "blank-border"
        job["bleedConfirmation"] = {
            "actor_id": user["id"],
            "actor_name": user["name"],
            "at": now(),
            "generation": job["generation"],
            "original_file_id": latest(job, "ORIGINAL")["id"],
        }
        update_task(
            job,
            3,
            "Completed",
            "Blank border accepted outside the trim. The artwork was not stretched. The print-ready file is next.",
            user["name"],
        )
        auto_process = True
    elif action == "confirm-bleed":
        require_completed(job, 3)
        if job["tasks"][3]["status"] == "Completed":
            raise AppError("Bleed handling is already confirmed.")
        if job.get("inspection", {}).get("bleed") == "missing" and not job.get("bleedDecision"):
            raise AppError("Choose a corrected PDF or explicitly accept a blank border.")
        if not payload.get("acknowledged"):
            raise AppError("Confirm bleed handling before preparation.")
        original = latest(job, "ORIGINAL") or {}
        job["bleedConfirmation"] = {
            "actor_id": user["id"],
            "actor_name": user["name"],
            "at": now(),
            "generation": job["generation"],
            "original_file_id": original.get("id"),
            "decision": job.get("bleedDecision") or "bleed-present",
        }
        update_task(
            job,
            3,
            "Waiting for operator",
            "Bleed confirmed. Building the print-ready file.",
            user["name"],
        )
        auto_process = True
    elif action == "approve":
        require_completed(job, 7)
        if not print_ready or payload.get("sha") != print_ready["sha"] or not payload.get("acknowledged"):
            raise AppError("Approval must match the currently verified production PDF.")
        job["approval"] = {
            "sha": print_ready["sha"],
            "fileId": print_ready["id"],
            "actor": user["name"],
            "at": now(),
            "generation": job["generation"],
        }
        update_task(job, 7, "Completed", "Proof approved for this exact PDF.", user["name"], print_ready["id"])
        update_task(job, 8, "Waiting for operator", "Choose a press for this job, or keep it as a proof.", user["name"])
        if is_london_card(job.get("recipe") or {}):
            output = (job.get("cardRoute") or {}).get("outputName") or print_ready.get("name")
            checklist = fresh_checklist(job["recipe"], output)
            for step in checklist:
                if step["id"] in {"start", "ask-file", "confirm-customer", "size", "canvas", "background", "safe", "export"}:
                    step["status"] = "done"
            job["productionChecklist"] = checklist
            job.pop("productionStop", None)
            job["connectorHook"] = connector_production_hook(job)
        settings_data = await shop_settings()
        chosen = known_finish(payload.get("finish")) or known_finish(job.get("finish"))
        if chosen:
            job["finish"] = chosen
            if isinstance(job.get("spec"), dict):
                job["spec"]["finish"] = chosen
        matched = auto_send_ready(job, settings_data)
        london = is_london_card(job.get("recipe") or {})
        if automatic_mode(settings_data):
            await queue_automatic_hold(job, user["name"])
        elif settings_data.get("fieryAutoSend") is True and london and fiery_target(settings_data) and not matched:
            job["productionStop"] = (
                "Fiery hold was not sent: the finish is not a cardstock on this shop's list. "
                "Use the checklist. Nothing was printed."
            )
            update_task(job, 8, "Needs attention", job["productionStop"], AUTO_ACTOR)
        elif matched:
            printer = fiery_target(settings_data)
            job["route"] = {
                "mode": "production",
                "settingsVersion": settings_data.get("version"),
                "printer": printer["name"],
                "auto": True,
            }
            update_task(
                job,
                8,
                "Completed",
                f"Production route selected: {printer['name']}. The file stays on HOLD.",
                AUTO_ACTOR,
            )
            update_task(
                job,
                9,
                "Running",
                "Sending the PRINT_READY file to the Fiery hold queue. It will not print.",
                AUTO_ACTOR,
            )
            job["fieryHold"] = {
                "status": "queued",
                "preset": "London BC",
                "stock": matched,
                "finish": job.get("finish"),
                "printer": printer["name"],
                "address": printer.get("address") or "",
                "at": now(),
                "held": False,
                "printed": False,
            }
            job.pop("productionStop", None)
        elif print_order(job):
            keep_production_route(job, settings_data)
            update_task(job, 8, "Completed", job["tasks"][8]["result"], AUTO_ACTOR)
            update_task(job, 9, "Waiting for operator", job["tasks"][9]["result"], AUTO_ACTOR)
    elif action == "route":
        require_completed(job, 8)
        settings_data = await shop_settings()
        mode = payload.get("mode") or "production"
        if mode not in {"production", "proof-only"}:
            raise AppError("Choose a production route or a proof-only route.", 400)
        if mode == "proof-only":
            job["route"] = {
                "mode": "proof-only",
                "settingsVersion": settings_data.get("version"),
                "printer": None,
            }
            update_task(
                job,
                8,
                "Completed",
                "Proof-only route selected. No press is assigned and nothing will print.",
                user["name"],
            )
            update_task(
                job,
                9,
                "Waiting for operator",
                "Proof only: nothing is sent to a press. Switch to a production route here if this job should print.",
                user["name"],
            )
        else:
            printer = str(settings_data.get("printer") or "").strip()
            verified = settings_data.get("verifiedPrinters") or []
            stock_ok = job["stock"] in (settings_data.get("stocks") or [])
            printer_ok = bool(printer) and (not verified or printer in verified)
            if print_order(job) and not (printer_ok and stock_ok):
                # A missing press must not turn a print order into a proof.
                # Earlier steps, including the approved proof, stay completed.
                keep_production_route(job, settings_data)
                update_task(job, 8, "Completed", job["tasks"][8]["result"], user["name"])
                update_task(job, 9, "Waiting for operator", job["tasks"][9]["result"], user["name"])
            elif not printer_ok or not stock_ok:
                problems = []
                if not printer:
                    problems.append("No printer is selected.")
                elif verified and printer not in verified:
                    problems.append(f"{printer} is not a verified press.")
                if not stock_ok:
                    problems.append(f"Stock “{job['stock']}” is not on this shop's press list.")
                raise AppError(
                    " ".join(problems)
                    + " Verify the printer on this step and add the stock, or choose Proof only. Nothing is sent to a press until you do.",
                    409,
                    code="machine-required",
                )
            else:
                job["route"] = {
                    "mode": "production",
                    "settingsVersion": settings_data["version"],
                    "printer": printer,
                    "manual": False,
                }
                update_task(job, 8, "Completed", f"Production route selected: {printer}. The approved proof was kept.", user["name"])
                if is_london_card(job.get("recipe") or {}) or print_order(job):
                    message = manual_press_message(job) if not fiery_target(settings_data) else (
                        "Send the PRINT_READY file to the Fiery HOLD queue. It stays on HOLD and will not print."
                    )
                    update_task(job, 9, "Waiting for operator", message, user["name"])
                else:
                    update_task(job, 9, "Waiting for operator", "Record the RIP job name. This does not print.", user["name"])
    elif action == "production-step":
        require_completed(job, 9)
        if job["tasks"][9]["status"] == "Completed":
            raise AppError("The Fiery checklist is already complete.")
        if not is_london_card(job.get("recipe") or {}):
            raise AppError("This job does not use the London business-card checklist.")
        if (job.get("route") or {}).get("mode") != "production":
            raise AppError(
                "This job is a proof only, so the Fiery checklist is closed. Switch to the production route first.",
                409,
            )
        if not job.get("productionChecklist"):
            output = (job.get("cardRoute") or {}).get("outputName") or (print_ready or {}).get("name")
            job["productionChecklist"] = fresh_checklist(job["recipe"], output)
        settings_data = await shop_settings()
        outcome = apply_production_event(
            job["productionChecklist"],
            payload,
            job["recipe"],
            settings_data.get("stocks") or [],
        )
        if not outcome["stop"]:
            stock_outcome = apply_known_stock(job, settings_data.get("stocks") or [])
            if stock_outcome:
                outcome = stock_outcome
                if not stock_outcome["stop"]:
                    record_event(
                        job,
                        f"Finish {job.get('finish')} was already known, so the Fiery stock step was answered.",
                        AUTO_ACTOR,
                    )
        if outcome["stop"]:
            job["productionStop"] = outcome["stop"]
            update_task(job, 9, "Needs attention", outcome["stop"], user["name"])
        else:
            job.pop("productionStop", None)
            if outcome["done"]:
                update_task(job, 9, "Completed", "Fiery checklist recorded. No print command sent.", user["name"])
                update_task(
                    job,
                    10,
                    "Waiting for operator",
                    "Check that the shop computer is connected. This does not print.",
                    user["name"],
                )
            else:
                pending = next(step for step in job["productionChecklist"] if step["status"] != "done")
                update_task(job, 9, "Waiting for operator", pending["title"], user["name"])
    elif action == "handoff":
        require_completed(job, 9)
        note = valid_text(payload.get("note"), "RIP handoff note", 1000, 5)
        update_task(job, 9, "Completed", f"RIP staging recorded: {note}. No print command sent.", user["name"])
        update_task(job, 10, "Waiting for operator", "Check that the shop computer is connected. This does not print.", user["name"])
    elif action == "readiness":
        require_completed(job, 10)
        ready = await readiness(job)
        host = ready.get("hostname") or "The shop computer"
        if ready.get("delivery") == "folder":
            note = "Connector is fresh and staging destination is writable."
        else:
            note = f"{host} is connected. The PRINT_READY file will be sent to Fiery HOLD. This does not print."
        update_task(job, 10, "Completed", note, user["name"])
        update_task(job, 11, "Waiting for approval", "Authorize this exact file for staging.", user["name"])
        job["readiness"] = {
            "checkedAt": now(),
            "destination": ready.get("destination") or "",
            "deviceId": ready.get("id") or "",
            "hostname": host,
            "lastSeen": ready.get("lastSeen") or "",
            "delivery": ready.get("delivery") or "",
        }
    elif action == "authorize":
        require_completed(job, 11)
        ready = await readiness(job)
        if not print_ready or payload.get("sha") != print_ready["sha"] or not payload.get("acknowledged"):
            raise AppError("Authorization must match the approved file and require confirmation.")
        if job.get("approval", {}).get("sha") != print_ready["sha"]:
            raise AppError("Approve this exact PDF before authorizing it.")
        job["authorization"] = {
            "sha": print_ready["sha"],
            "fileId": print_ready["id"],
            "generation": job["generation"],
            "actor": user["name"],
            "at": now(),
        }
        host = ready.get("hostname") or "The shop computer"
        if ready.get("delivery") == "fiery_hold":
            settings_data = await shop_settings()
            printer = fiery_target(settings_data) or {}
            preset = "London BC" if is_london_card(job.get("recipe") or {}) else (
                ((job.get("recipe") or {}).get("production") or {}).get("preset") or ""
            )
            job["fieryHold"] = {
                "status": "queued",
                "explicit": True,
                "deviceId": ready.get("id") or "",
                "preset": preset or "London BC",
                "stock": job.get("stock") or "",
                "finish": job.get("finish"),
                "printer": printer.get("name") or "",
                "address": printer.get("address") or "",
                "at": now(),
                "held": False,
                "printed": False,
            }
            note = f"Sending the PRINT_READY file to Fiery HOLD on {host}. It will not print."
        else:
            note = "Production authorization recorded; printing remains manual."
        update_task(job, 11, "Completed", note, user["name"])
        update_task(job, 12, "Waiting for operator", "Confirm only after physical sheets print.", user["name"])
    elif action in {"printed", "cut", "qc", "pack", "rework"}:
        if action != "rework" and (
            not print_ready or job.get("authorization", {}).get("sha") != print_ready["sha"]
        ):
            raise AppError("Production authorization is invalid for this exact file.")
        if action == "printed":
            require_completed(job, 12)
            if not payload.get("acknowledged"):
                raise AppError("Confirm only after the sheets physically print.")
            update_task(job, 12, "Completed", "Physical printing confirmed by operator.", user["name"])
            update_task(job, 13, "Waiting for operator", duplo_line(job) or "Cut and finish the cards.", user["name"])
        elif action == "cut":
            require_completed(job, 13)
            if not payload.get("acknowledged"):
                raise AppError("Operator confirmation is required.")
            update_task(job, 13, "Completed", "Cutting and finishing confirmed by operator.", user["name"])
            update_task(job, 14, "Waiting for operator", "Record final quality check.", user["name"])
        elif action == "qc":
            require_completed(job, 14)
            checks = payload.get("checks") or {}
            passed = all(checks.get(key) is True for key in ("quantity", "alignment", "appearance", "finishing"))
            if not passed:
                job["qc"] = {
                    "result": "FAIL",
                    "confirmed_by": user["name"],
                    "confirmed_at": now(),
                    "reason": "One or more operator quality checks failed.",
                }
                job.pop("authorization", None)
                update_task(job, 14, "Needs attention", "Quality check rejected; rework is required.", user["name"])
            else:
                job["qc"] = {
                    "result": "PASS",
                    "confirmed_by": user["name"],
                    "confirmed_at": now(),
                }
                update_task(job, 14, "Completed", "Final quality check passed.", user["name"])
                update_task(job, 15, "Waiting for operator", "Pack and label the order.", user["name"])
        elif action == "rework":
            if job["tasks"][14]["status"] != "Needs attention":
                raise AppError("Rework is available only after a rejected quality check.")
            job.pop("authorization", None)
            for index in range(11, 16):
                job["tasks"][index]["status"] = "Pending"
                job["tasks"][index]["result"] = "Rework requires new human confirmation."
            update_task(job, 11, "Waiting for approval", "Re-authorize the verified production PDF.", user["name"])
        else:
            require_completed(job, 15)
            if not payload.get("acknowledged") or payload.get("method") not in {"collection", "delivery"}:
                raise AppError("Confirm packing and choose collection or delivery.")
            update_task(job, 15, "Completed", "Packed and complete.", user["name"])
            job["state"] = "complete"
    elif action == "mark-sent":
        require_completed(job, 9)
        if (job.get("route") or {}).get("mode") != "production":
            raise AppError("Switch to the production route before marking the file sent.", 409)
        if not print_ready or job.get("approval", {}).get("sha") != print_ready["sha"]:
            raise AppError("Approve this exact PDF before sending it.")
        mark_sent_to_fiery(job)
        line = duplo_line(job)
        update_task(job, 9, job["tasks"][9]["status"], job["tasks"][9]["result"], user["name"])
        update_task(job, 10, job["tasks"][10]["status"], job["tasks"][10]["result"], user["name"])
        update_task(job, 11, job["tasks"][11]["status"], job["tasks"][11]["result"], user["name"])
        update_task(job, 12, job["tasks"][12]["status"], job["tasks"][12]["result"], user["name"])
        if line:
            update_task(job, 13, job["tasks"][13]["status"], line, user["name"])
        job["authorization"] = {
            "sha": print_ready["sha"],
            "fileId": print_ready["id"],
            "generation": job["generation"],
            "actor": user["name"],
            "at": now(),
            "manual": True,
        }
        job["manualFiery"] = {"at": now(), "actor": user["name"], "sha": print_ready["sha"]}
    elif action == "run-job":
        settings_data = await shop_settings()
        if not automatic_mode(settings_data):
            raise AppError("Automatic mode is off. Use the steps on this job.", 409)
        if not latest(job, "ORIGINAL"):
            raise AppError("Upload the artwork, then run the job.", 409)
        if job["tasks"][6]["status"] != "Completed":
            try:
                result = await process_with_lease(job["id"], job["generation"], AUTO_ACTOR)
                job = result["job"]
            except AppError:
                job = await get_job(job_id) or job
        if job["tasks"][6]["status"] == "Completed":
            ready_file = latest(job, "PRINT_READY")
            approved = bool(ready_file) and (job.get("approval") or {}).get("sha") == ready_file.get("sha")
            if approved:
                await queue_automatic_hold(job, user["name"])
            else:
                await note_prepared_route(job)
    elif action == "send-hold":
        require_completed(job, 9)
        if (job.get("route") or {}).get("mode") != "production":
            raise AppError("Switch to the production route before sending to Fiery.", 409)
        if not print_ready or job.get("approval", {}).get("sha") != print_ready["sha"]:
            raise AppError("Approve this exact PDF before sending it.")
        settings_data = await shop_settings()
        printer = fiery_target(settings_data)
        if not printer:
            raise AppError(
                "No Fiery is paired yet. Download the PRINT_READY file and send it yourself, or pair the connector. Nothing was printed.",
                409,
            )
        try:
            ready = await readiness(job)
        except AppError as error:
            raise AppError(f"{error.message} Nothing was printed.", error.status) from error
        if ready.get("delivery") != "fiery_hold":
            raise AppError("The shop computer cannot place this file on Fiery HOLD. Nothing was printed.", 409)
        try:
            stage_fiery_hold(job, ready, printer, user["name"], print_ready, now())
        except ValueError as error:
            raise AppError(str(error), 409) from error
        record_event(job, "PRINT_READY is queued on the Fiery HOLD queue. It was not printed.", user["name"])
    else:
        raise AppError("This protected action is not available in the current workflow.")
    await save_job(job)
    if auto_process:
        try:
            result = await process_with_lease(job["id"], job["generation"], AUTO_ACTOR)
            job = result["job"]
        except AppError:
            job = await get_job(job_id) or job
    job["statusLabel"] = status_label(job)
    job["timeline"] = timeline(job)
    return job


@api.post("/jobs/{job_id}/proof-link")
async def job_proof_link(job_id: str, request: Request):
    assert_origin(request)
    user = require_user(await current_user(request))
    job = await get_job(job_id)
    if not job:
        raise AppError("Job not found.", 404)
    payload = await request.json()
    result = await create_proof_link(job, user, public_base(request))
    email = str((payload or {}).get("email") or "").strip()
    if email:
        try:
            sent = send_email(
                email,
                "Approve your proof",
                f"Approve this proof: {result['url']}\nApproving does not print the job.",
            )
            result["emailed"] = bool(sent.get("delivered"))
        except Exception:
            result["emailed"] = False
    await save_job(job)
    return result


@api.get("/proofs/{token}")
async def public_proof(token: str):
    return await proof_for_token(token)


@api.post("/proofs/{token}/approve")
async def public_proof_approve(token: str, request: Request):
    assert_origin(request)
    return await approve_proof_token(token)


@api.get("/files/{job_id}/{file_id}")
async def download_file(job_id: str, file_id: str, request: Request):
    require_user(await current_user(request))
    job = await get_job(job_id)
    record = next((item for item in (job or {}).get("files", []) if item["id"] == file_id), None)
    if not record:
        raise AppError("File not found.", 404)
    content = await file_bytes(job, record)
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
    if request.query_params.get("download") is not None:
        headers["Content-Disposition"] = f'attachment; filename="{record["name"]}"'
    return Response(content=content, media_type="application/pdf", headers=headers)


@api.get("/files/{job_id}/{file_id}/preview/{page}")
async def preview_file(job_id: str, file_id: str, page: int, request: Request):
    require_user(await current_user(request))
    job = await get_job(job_id)
    record = next((item for item in (job or {}).get("files", []) if item["id"] == file_id), None)
    if not record:
        raise AppError("File not found.", 404)
    return Response(await _render(job, record, page), media_type="image/png")


async def _render(job, record, page):
    return render_page(await file_bytes(job, record), page - 1)


@api.post("/jobs/{job_id}/chat")
async def chat(job_id: str, request: Request):
    assert_origin(request)
    user = require_user(await current_user(request))
    job = await get_job(job_id)
    if not job:
        raise AppError("Job not found.", 404)
    message = valid_text((await request.json()).get("message"), "Message", 3000)
    async def stream():
        async for item in conversation_events(job, user, message):
            yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@api.post("/connector")
async def connector_heartbeat(request: Request):
    secret = os.environ.get("CONNECTOR_SECRET")
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not secret or not hmac.compare_digest(supplied, secret):
        raise AppError("Connector authentication failed.", 401)
    shop_id = bound_shop(PRINT2GO_SHOP_ID, request.headers.get("x-shop-id"))
    with shop_scope(shop_id):
        payload = await request.json()
        nonce = valid_text(payload.get("nonce"), "Connector nonce", 100)
        try:
            uuid.UUID(nonce)
            timestamp = int(payload.get("timestamp"))
        except (TypeError, ValueError, AttributeError) as error:
            raise AppError("Connector nonce or timestamp is invalid.", 400) from error
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if abs(now_ms - timestamp) > 60_000:
            raise AppError("Connector clock differs by more than one minute.", 409)
        try:
            await db.connector_nonces.insert_one({"nonce": nonce, "created": datetime.now(timezone.utc)})
        except Exception as error:
            raise AppError("Connector replay rejected.", 409) from error
        if not payload.get("writable") or "pdf-hot-folder" not in payload.get("capabilities", []):
            raise AppError("Connector must report a writable PDF staging capability.", 409)
        agent = {
            "destination": valid_text(payload.get("destination"), "Destination", 500),
            "writable": True,
            "capabilities": ["pdf-hot-folder"],
            "lastSeen": now(),
        }
        await save_connector_agent(agent)
        for handoff in payload.get("handoffs", []):
            job_id = str(handoff.get("jobId") or "")
            job = await get_job(job_id)
            file = latest(job or {}, "PRINT_READY")
            authorization = (job or {}).get("authorization")
            matching = (
                job
                and file
                and authorization
                and handoff.get("sha") == file["sha"]
                and handoff.get("fileId") == file["id"]
                and handoff.get("generation") == job["generation"]
                and authorization.get("generation") == job["generation"]
            )
            if not matching:
                raise AppError("Connector handoff does not match an authorized file.", 409)
            if not any(item["stage"] == "PRODUCTION_OUTPUT" and item.get("parent") == file["id"] for item in job["files"]):
                staged = await create_file(
                    job,
                    "PRODUCTION_OUTPUT",
                    await file_bytes(job, file),
                    file,
                    "Connector confirmed exact checksum handoff; this is not proof of printing.",
                )
                record_event(
                    job,
                    f"Connector confirmed production file handoff for checksum {staged['sha'][:12]}. "
                    "Physical printing still needs human confirmation.",
                )
                await save_job(job)
        candidates = await db.jobs.find(exclude_archived({"state": "active"}), {"_id": 0}).to_list(100)
        authorized = []
        for job in candidates:
            file = latest(job, "PRINT_READY")
            authorization = job.get("authorization")
            if file and authorization and authorization["sha"] == file["sha"]:
                entry = {"id": job["id"], "generation": job["generation"], "file": file}
                hook = connector_production_hook(job)
                if hook:
                    entry["production"] = hook
                authorized.append(entry)
        return {"jobs": authorized}


@api.get("/connector/file/{job_id}")
async def connector_file(job_id: str, request: Request):
    secret = os.environ.get("CONNECTOR_SECRET")
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not secret or not hmac.compare_digest(supplied, secret):
        raise AppError("Connector authentication failed.", 401)
    shop_id = bound_shop(PRINT2GO_SHOP_ID, request.headers.get("x-shop-id"))
    with shop_scope(shop_id):
        job = await get_job(job_id)
        record = latest(job or {}, "PRINT_READY")
        if not job or not record or job.get("authorization", {}).get("sha") != record["sha"]:
            raise AppError("This file is not authorized.", 403)
        content = await file_bytes(job, record)
    return Response(content, media_type="application/pdf")


app.include_router(api)
app.add_middleware(ShopContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, error: AppError):
    return error_response(error)


@app.exception_handler(TenantScopeError)
async def tenant_scope_handler(_: Request, error: TenantScopeError):
    return JSONResponse({"error": error.message, "code": error.code}, status_code=error.status)