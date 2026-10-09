import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, File, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.cors import CORSMiddleware


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from p2g.ai import configured as ai_configured, conversation_events
from p2g.agent_bridge import evaluate_agents
from p2g.build_metadata import read_build_metadata
from p2g.connector_pairing import (
    approve_pairing,
    claim_pairing,
    create_pairing,
    heartbeat as paired_heartbeat,
    pairings,
    pairing_status,
)
from p2g.core import AppError, db, new_id, now
from p2g.pdfcheck import render_page
from p2g.workflow import (
    DEFAULT_RECIPE,
    create_file,
    create_session,
    current_user,
    ensure_collections,
    file_bytes,
    get_job,
    latest,
    password_hash,
    password_matches,
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
    session_response,
    tasks,
    update_task,
)


app = FastAPI(title="Print2Go Production Studio")
api = APIRouter(prefix="/api")


def error_response(error):
    if isinstance(error, AppError):
        return JSONResponse({"error": error.message}, status_code=error.status)
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


async def shop_settings():
    settings = await db.settings.find_one({"_id": "shop"}, {"_id": 0})
    if settings:
        return settings
    return {
        "printer": "",
        "stocks": ["14pt matte", "16pt soft touch"],
        "sides": [1, 2],
        "instructions": "Operator-assisted RIP handoff. No automatic printing.",
        "version": 1,
    }


@app.on_event("startup")
async def startup():
    await ensure_collections()
    await recover_interrupted_executions()


@api.get("/")
async def health():
    return {"name": "Print2Go Production Studio", "status": "ready"}


@api.get("/build-info")
async def build_info():
    return read_build_metadata()


@api.get("/auth")
async def auth_status(request: Request):
    user = await current_user(request)
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
    user = {"id": new_id(), "name": name, "email": email, "role": "admin"}
    try:
        await db.users.insert_one({**user, "password": password_hash(password), "created": now()})
    except Exception as error:
        await db.bootstrap.update_one({"_id": "first-run"}, {"$set": {"configured": False}})
        raise AppError("Administrator setup could not be saved. Retry safely.") from error
    token, cookie, safe_user = session_response(request, user)
    await create_session(token, user["id"])
    response = JSONResponse({"user": safe_user})
    response.set_cookie(**cookie)
    return response


@api.post("/auth/login")
async def auth_login(request: Request):
    assert_origin(request)
    payload = await request.json()
    email = valid_text(payload.get("email"), "Email", 200).lower()
    password = str(payload.get("password") or "")
    user = await db.users.find_one({"email": email})
    if not user or not password_matches(password, user["password"]):
        raise AppError("Email or password is incorrect.", 401)
    token, cookie, safe_user = session_response(request, user)
    await create_session(token, user["id"])
    response = JSONResponse({"user": safe_user})
    response.set_cookie(**cookie)
    return response


