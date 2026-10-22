import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from p2g.core import AppError, db, lock, new_id, now, unlock
from p2g.pdfcheck import PdfError, inspect, make_print_ready, prepare, render_page, verify
from p2g.present import status_label
from p2g.account_access import SUSPENDED_MESSAGE, shop_allows_sign_in
from p2g.membership import save_session, user_for_session
from p2g.tenancy import (
    PRINT2GO_SHOP_ID,
    current_shop_id,
    download_allowed,
    is_shop_admin,
    is_superadmin,
    migrate_tenants,
    shop_scope,
    starter_recipes,
    unscoped,
)
from p2g.uploads import SpecError, prepare_artwork


TASK_TITLES = [
    "Capture order",
    "Receive artwork",
    "Check artwork",
    "Decide bleed handling",
    "Prepare artwork",
    "Generate PRINT_READY",
    "Verify PRINT_READY",
    "Review and approve proof",
    "Choose production route",
    "Prepare imposition and RIP handoff",
    "Verify shop readiness",
    "Authorize production",
    "Print",
    "Cut and finish",
    "Final quality check",
    "Pack and complete",
]

DEFAULT_RECIPE = {
    "id": "business-card",
    "version": 1,
    "name": "Business card",
    "width": 3.5,
    "height": 2.0,
    "bleed": 0.125,
    "safe": 0.25,
    "minDpi": 300,
    "cutInstructions": "Cut to 3.5 × 2 inches using the verified trim box.",
}


def tasks():
    stamp = now()
    return [
        {
            "id": f"t{index + 1}",
            "title": title,
            "status": "Completed" if index == 0 else "Pending",
            "result": "Order details saved." if index == 0 else "Not started.",
            "party": "Operator" if index in {0, 1, 3, 7, 8, 9, 11, 12, 13, 14, 15} else "Application",
            "next": "",
            "updated": stamp,
            "executions": [],
            "evidence": [],
        }
        for index, title in enumerate(TASK_TITLES)
    ]


def record_event(job, text, actor="Application"):
    job.setdefault("events", []).append(
        {"id": new_id(), "text": text, "actor": actor, "at": now()}
    )


def update_task(
    job,
    index,
    status,
    result,
    actor="Application",
    evidence=None,
    execution=None,
    error=None,
    recovery=None,
):
    item = job["tasks"][index]
    item["status"] = status
    item["result"] = result
    item["updated"] = now()
    if status == "Completed":
        item.setdefault("started", now())
        item["finished"] = now()
    if evidence and evidence not in item["evidence"]:
        item["evidence"].append(evidence)
    if execution and execution not in item["executions"]:
        item["executions"].append(execution)
    if error:
        item["error"] = error
    if recovery:
        item["recovery"] = recovery
    item["next"] = {
        "Needs attention": "Review the details, then choose the stated operator decision.",
        "Waiting for approval": "Review the actual proof and approve this exact file.",
        "Waiting for operator": "Complete the stated operator action when it is true.",
        "Failed": "Retry from saved evidence or upload corrected artwork.",
        "Blocked": "Upload corrected artwork or resolve the stated block.",
    }.get(status, "")
    record_event(job, result, actor)


def latest(job, stage):
    return next((item for item in reversed(job.get("files", [])) if item["stage"] == stage), None)


def require_completed(job, through):
    for item in job["tasks"][:through]:
        if item["status"] != "Completed":
            raise AppError(f"Finish “{item['title']}” first.")


def reset_from(job, index, reason):
    job["generation"] += 1
    for item in job["tasks"][index:]:
        item.update(
            {
                "status": "Pending",
                "result": reason,
                "next": "",
                "finished": None,
                "executions": [],
                "evidence": [],
            }
        )
    if index <= 7:
        job.pop("approval", None)
    job.pop("authorization", None)
    if index <= 8:
        job.pop("route", None)
        job.pop("readiness", None)
    if index <= 6:
        job.pop("verification", None)
    if index <= 3:
        job.pop("bleedDecision", None)
        job.pop("bleedConfirmation", None)
    record_event(job, reason)


def public(doc):
    if not doc:
        return None
    copy = {key: value for key, value in doc.items() if key != "_id"}
    if "tasks" in copy and "state" in copy:
        copy["statusLabel"] = status_label(copy)
    return copy


