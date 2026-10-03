"""
Narrow READ-ONLY regression for the stale job.readiness snapshot fix.

Context:
  Previous iteration (iteration_4) found that reset_from() cleared the task row
  for step 11 (readiness) but did NOT pop job["readiness"], leaving a stale
  snapshot after a settings mutation. The main agent then added a single-line
  cleanup inside reset_from() to pop "readiness" when route authority is reset
  (index <= 8). This test verifies that invariant on the pre-existing isolated
  Settings QA job.

Scope (strictly read-only):
  - Login as the disposable QA user.
  - GET /api/jobs to find the active Settings QA job.
  - Assert: job.readiness is ABSENT.
  - Assert: PRINT_READY file is still present.
  - Assert: approval exists AND approval.generation == job.generation
            AND approval.sha matches the current PRINT_READY sha.
  - Assert: job.route is absent and job.authorization is absent.

Non-goals:
  - Do NOT mutate settings, the job, the connector, AI, or hardware.
  - Do NOT create a new reset event (would bump generation and mutate the job).
  - Do NOT issue any action (not even the previously-permitted 409 probe).
"""
import os
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
QA_EMAIL = "qa@print2go.test"
QA_PASSWORD = "Temporary-QA-Only-2026!"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "Origin": BASE_URL})
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": QA_EMAIL, "password": QA_PASSWORD},
    )
    assert r.status_code == 200, f"QA login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def job(session):
    r = session.get(f"{BASE_URL}/api/jobs")
    assert r.status_code == 200, r.text
    jobs = r.json()
    assert jobs, "Isolated QA DB should contain at least one job"
    active = [j for j in jobs if j.get("state") == "active"]
    assert active, f"No active QA job found: {jobs}"
    # Re-fetch the single job by id to guarantee a fresh server-side view
    r2 = session.get(f"{BASE_URL}/api/jobs/{active[0]['id']}")
    assert r2.status_code == 200, r2.text
    return r2.json()


def _latest(job, stage):
    files = [f for f in job.get("files", []) if f.get("stage") == stage]
    return files[-1] if files else None


# --- primary invariant: stale readiness snapshot is gone ---
def test_readiness_snapshot_absent(job):
    assert "readiness" not in job or not job.get("readiness"), (
        f"job.readiness must be absent after reset_from(); "
        f"got stale snapshot: {job.get('readiness')!r}"
    )


# --- supporting invariants: proof + approval preserved ---
def test_print_ready_preserved(job):
    pr = _latest(job, "PRINT_READY")
    assert pr is not None, "PRINT_READY proof must still be present"
    assert pr.get("sha"), "PRINT_READY must retain its sha"


def test_approval_matches_current_generation(job):
    approval = job.get("approval")
    assert approval, "Approval must be preserved"
    assert approval.get("generation") == job.get("generation"), (
        f"approval.generation={approval.get('generation')} must match "
        f"job.generation={job.get('generation')}"
    )
    pr = _latest(job, "PRINT_READY")
    assert approval.get("sha") == pr.get("sha"), (
        "Approval sha must still reference the current PRINT_READY sha"
    )


# --- supporting invariants: route authority remains revoked ---
def test_route_absent(job):
    assert not job.get("route"), f"job.route must be absent, got {job.get('route')!r}"


def test_authorization_absent(job):
    assert not job.get("authorization"), (
        f"job.authorization must be absent, got {job.get('authorization')!r}"
    )
