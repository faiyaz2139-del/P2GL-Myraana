import hashlib
from datetime import datetime, timedelta, timezone

from agents.orchestrator import MultiAgentOrchestrator
from agents.schemas import JobState

from p2g.core import AppError, db, lock, new_id, now, unlock
from p2g.workflow import get_job, latest, record_event, save_job


def _fresh(timestamp, seconds=90):
    if not timestamp:
        return False
    return datetime.now(timezone.utc) - datetime.fromisoformat(timestamp) < timedelta(seconds=seconds)


async def build_job_state(job):
    """Build trusted agent input exclusively from saved job, file, and shop records."""
    original = latest(job, "ORIGINAL")
    print_ready = latest(job, "PRINT_READY")
    inspection = job.get("inspection") or {}
    verification = job.get("verification") or {}
    approval = job.get("approval") or {}
    authorization = job.get("authorization") or {}
    settings = await db.settings.find_one({"_id": "shop"}, {"_id": 0})
    agent = await db.connector_state.find_one({"_id": "agent"}, {"_id": 0})
    capabilities = await db.machine_capabilities.find(
        {"enabled": True, "stocks": job["stock"]},
        {"_id": 0},
    ).to_list(100)
    verified = bool(
        print_ready
        and verification.get("fileId") == print_ready["id"]
        and verification.get("sha") == print_ready["sha"]
        and verification.get("generation") == job["generation"]
        and not verification.get("errors")
    )
    approval_matches = bool(
        approval.get("fileId") == (print_ready or {}).get("id")
        and approval.get("sha") == (print_ready or {}).get("sha")
        and approval.get("generation") == job["generation"]
    )
    authorization_matches = bool(
        authorization.get("fileId") == (print_ready or {}).get("id")
        and authorization.get("sha") == (print_ready or {}).get("sha")
        and authorization.get("generation") == job["generation"]
    )
    connector_ready = bool(
        job.get("readiness")
        and job.get("route")
        and settings
        and job["route"].get("settingsVersion") == settings.get("version")
        and agent
        and agent.get("writable")
        and _fresh(agent.get("lastSeen"))
        and "pdf-hot-folder" in agent.get("capabilities", [])
    )
    qc = job.get("qc") or {}
    return JobState(
        job_id=job["id"],
        product="business_card",
        quantity=job["quantity"],
        order_spec={"stock": job["stock"], "finish": job["finish"], "sides": job["sides"]},
        artwork={"original_file_id": original["id"] if original else None},
        preflight={
            "measured": job["tasks"][2]["status"] == "Completed",
            "unsafe_content": bool(inspection.get("errors")),
            "bleed_ok": inspection.get("bleed") == "correct",
            "bleed_decision": job.get("bleedDecision"),
            "dpi_warning": next((item for item in inspection.get("warnings", []) if "dpi" in item.lower()), None),
            "pages": inspection.get("pages", []),
        },
        print_ready={
            "file_id": print_ready["id"] if print_ready else None,
            "checksum": print_ready["sha"] if print_ready else None,
            "verified": verified,
        },
        recipe={"product": "business_card", **job["recipe"]},
        optimization={"candidate_plans": capabilities},
        production={"route": job.get("route"), "readiness": job.get("readiness")},
        qc=qc,
        approved_file_id=approval.get("fileId") if approval_matches else None,
        approved_checksum=approval.get("sha") if approval_matches else None,
        human_authorized=authorization_matches,
        connector_ready=connector_ready,
        physical_print_enabled=False,
    )


async def evaluate_agents(job_id, actor):
    """Run once under the existing Mongo job lease; request bodies never supply state."""
    token = await lock(job_id)
    execution_id = new_id()
    try:
        job = await get_job(job_id)
        if not job:
            raise AppError("Job not found.", 404)
        if job.get("state") != "active":
            raise AppError(f"This job is {job.get('state')}. Resume it before evaluation.")
        state = await build_job_state(job)
        state_signature = hashlib.sha256(state.model_dump_json().encode()).hexdigest()
        existing = await db.executions.find_one(
            {
                "job_id": job_id,
                "action": "agents_evaluate",
                "generation": job["generation"],
                "state_signature": state_signature,
            },
            {"_id": 0},
        )
        if existing:
            return {"execution": existing["id"], "results": existing["results"], "idempotent": True}
        results = [item.model_dump(mode="json") for item in MultiAgentOrchestrator().run_until_gate(state)]
        for result in results:
            record_event(job, f"Agent {result['agent']}: {result['summary']}", actor)
        await db.executions.insert_one(
            {
                "_id": execution_id,
                "id": execution_id,
                "job_id": job_id,
                "generation": job["generation"],
                "action": "agents_evaluate",
                "state_signature": state_signature,
                "status": results[-1]["status"] if results else "STOP",
                "actor": actor,
                "results": results,
                "created": now(),
                "updated": now(),
            }
        )
        await save_job(job, token)
        return {"execution": execution_id, "results": results, "idempotent": False}
    finally:
        await unlock(job_id, token)