async def ensure_collections():
    with unscoped():
        await migrate_tenants(db)
        await db.users.create_index([("shop_id", 1), ("email", 1)], unique=True, name="shop_email")
        await db.users.create_index("shop_id")
        await db.sessions.create_index("expires")
        await db.sessions.create_index("shop_id")
        await db.jobs.create_index("shop_id")
        await db.shops.create_index("slug", unique=True)
        await db.connector_nonces.create_index("created", expireAfterSeconds=300)
        await db.connector_nonces.create_index("nonce", unique=True)
        await db.executions.create_index([("job_id", 1), ("status", 1)])
        await db.executions.create_index("lease_until")
        await db.cost_profiles.create_index(
            [("shop_id", 1), ("id", 1)], unique=True, name="shop_cost"
        )
        await db.leads.create_index("email")
        await db.leads.create_index("created")
        await db.invites.create_index("token_hash")
        await db.password_resets.create_index("token_hash")
        await db.auth_attempts.create_index("created")
        await db.bootstrap.update_one(
            {"_id": "first-run"},
            {"$setOnInsert": {"configured": False, "created": now()}},
            upsert=True,
        )
    with shop_scope(PRINT2GO_SHOP_ID):
        for recipe in starter_recipes():
            if recipe["id"] == "business-card":
                exists = await db.recipes.find_one({"id": "business-card", "version": 1})
            else:
                exists = await db.recipes.find_one({"id": recipe["id"]})
            if not exists:
                await db.recipes.insert_one({**recipe, "created": now()})


