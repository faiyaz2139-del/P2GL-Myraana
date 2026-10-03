import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from p2g.core import AppError, db, new_id, now, sha256
from p2g.pdfcheck import PdfError, inspect, make_print_ready, prepare, render_page, verify


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
    "safe": 0.125,
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


def update_task(job, index, status, result, actor="Application", evidence=None):
    item = job["tasks"][index]
    item["status"] = status
    item["result"] = result
    item["updated"] = now()
    if status == "Completed":
        item.setdefault("started", now())
        item["finished"] = now()
    if evidence and evidence not in item["evidence"]:
        item["evidence"].append(evidence)
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
    if index <= 6:
        job.pop("verification", None)
    if index <= 3:
        job.pop("bleedDecision", None)
    record_event(job, reason)


def public(doc):
    if not doc:
        return None
    copy = {key: value for key, value in doc.items() if key != "_id"}
    return copy


async def ensure_collections():
    await db.users.create_index("email", unique=True)
    await db.sessions.create_index("expires")
    await db.connector_nonces.create_index("created", expireAfterSeconds=300)
    await db.connector_nonces.create_index("nonce", unique=True)
    await db.bootstrap.update_one(
        {"_id": "first-run"},
        {"$setOnInsert": {"configured": False, "created": now()}},
        upsert=True,
    )
    if not await db.recipes.find_one({"id": "business-card", "version": 1}):
        recipe = {**DEFAULT_RECIPE, "created": now()}
        await db.recipes.insert_one(recipe)


def password_hash(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def password_matches(password, encoded):
    return bcrypt.checkpw(password.encode(), encoded.encode())


async def current_user(request: Request):
    raw = request.cookies.get("p2g_session")
    if not raw:
        return None
    session = await db.sessions.find_one(
        {"token_hash": sha256(raw), "expires": {"$gt": now()}},
        {"_id": 0},
    )
    if not session:
        return None
    return await db.users.find_one({"id": session["user_id"]}, {"_id": 0, "password": 0})


def require_user(user):
    if not user:
        raise AppError("Sign in to your shop.", 401)
    return user


def require_admin(user):
    require_user(user)
    if user["role"] != "admin":
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
    return token, cookie, {key: user[key] for key in ("id", "name", "email", "role")}


async def create_session(token, user_id):
    expiry = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    await db.sessions.insert_one(
        {"id": new_id(), "user_id": user_id, "token_hash": sha256(token), "expires": expiry}
    )


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
    bucket = AsyncIOMotorGridFSBucket(db, bucket_name="pdf_files")
    stream = bucket.open_upload_stream_with_id(
        file_id,
        meta["name"],
        metadata={"job_id": job["id"], "sha": meta["sha"], "stage": stage},
    )
    await stream.write(content)
    await stream.close()
    job.setdefault("files", []).append(meta)
    return meta


async def file_bytes(job, record):
    bucket = AsyncIOMotorGridFSBucket(db, bucket_name="pdf_files")
    stream = await bucket.open_download_stream(record["id"])
    content = await stream.read()
    if hashlib.sha256(content).hexdigest() != record["sha"]:
        raise AppError("Saved file identity does not match its recorded checksum.", 409)
    return content


async def save_job(job):
    job["updated"] = now()
    result = await db.jobs.replace_one(
        {"_id": job["id"], "revision": job["revision"]},
        {**job, "_id": job["id"], "revision": job["revision"] + 1},
    )
    if not result.matched_count:
        raise AppError("This job changed in another session. Refresh and retry.")
    job["revision"] += 1
    return job


async def get_job(job_id):
    return public(await db.jobs.find_one({"_id": job_id}))


async def run_pdf_workflow(job, actor):
    original = latest(job, "ORIGINAL")
    if not original:
        raise AppError("Upload artwork first.")
    content = await file_bytes(job, original)
    try:
        if job["tasks"][2]["status"] != "Completed":
            report = inspect(content, job["recipe"], job["sides"])
            job["inspection"] = report
            if report["errors"]:
                update_task(job, 2, "Blocked", " ".join(report["errors"]), actor, original["id"])
                await save_job(job)
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
            if job["inspection"]["bleed"] == "missing" and not job.get("bleedDecision"):
                update_task(
                    job,
                    3,
                    "Needs attention",
                    "Artwork is trim size only. Choose corrected artwork or a blank border.",
                    actor,
                    original["id"],
                )
                await save_job(job)
                return job
            update_task(job, 3, "Completed", "Bleed decision recorded.", actor, original["id"])
        if job["tasks"][4]["status"] != "Completed":
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
                await save_job(job)
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
        await save_job(job)
        return job
    except PdfError as error:
        update_task(job, 2, "Failed", str(error), actor)
        await save_job(job)
        return job


async def readiness(job):
    settings = await db.settings.find_one({"_id": "shop"}, {"_id": 0})
    agent = await db.connector_state.find_one({"_id": "agent"}, {"_id": 0})
    if not settings or not settings.get("printer"):
        raise AppError("Configure a printer in Shop settings.")
    if not job.get("route") or job["route"]["settingsVersion"] != settings["version"]:
        raise AppError("Production settings changed. Choose the route again.")
    if not agent or not agent.get("writable"):
        raise AppError("Shop disconnected. Start the connector with a writable staging folder.")
    heartbeat = datetime.fromisoformat(agent["lastSeen"])
    if datetime.now(timezone.utc) - heartbeat > timedelta(seconds=90):
        raise AppError("Shop connector heartbeat is stale. Reconnect before authorization.")
    return agent