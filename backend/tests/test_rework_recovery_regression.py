"""
Narrow regression for the Operator recovery fix (QC rejection -> rework).

Scope (ISOLATED SYNTHETIC FIXTURE ONLY):
  - Build an in-memory synthetic job dict (not persisted, no DB, no auth).
  - Exercise the exact rework-branch state transitions used by
    backend/server.py job_action rework (lines ~510-517).
  - Assert the job returns to task #12 (index 11) in "Waiting for approval",
    which is the human re-authorization step.

Also includes source-level anchor assertions so that any accidental drift of
the production rework handler (e.g. switching to update_task(job, 10, ...)
or using an incorrect status label) is caught by this regression.

Non-goals:
  - No production DB access, no login, no HTTP calls, no file I/O.
  - No frontend DOM assertions (covered by Playwright).
"""
import os
import re
import sys

import pytest
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

from p2g.workflow import tasks as make_tasks, update_task  # noqa: E402


SERVER_PY = "/app/backend/server.py"


def _synthetic_job():
    """Minimal job dict shaped like a real job that has reached QC rejection."""
    job = {
        "id": "TEST_synthetic_rework_job",
        "generation": 2,
        "state": "active",
        "tasks": make_tasks(),
        "events": [],
        "authorization": {"sha": "deadbeef", "generation": 2, "by": "op"},
    }
    # Mark tasks index 1..13 (task #2..#14) Completed to simulate pre-QC state.
    for i in range(1, 14):
        job["tasks"][i]["status"] = "Completed"
        job["tasks"][i]["result"] = "ok"
    # Task 14 (index 14) rejected: QC Needs attention.
    job["tasks"][14]["status"] = "Needs attention"
    job["tasks"][14]["result"] = "Quality check rejected; rework is required."
    # Task 15 (index 15) still Pending.
    return job


def _apply_rework(job, actor="qa-op"):
    """
    Replica of backend/server.py job_action rework branch (lines 510-517).
    Kept in lock-step via the source-anchor test below.
    """
    if job["tasks"][14]["status"] != "Needs attention":
        raise AssertionError("Rework guard tripped unexpectedly in test")
    job.pop("authorization", None)
    for index in range(11, 16):
        job["tasks"][index]["status"] = "Pending"
        job["tasks"][index]["result"] = "Rework requires new human confirmation."
    update_task(
        job, 11, "Waiting for approval",
        "Re-authorize the verified production PDF.", actor,
    )


# --- behavior ---

def test_rework_requires_qc_needs_attention():
    job = _synthetic_job()
    job["tasks"][14]["status"] = "Completed"
    with pytest.raises(AssertionError):
        _apply_rework(job)


def test_rework_returns_job_to_task12_reauthorization():
    job = _synthetic_job()
    _apply_rework(job)
    # Task #12 (index 11) is now the human re-authorization step.
    assert job["tasks"][11]["status"] == "Waiting for approval", job["tasks"][11]
    assert "Re-authorize" in job["tasks"][11]["result"]


def test_rework_clears_authorization():
    job = _synthetic_job()
    _apply_rework(job)
    assert "authorization" not in job


def test_rework_resets_tasks_12_through_16_pending_or_waiting():
    job = _synthetic_job()
    _apply_rework(job)
    # index 11 -> Waiting for approval (set above); indices 12..15 -> Pending
    for idx in range(12, 16):
        assert job["tasks"][idx]["status"] == "Pending", (idx, job["tasks"][idx])
        assert job["tasks"][idx]["result"] == "Rework requires new human confirmation."


def test_rework_preserves_pre_authorize_history():
    job = _synthetic_job()
    _apply_rework(job)
    # Tasks before the re-authorize step must remain Completed.
    for idx in range(1, 11):
        assert job["tasks"][idx]["status"] == "Completed", (idx, job["tasks"][idx])


# --- source anchor: production handler still matches the replica above ---

def test_server_rework_branch_source_anchor():
    with open(SERVER_PY, "r", encoding="utf-8") as f:
        src = f.read()
    # Guard
    assert re.search(
        r'elif\s+action\s*==\s*["\']rework["\']\s*:\s*\n'
        r'\s*if\s+job\["tasks"\]\[14\]\["status"\]\s*!=\s*["\']Needs attention["\']',
        src,
    ), "rework branch guard on tasks[14] missing or changed"
    # Clears authorization
    assert 'job.pop("authorization", None)' in src
    # Resets tasks 11..15
    assert "for index in range(11, 16):" in src
    # Re-authorization target: update_task(job, 11, "Waiting for approval", ...)
    assert re.search(
        r'update_task\(\s*job\s*,\s*11\s*,\s*["\']Waiting for approval["\']',
        src,
    ), "rework must land task index 11 (task #12) in Waiting for approval"