def password_hash(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def password_matches(password, encoded):
    return bcrypt.checkpw(password.encode(), encoded.encode())


async def current_user(request: Request):
    return await user_for_session(db, request.cookies.get("p2g_session"), now())


def require_user(user):
    if not user:
        raise AppError("Sign in to your shop.", 401)
    if is_superadmin(user) or not user.get("shop_id"):
        raise AppError(
            "Platform administrators do not open a shop workspace from this page.",
            403,
        )
    if not shop_allows_sign_in(user.get("shop_status")):
        raise AppError(SUSPENDED_MESSAGE, 403)
    return user


def require_admin(user):
    require_user(user)
    if not is_shop_admin(user):
        raise AppError("Only an administrator can change shop configuration.", 403)
    return user


def session_response(request, user):
    token = secrets.token_urlsafe(48)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    cookie = {
        "key": "p2g_session",
        "value": token,
        "httponly": True,
        "samesite": "strict",
        "secure": secure,
        "max_age": 43200,
        "path": "/",
    }
    safe = {key: user[key] for key in ("id", "name", "email", "role")}
    if user.get("shop_id"):
        safe["shopId"] = user["shop_id"]
    return token, cookie, safe


async def create_session(token, user_id, shop_id=None):
    expiry = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    await save_session(
        db,
        token=token,
        user_id=user_id,
        shop_id=shop_id,
        session_id=new_id(),
        expires=expiry,
    )


async def issue_session(request, user):
    """Set the same cookie login uses. Invite acceptance goes through here too."""
    if not user or user.get("active") is False:
        raise AppError("This account has been removed from the shop.", 403)
    token, cookie, safe_user = session_response(request, user)
    await create_session(token, user["id"], user.get("shop_id"))
    return cookie, safe_user


async def create_file(job, stage, content, parent, method, name=None):
    file_id = new_id()
    meta = {
        "id": file_id,
        "stage": stage,
        "name": name or f"{job['id']}-{stage}.pdf",
        "bytes": len(content),
        "sha": hashlib.sha256(content).hexdigest(),
        "created": now(),
        "parent": parent["id"] if parent else None,
        "method": method,
    }
    shop_id = job.get("shop_id") or current_shop_id()
    if shop_id and not job.get("shop_id"):
        job["shop_id"] = shop_id
    bucket = AsyncIOMotorGridFSBucket(db.raw, bucket_name="pdf_files")
    stream = bucket.open_upload_stream_with_id(
        file_id,
        meta["name"],
        metadata={"job_id": job["id"], "sha": meta["sha"], "stage": stage, "shop_id": shop_id},
    )
    await stream.write(content)
    await stream.close()
    job.setdefault("files", []).append(meta)
    return meta


async def file_bytes(job, record):
    stored = await db.raw["pdf_files.files"].find_one({"_id": record["id"]})
    metadata_shop = ((stored or {}).get("metadata") or {}).get("shop_id")
    if not download_allowed(current_shop_id(), (job or {}).get("shop_id"), metadata_shop):
        raise AppError("File not found.", 404)
    bucket = AsyncIOMotorGridFSBucket(db.raw, bucket_name="pdf_files")
    try:
        stream = await bucket.open_download_stream(record["id"])
        content = await stream.read()
    except Exception as error:
        raise AppError("File not found.", 404) from error
    if hashlib.sha256(content).hexdigest() != record["sha"]:
        raise AppError("Saved file identity does not match its recorded checksum.", 409)
    return content


async def save_job(job, token=None):
    job["updated"] = now()
    data = {key: value for key, value in job.items() if key not in {"revision", "_id"}}
    query = {"_id": job["id"], "revision": job["revision"]}
    if token:
        query["lock"] = token
    result = await db.jobs.replace_one(
        query,
        {"_id": job["id"], **data, "revision": job["revision"] + 1},
    )
    if not result.matched_count:
        raise AppError("This job changed in another session. Refresh and retry.")
    job["revision"] += 1
    return job


async def get_job(job_id):
    return public(await db.jobs.find_one({"_id": job_id}))


async def run_pdf_workflow(job, actor, execution=None, token=None):
    if job.get("state") != "active":
        raise AppError(f"This job is {job.get('state')}. Resume it before processing.")

    async def persist():
        await save_job(job, token)

    original = latest(job, "ORIGINAL")
    if not original:
        raise AppError("Upload artwork first.")
    content = await file_bytes(job, original)
    try:
        try:
            content = prepare_artwork(
                content,
                job.get("sourceKind") or "pdf",
                (job.get("recipe") or {}).get("outputDpi") or 300,
            )
        except SpecError as error:
            update_task(job, 2, "Blocked", str(error), actor, original["id"])
            await persist()
            return job
        if job["tasks"][2]["status"] != "Completed":
            update_task(job, 2, "Running", "Checking artwork against the pinned recipe.", actor, execution=execution)
            await persist()
            report = inspect(content, job["recipe"], job["sides"])
            job["inspection"] = report
            if report["errors"]:
                update_task(job, 2, "Blocked", " ".join(report["errors"]), actor, original["id"])
                await persist()
                return job
            update_task(
                job,
                2,
                "Completed",
                f"Checked {job['sides']} page(s). {len(report['warnings'])} review note(s).",
                actor,
                original["id"],
            )
        if job["tasks"][3]["status"] != "Completed":
            update_task(job, 3, "Running", "Reviewing bleed handling.", actor, execution=execution)
            await persist()
            if job["inspection"]["bleed"] == "missing" and not job.get("bleedDecision"):
                update_task(
                    job,
                    3,
                    "Needs attention",
                    "This file is the finished size only, with no bleed. "
                    "Upload a PDF that includes the bleed, or accept a blank border. "
                    "The artwork will not be stretched.",
                    actor,
                    original["id"],
                )
                await persist()
                return job
            if not job.get("bleedConfirmation"):
                update_task(
                    job,
                    3,
                    "Waiting for operator",
                    "Confirm bleed handling before the print-ready file is prepared.",
                    actor,
                    original["id"],
                )
                await persist()
                return job
            update_task(job, 3, "Completed", "Bleed handling confirmed.", actor, original["id"])
        if job["tasks"][4]["status"] != "Completed":
            update_task(job, 4, "Running", "Preparing the protected working copy.", actor, execution=execution)
            await persist()
            prepared = prepare(content, job["recipe"], job.get("bleedDecision") == "blank-border")
            working = await create_file(
                job,
                "WORKING_COPY",
                prepared,
                original,
                "Preserve artwork; set recipe page boxes.",
            )
            update_task(job, 4, "Completed", "Working copy saved. Original artwork preserved.", actor, working["id"])
        if job["tasks"][5]["status"] != "Completed":
            update_task(job, 5, "Running", "Generating PRINT_READY from the saved working copy.", actor, execution=execution)
            await persist()
            working = latest(job, "WORKING_COPY")
            prepared = await file_bytes(job, working)
            produced = make_print_ready(prepared, job["recipe"], job["id"], job["generation"])
            print_ready = await create_file(
                job,
                "PRINT_READY",
                produced,
                working,
                "Production PDF from prepared copy; no colour or font substitution.",
            )
            update_task(job, 5, "Completed", "PRINT_READY PDF stored with a checksum.", actor, print_ready["id"])
        if job["tasks"][6]["status"] != "Completed":
            update_task(job, 6, "Running", "Reopening and verifying the production PDF.", actor, execution=execution)
            await persist()
            print_ready = latest(job, "PRINT_READY")
            report = verify(
                await file_bytes(job, print_ready),
                job["recipe"],
                job["sides"],
                print_ready["sha"],
            )
            job["verification"] = {
                **report,
                "fileId": print_ready["id"],
                "sha": print_ready["sha"],
                "generation": job["generation"],
                "recipeVersion": job["recipe"]["version"],
            }
            if report["errors"]:
                update_task(job, 6, "Blocked", " ".join(report["errors"]), actor, print_ready["id"])
                await persist()
                return job
            update_task(
                job,
                6,
                "Completed",
                "Stored PRINT_READY PDF reopened and independently verified.",
                actor,
                print_ready["id"],
            )
            update_task(job, 7, "Waiting for approval", "Review the actual production proof.", actor)
        for task in job["tasks"][2:7]:
            if task["status"] == "Completed" and execution and execution not in task["executions"]:
                task["executions"].append(execution)
        await persist()
        return job
    except PdfError as error:
        update_task(
            job,
            2,
            "Failed",
            str(error),
            actor,
            execution=execution,
            error=str(error),
            recovery="Retry checks or upload a fresh PDF.",
        )
        await persist()
        return job


async def process_with_lease(job_id, generation, actor):
    """Claim a durable execution before any GridFS write and retain step evidence."""
    token = await lock(job_id)
    execution_id = new_id()
    try:
        job = await get_job(job_id)
        if not job:
            raise AppError("Job not found.", 404)
        if job["generation"] != generation:
            raise AppError("Artwork version changed. Refresh before continuing.")
        if job.get("archived"):
            raise AppError("This job is archived.", 409)
        if job.get("state") != "active":
            raise AppError(f"This job is {job.get('state')}. Resume it before processing.")
        if job["tasks"][6]["status"] == "Completed":
            return {"queued": False, "job": job, "execution": None}
        existing = await db.executions.find_one(
            {"job_id": job_id, "generation": generation, "status": {"$in": ["Queued", "Running"]}},
            {"_id": 0},
        )
        if existing:
            raise AppError("Artwork processing is already claimed. Refresh for its saved progress.")
        await db.executions.insert_one(
            {
                "_id": execution_id,
                "job_id": job_id,
                "generation": generation,
                "action": "process",
                "status": "Running",
                "actor": actor,
                "lease_until": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
                "created": now(),
                "updated": now(),
            }
        )
        job["activeExecution"] = execution_id
        await save_job(job, token)
        result = await run_pdf_workflow(job, actor, execution_id, token)
        state = "Blocked" if any(item["status"] in {"Blocked", "Failed"} for item in result["tasks"][2:7]) else "Completed"
        await db.executions.update_one(
            {"_id": execution_id},
            {"$set": {"status": state, "updated": now(), "events": result["events"][-12:]}},
        )
        result.pop("activeExecution", None)
        await save_job(result, token)
        return {"queued": True, "job": result, "execution": execution_id}
    except Exception as error:
        await db.executions.update_one(
            {"_id": execution_id},
            {"$set": {"status": "Failed", "error": str(error), "updated": now()}},
            upsert=True,
        )
        raise
    finally:
        await unlock(job_id, token)


async def recover_interrupted_executions():
    with unscoped():
        expired = await db.executions.find(
            {"status": {"$in": ["Queued", "Running"]}, "lease_until": {"$lt": now()}},
        ).to_list(100)
    for execution in expired:
        with shop_scope(execution.get("shop_id") or PRINT2GO_SHOP_ID):
            await db.executions.update_one(
                {"_id": execution["_id"]},
                {"$set": {"status": "Interrupted", "updated": now()}},
            )
            job = await get_job(execution["job_id"])
            if not job or job.get("state") != "active":
                continue
            for task in job["tasks"][2:7]:
                if task["status"] == "Running":
                    update_task(
                        job,
                        job["tasks"].index(task),
                        "Failed",
                        "Execution was interrupted. Retry safely from saved evidence.",
                        "Application",
                        execution=execution["_id"],
                        recovery="Retry checks. Completed files remain immutable.",
                    )
            job.pop("activeExecution", None)
            try:
                await save_job(job)
            except AppError:
                continue


async def readiness(job):
    settings = await db.settings.find_one({"kind": "settings"}, {"_id": 0})
    agent = await db.connector_state.find_one({"role": "agent"}, {"_id": 0})
    if not settings or not settings.get("printer"):
        raise AppError("No printer is selected. Verify a printer on the route step, then check again.")
    if not job.get("route") or job["route"]["settingsVersion"] != settings["version"]:
        raise AppError("Shop settings changed after the route was chosen. Choose the production route again.")
    if not agent or not agent.get("writable"):
        raise AppError(
            "The shop computer is not connected. Start the connector with a writable folder, then check again. "
            "This step does not print."
        )
    heartbeat = datetime.fromisoformat(agent["lastSeen"])
    if datetime.now(timezone.utc) - heartbeat > timedelta(seconds=90):
        raise AppError(
            "The shop computer has not checked in for over a minute. Start the connector again, then check readiness."
        )
    return agent