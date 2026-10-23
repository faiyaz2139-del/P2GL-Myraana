"""Automatic mode runs the job and stops for approval. It does not print."""
from datetime import datetime, timedelta, timezone

from p2g.automatic import (
    apply_customer_approval,
    automatic_mode,
    automatic_route_note,
    build_proof_link,
    proof_link_state,
    timeline,
)
from p2g.card_flow import stage_fiery_hold
from p2g.connector_auth import credential_hash


STOP_SIZE = "STOP: size error, artwork needs re-design. Never resize or stretch it."


def _tasks():
    tasks = []
    for index in range(16):
        status = "Completed" if index < 7 else "Pending"
        tasks.append({"status": status, "result": ""})
    tasks[7]["status"] = "Waiting for approval"
    return tasks


def test_automatic_mode_is_on_unless_the_shop_turns_it_off():
    assert automatic_mode({}) is True
    assert automatic_mode({"printer": "Fiery"}) is True
    assert automatic_mode({"automaticMode": True}) is True
    assert automatic_mode({"automaticMode": False}) is False


def test_timeline_hides_detail_until_a_step_fails():
    waiting = {"tasks": _tasks(), "approval": {}}
    phases = timeline(waiting)
    assert [phase["id"] for phase in phases] == ["order", "proof", "approval", "hold", "press", "finish"]
    assert all(phase["detail"] == "" for phase in phases)
    assert next(phase for phase in phases if phase["id"] == "approval")["state"] == "current"
    stopped = {
        "tasks": _tasks(),
        "cardRoute": {"stop": STOP_SIZE},
    }
    stopped["tasks"][6]["status"] = "Blocked"
    failed = timeline(stopped)
    proof = next(phase for phase in failed if phase["id"] == "proof")
    assert proof["state"] == "failed"
    assert proof["detail"] == STOP_SIZE
    assert all(phase["detail"] == "" or phase["state"] == "failed" for phase in failed)


def test_approval_does_not_print_and_the_route_note_names_london_bc():
    job = {"tasks": _tasks(), "generation": 2, "finish": "Matte", "spec": {"product": "business-card"}, "recipe": {}}
    outcome = apply_customer_approval(job, {"sha": "abc", "id": "file-1"}, "Customer", "2026-10-23T00:00:00+00:00")
    assert outcome == "approved"
    assert job["approval"]["sha"] == "abc"
    assert job["tasks"][7]["status"] == "Completed"
    assert "fieryHold" not in job
    assert "authorization" not in job
    assert apply_customer_approval(job, {"sha": "abc"}, "Customer", "2026-10-23T00:01:00+00:00") == "already"
    note = automatic_route_note(job, {
        "printer": "Xerox EX-Li PX300 Server",
        "discoveredPrinters": [{
            "name": "Xerox EX-Li PX300 Server",
            "isFiery": True,
            "address": "192.168.0.200",
        }],
    })
    assert "London BC" in note
    assert "Matte" in note
    assert "Nothing is printed." in note


def test_hold_is_queued_without_printing():
    job = {
        "tasks": _tasks(),
        "finish": "Matte",
        "stock": "14pt matte",
        "generation": 3,
        "recipe": {"id": "business-card", "production": {"preset": "London BC", "cutter": {"model": "Duplo DC-618", "jobNumber": 2}}},
    }
    for index in range(9):
        job["tasks"][index]["status"] = "Completed"
    ready = {"delivery": "fiery_hold", "id": "device-1", "hostname": "P2GL-2", "lastSeen": "2026-10-23T00:00:00+00:00"}
    stage_fiery_hold(
        job,
        ready,
        {"name": "Xerox EX-Li PX300 Server", "address": "192.168.0.200"},
        "Op",
        {"sha": "abc", "id": "file-1"},
        "2026-10-23T00:00:00+00:00",
    )
    assert job["fieryHold"]["status"] == "queued"
    assert job["fieryHold"]["explicit"] is True
    assert job["fieryHold"]["deviceId"] == "device-1"
    assert job["fieryHold"]["printed"] is False
    assert job["fieryHold"]["held"] is False
    assert job["tasks"][9]["status"] == "Completed"
    assert job["tasks"][10]["status"] == "Completed"
    assert job["tasks"][11]["status"] == "Completed"
    assert job["tasks"][12]["status"] == "Waiting for operator"
    assert "Confirm only after physical sheets print." in job["tasks"][12]["result"]
    assert job["tasks"][13]["result"] == "Cut on Duplo DC-618, job 2"
    assert job["authorization"]["sha"] == "abc"
    assert "will not print" in job["tasks"][11]["result"]


def test_proof_link_expires_and_a_used_link_stays_used():
    created = datetime(2026, 10, 23, tzinfo=timezone.utc).isoformat()
    token = "proof-token-value-0123456789"
    link = build_proof_link("job-1", "shop-1", token, "admin-1", created, link_id="link-1")
    assert link["token_hash"] == credential_hash(token)
    assert link["token_hash"] != token
    assert proof_link_state(link, created) == "open"
    used = {**link, "status": "used", "used_at": created}
    assert proof_link_state(used, created) == "used"
    later = (datetime(2026, 10, 23, tzinfo=timezone.utc) + timedelta(days=8)).isoformat()
    assert proof_link_state(link, later) == "expired"
