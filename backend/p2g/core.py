import os
import time
import uuid
import hashlib
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
bucket = AsyncIOMotorGridFSBucket(db, bucket_name="pdf_files")
LEASE_MS = 120000


class AppError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.message = message
        self.status = status


def now():
    return datetime.now(timezone.utc).isoformat()


def ms():
    return int(time.time() * 1000)


def new_id():
    return str(uuid.uuid4())


def sha256(data):
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def clean(doc):
    if doc is None:
        return None
    out = {k: v for k, v in doc.items() if k not in ("_id", "lock", "locked_at")}
    out["id"] = doc["_id"]
    return out


async def read_job(job_id):
    return clean(await db.jobs.find_one({"_id": job_id}))


async def lock(job_id):
    token = new_id()
    t = ms()
    r = await db.jobs.update_one(
        {"_id": job_id, "$or": [{"lock": None}, {"locked_at": {"$lt": t - LEASE_MS}}]},
        {"$set": {"lock": token, "locked_at": t}},
    )
    if r.matched_count == 0:
        if not await db.jobs.find_one({"_id": job_id}, {"_id": 1}):
            raise AppError("Job not found.", 404)
        raise AppError("This job is already being updated. Please wait and refresh.")
    return token


async def unlock(job_id, token):
    await db.jobs.update_one({"_id": job_id, "lock": token}, {"$set": {"lock": None, "locked_at": None}})


async def save(job, token):
    job["updated"] = now()
    data = {k: v for k, v in job.items() if k not in ("id", "revision")}
    r = await db.jobs.update_one(
        {"_id": job["id"], "lock": token},
        {"$set": {**data, "locked_at": ms()}, "$inc": {"revision": 1}},
    )
    if r.matched_count == 0:
        raise AppError("Execution lease expired. Refresh the job.")
    job["revision"] = job.get("revision", 0) + 1


async def record_execution(ex_id, job_id, action, status, data):
    await db.executions.update_one(
        {"_id": ex_id},
        {"$set": {"job_id": job_id, "action": action, "status": status, "data": data, "updated": now()},
         "$setOnInsert": {"created": now()}},
        upsert=True,
    )