@api.post("/auth/logout")
async def auth_logout(request: Request):
    assert_origin(request)
    raw = request.cookies.get("p2g_session")
    if raw:
        from p2g.core import sha256

        await db.sessions.delete_one({"token_hash": sha256(raw)})
    response = JSONResponse({"ok": True})
    response.delete_cookie("p2g_session", path="/")
    return response


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
    fields = {}
    for key, low, high in (
        ("width", 0.5, 20),
        ("height", 0.5, 20),
        ("bleed", 0, 0.5),
        ("safe", 0.05, 0.5),
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
    latest_recipe = await db.recipes.find_one({}, sort=[("version", -1)])
    recipe = {
        "id": "business-card",
        "version": latest_recipe["version"] + 1,
        "name": name,
        **fields,
        "minDpi": int(fields["minDpi"]),
        "cutInstructions": valid_text(payload.get("cutInstructions"), "Instructions", 2000),
        "created": now(),
    }
    await db.recipes.insert_one(recipe.copy())
    return public(recipe)


@api.get("/settings")
async def settings(request: Request):
    require_user(await current_user(request))
    settings_data = await shop_settings()
    agent = await db.connector_state.find_one({"_id": "agent"}, {"_id": 0})
    return {
        **settings_data,
        "aiConnected": ai_configured(),
        "connectorConfigured": bool(os.environ.get("CONNECTOR_SECRET")),
        "agent": agent,
        "connected": bool(agent and agent.get("writable")),
        "pairings": await pairings(),
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


@api.post("/connector-devices/heartbeat")
async def paired_connector_heartbeat(request: Request):
    return await paired_heartbeat(request, await request.json())


@api.post("/settings")
async def update_settings(request: Request):
    assert_origin(request)
    require_admin(await current_user(request))
    payload = await request.json()
    current = await shop_settings()
    stocks = [valid_text(item, "Stock", 100) for item in payload.get("stocks", [])]
    if len(stocks) > 30:
        raise AppError("Use at most 30 supported stocks.", 400)
    data = {
        "printer": str(payload.get("printer") or "").strip()[:120],
        "stocks": stocks,
        "sides": [side for side in payload.get("sides", [1, 2]) if side in [1, 2]],
        "instructions": str(payload.get("instructions") or "")[:2000],
        "version": current["version"] + 1,
        "updated": now(),
    }
    changed = any(
        current.get(key) != data.get(key)
        for key in ("printer", "stocks", "sides", "instructions")
    )
    await db.settings.replace_one({"_id": "shop"}, {"_id": "shop", **data}, upsert=True)
    if changed:
        affected = await db.jobs.find(
            {"state": "active", "tasks.12.status": {"$ne": "Completed"}},
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


@api.get("/users")
async def users(request: Request):
    require_admin(await current_user(request))
    return await db.users.find({}, {"_id": 0, "password": 0}).to_list(100)


@api.post("/users")
async def create_user(request: Request):
    assert_origin(request)
    require_admin(await current_user(request))
    payload = await request.json()
    role = payload.get("role")
    if role not in {"admin", "operator"}:
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
    try:
        await db.users.insert_one(user)
    except Exception as error:
        raise AppError("That operator email already exists.", 409) from error
    return {"ok": True}


@api.get("/jobs")
async def jobs(request: Request):
    require_user(await current_user(request))
    found = await db.jobs.find({}, {"_id": 0}).sort("created", -1).to_list(500)
    for item in found:
        item["messages"] = []
        item["events"] = []
    return found


@api.post("/jobs")
async def create_job(request: Request):
    assert_origin(request)
    user = require_user(await current_user(request))
    payload = await request.json()
    try:
        quantity = int(payload.get("quantity"))
        sides = int(payload.get("sides"))
    except (TypeError, ValueError) as error:
        raise AppError("Quantity and sides are required.", 400) from error
    if not 1 <= quantity <= 1_000_000 or sides not in {1, 2}:
        raise AppError("Quantity or sides are outside the supported range.", 400)
    recipe = await db.recipes.find_one({}, {"_id": 0}, sort=[("version", -1)])
    job = {
        "id": new_id(),
        "customer": valid_text(payload.get("customer"), "Customer", 180),
        "quantity": quantity,
        "sides": sides,
        "stock": valid_text(payload.get("stock"), "Stock", 100),
        "finish": valid_text(payload.get("finish"), "Finish", 100),
        "due": valid_text(payload.get("due"), "Due date", 10),
        "recipe": recipe or {**DEFAULT_RECIPE, "created": now()},
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
    record_event(job, "Order created.", user["name"])
    await db.jobs.insert_one({"_id": job["id"], **job})
    return job


@api.get("/jobs/{job_id}")
async def job_detail(job_id: str, request: Request):
    require_user(await current_user(request))
    job = await get_job(job_id)
    if not job:
        raise AppError("Job not found.", 404)
    return job


@api.post("/jobs/{job_id}/artwork")
async def upload_artwork(job_id: str, request: Request, file: UploadFile = File(...)):
    assert_origin(request)
    user = require_user(await current_user(request))
    job = await get_job(job_id)
    if not job or job["state"] != "active":
        raise AppError("This job is not available for artwork changes.", 409)
    content = await file.read(4 * 1024 * 1024 + 1)
    if len(content) < 5 or len(content) > 4 * 1024 * 1024 or not content.startswith(b"%PDF-"):
        raise AppError("Upload one PDF of up to 4 MB.", 400)
    original = await create_file(job, "ORIGINAL", content, None, "Original upload preserved.", file.filename)
    reset_from(job, 2, "New artwork version: downstream checks and approvals invalidated.")
    job.pop("inspection", None)
    update_task(job, 1, "Completed", "Original PDF saved. Ready to check artwork.", user["name"], original["id"])
    await save_job(job)
    return job


@api.post("/jobs/{job_id}/process")
async def process_job(job_id: str, request: Request):
    assert_origin(request)
    user = require_user(await current_user(request))
    payload = await request.json()
    result = await process_with_lease(job_id, payload.get("generation"), user["name"])
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
    if job["state"] != "active":
        raise AppError(f"This job is {job['state']}. Resume it before making changes.")
    if payload.get("generation") != job["generation"]:
        raise AppError("Job version changed. Refresh before continuing.")
    action = payload.get("action")
    print_ready = latest(job, "PRINT_READY")
    if action == "bleed":
        require_completed(job, 3)
        if job.get("inspection", {}).get("bleed") != "missing" or payload.get("decision") != "blank-border":
            raise AppError("Choose a corrected PDF or explicitly accept a blank border.")
        job["bleedDecision"] = "blank-border"
        update_task(job, 3, "Completed", "Blank border outside trim accepted; content is not stretched.", user["name"])
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
        update_task(job, 8, "Waiting for operator", "Choose a compatible production route.", user["name"])
    elif action == "route":
        require_completed(job, 8)
        settings_data = await shop_settings()
        if not settings_data["printer"] or job["stock"] not in settings_data["stocks"]:
            raise AppError("No compatible route. Configure the printer and selected stock first.")
        job["route"] = {"settingsVersion": settings_data["version"], "printer": settings_data["printer"]}
        update_task(job, 8, "Completed", "Production route selected.", user["name"])
        update_task(job, 9, "Waiting for operator", "Stage in RIP without printing.", user["name"])
    elif action == "handoff":
        require_completed(job, 9)
        note = valid_text(payload.get("note"), "RIP handoff note", 1000, 5)
        update_task(job, 9, "Completed", f"RIP staging recorded: {note}. No print command sent.", user["name"])
        update_task(job, 10, "Waiting for operator", "Verify shop connector readiness.", user["name"])
    elif action == "readiness":
        require_completed(job, 10)
        agent = await readiness(job)
        update_task(job, 10, "Completed", "Connector is fresh and staging destination is writable.", user["name"])
        update_task(job, 11, "Waiting for approval", "Authorize this exact file for staging.", user["name"])
        job["readiness"] = {"checkedAt": now(), "destination": agent["destination"]}
    elif action == "authorize":
        require_completed(job, 11)
        await readiness(job)
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
        update_task(job, 11, "Completed", "Production authorization recorded; printing remains manual.", user["name"])
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
            update_task(job, 13, "Waiting for operator", "Cut and finish the cards.", user["name"])
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
    else:
        raise AppError("This protected action is not available in the current workflow.")
    await save_job(job)
    return job


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
    await db.connector_state.replace_one({"_id": "agent"}, {"_id": "agent", **agent}, upsert=True)
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
    candidates = await db.jobs.find({"state": "active"}, {"_id": 0}).to_list(100)
    authorized = []
    for job in candidates:
        file = latest(job, "PRINT_READY")
        authorization = job.get("authorization")
        if file and authorization and authorization["sha"] == file["sha"]:
            authorized.append({"id": job["id"], "generation": job["generation"], "file": file})
    return {"jobs": authorized}


@api.get("/connector/file/{job_id}")
async def connector_file(job_id: str, request: Request):
    secret = os.environ.get("CONNECTOR_SECRET")
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not secret or not hmac.compare_digest(supplied, secret):
        raise AppError("Connector authentication failed.", 401)
    job = await get_job(job_id)
    record = latest(job or {}, "PRINT_READY")
    if not job or not record or job.get("authorization", {}).get("sha") != record["sha"]:
        raise AppError("This file is not authorized.", 403)
    return Response(await file_bytes(job, record), media_type="application/pdf")


app.include_router(api)
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