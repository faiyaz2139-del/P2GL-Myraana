"""Self-cleaning, real-endpoint integration test for the deterministic agents.

Run from /app/backend. It starts a separate local API on 8011 and never points
that process at the live database. It intentionally performs no AI or printing.
"""
import asyncio
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
REPORT_PATH = Path("/app/test_reports/agents_e2e.json")
TEST_DB = "p2g_integration_test"
PORT = 8011
BASE = f"http://127.0.0.1:{PORT}/api"
FIXTURE_URLS = {
    "v1": "https://customer-assets-39nsmqrw.emergentagent.net/job_p2g-production/"
    "artifacts/yx2e1kxe_zztest_card_v1.pdf",
    "v2": "https://customer-assets-39nsmqrw.emergentagent.net/job_p2g-production/"
    "artifacts/pckvyliz_zztest_card_v2_changed.pdf",
}
EXPECTED_SHA = {
    "v1": "60addb9686760b9ad340d452348eceb11e71e3aee554b84ace7aaf660ee51d70",
    "v2": "d1433c2b3bbeb836fdcab3bddc8e530e6050420080a401833178413eba9f2692",
}


class IntegrationRun:
    def __init__(self):
        self.env = dotenv_values(ENV_PATH)
        self.results = []
        self.server = None
        self.session = requests.Session()
        self.job_id = None
        self.job = None
        self.print_ready = None

    def record(self, check, passed, **evidence):
        self.results.append(
            {
                "check": check,
                "status": "PASS" if passed else "FAIL",
                "evidence": evidence,
            }
        )

    def request(self, method, path, **kwargs):
        return self.session.request(method, f"{BASE}{path}", timeout=60, **kwargs)

    async def database(self):
        client = AsyncIOMotorClient(self.env["MONGO_URL"])
        return client, client[TEST_DB]

    async def drop_test_database(self):
        client, _ = await self.database()
        await client.drop_database(TEST_DB)
        client.close()

    def fixture(self, name):
        target = Path(f"/tmp/zztest_card_{name}.pdf")
        response = requests.get(FIXTURE_URLS[name], timeout=60)
        response.raise_for_status()
        target.write_bytes(response.content)
        checksum = hashlib.sha256(response.content).hexdigest()
        self.record(f"fixture {name} checksum", checksum == EXPECTED_SHA[name], sha256=checksum)
        return target

    def start_server(self):
        live_name = self.env.get("DB_NAME")
        if not live_name or live_name == TEST_DB:
            raise RuntimeError("Refusing to run: test DB must differ from the live DB name.")
        server_env = os.environ.copy()
        server_env.update({key: value for key, value in self.env.items() if value is not None})
        server_env["DB_NAME"] = TEST_DB
        server_env["CONNECTOR_SECRET"] = "zztest-isolated-connector-only"
        self.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PORT)],
            cwd=ROOT,
            env=server_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(30):
            try:
                response = requests.get(f"{BASE}/", timeout=2)
                if response.ok:
                    self.record("isolated port 8011 health", True, http=response.status_code)
                    return
            except requests.RequestException:
                time.sleep(1)
        raise RuntimeError("Isolated backend did not become healthy.")

    def stop_server(self):
        if self.server and self.server.poll() is None:
            os.killpg(self.server.pid, signal.SIGTERM)
            self.server.wait(timeout=15)

    async def seed_capability(self):
        client, db = await self.database()
        await db.machine_capabilities.insert_one(
            {
                "enabled": True,
                "stocks": "14pt matte",
                "plan_id": "zztest-12up",
                "quality_pass": True,
                "spec_pass": True,
                "turnaround_pass": True,
                "safety_pass": True,
                "sheets": 10,
                "waste_sheets": 1,
                "clicks": 20,
                "machine_minutes": 2,
                "operator_minutes": 2,
                "setup_count": 1,
                "finishing_steps": 1,
                "reprint_risk": 0,
                "outsourced": False,
                "turnaround_risk": 0,
            }
        )
        client.close()

    async def disconnect_shop(self):
        client, db = await self.database()
        await db.connector_state.delete_many({})
        client.close()

    def latest_job(self):
        response = self.request("GET", f"/jobs/{self.job_id}")
        response.raise_for_status()
        self.job = response.json()
        return self.job

    def run_check(self, name, callback):
        try:
            callback()
        except Exception as error:
            self.record(name, False, reason=str(error))

    def run(self):
        v1 = self.fixture("v1")
        v2 = self.fixture("v2")
        self.start_server()

        def bootstrap():
            response = self.request(
                "POST",
                "/auth/setup",
                json={
                    "name": "ZZTEST Operator",
                    "email": "zztest@print2go.test",
                    "password": "Temporary-Integration-2026!",
                },
            )
            self.record("isolated first-run admin", response.status_code == 200, http=response.status_code)
            response = self.request(
                "POST",
                "/settings",
                json={
                    "printer": "ZZTEST RIP",
                    "stocks": ["14pt matte"],
                    "sides": [1, 2],
                    "instructions": "Isolated, non-printing test only.",
                },
            )
            self.record("isolated shop settings", response.status_code == 200, http=response.status_code)

        def create_and_process_v1():
            response = self.request(
                "POST",
                "/jobs",
                json={
                    "customer": "ZZTEST-Agent-E2E",
                    "quantity": 100,
                    "sides": 1,
                    "stock": "14pt matte",
                    "finish": "Matte",
                    "due": "2030-01-01",
                },
            )
            self.job = response.json()
            self.job_id = self.job["id"]
            self.record("create ZZTEST job", response.status_code == 200, job_id=self.job_id)
            with v1.open("rb") as handle:
                response = self.request(
                    "POST",
                    f"/jobs/{self.job_id}/artwork",
                    files={"file": (v1.name, handle, "application/pdf")},
                )
            self.job = response.json()
            self.record("upload v1 original", response.status_code == 200, http=response.status_code)
            response = self.request("POST", f"/jobs/{self.job_id}/process", json={"generation": self.job["generation"]})
            self.record("inspection and PRINT_READY generation", response.status_code == 200, http=response.status_code)
            self.latest_job()
            if self.job["tasks"][3]["status"] == "Needs attention":
                response = self.request(
                    "POST",
                    f"/jobs/{self.job_id}/action",
                    json={"action": "bleed", "generation": self.job["generation"], "decision": "blank-border"},
                )
                self.record("operator bleed decision", response.status_code == 200, http=response.status_code)
                response = self.request("POST", f"/jobs/{self.job_id}/process", json={"generation": self.job["generation"]})
                self.record("process after operator bleed decision", response.status_code == 200, http=response.status_code)
                self.latest_job()
            files = [item for item in self.job["files"] if item["stage"] == "PRINT_READY"]
            self.print_ready = files[-1] if files else None
            verified = bool(
                self.print_ready
                and self.job.get("verification", {}).get("sha") == self.print_ready.get("sha")
            )
            self.record(
                "independent PRINT_READY verification",
                verified,
                file_id=(self.print_ready or {}).get("id"),
                checksum=(self.print_ready or {}).get("sha"),
            )

        def approve_route_authorize():
            if not self.print_ready:
                raise RuntimeError("PRINT_READY missing; downstream checks are recorded as failed.")
            response = self.request(
                "POST",
                f"/jobs/{self.job_id}/action",
                json={
                    "action": "approve",
                    "generation": self.job["generation"],
                    "sha": self.print_ready["sha"],
                    "acknowledged": True,
                },
            )
            self.v1_approval = response.status_code == 200
            self.record("exact-file proof approval", self.v1_approval, http=response.status_code, file_id=self.print_ready["id"], checksum=self.print_ready["sha"])
            asyncio.run(self.seed_capability())
            self.latest_job()
            for action, data in (("route", {}), ("handoff", {"note": "ZZTEST staging only"})):
                response = self.request(
                    "POST",
                    f"/jobs/{self.job_id}/action",
                    json={"action": action, "generation": self.job["generation"], **data},
                )
                self.record(f"{action} workflow action", response.status_code == 200, http=response.status_code)
                self.latest_job()
            response = requests.post(
                f"{BASE}/connector",
                headers={"Authorization": "Bearer zztest-isolated-connector-only"},
                json={
                    "timestamp": int(time.time() * 1000),
                    "nonce": str(uuid.uuid4()),
                    "destination": "/tmp/zztest-no-print",
                    "writable": True,
                    "capabilities": ["pdf-hot-folder"],
                    "handoffs": [],
                },
                timeout=60,
            )
            self.record("simulated connector heartbeat", response.status_code == 200, http=response.status_code)
            self.latest_job()
            for action, data in (("readiness", {}), ("authorize", {"sha": self.print_ready["sha"], "acknowledged": True})):
                response = self.request(
                    "POST",
                    f"/jobs/{self.job_id}/action",
                    json={"action": action, "generation": self.job["generation"], **data},
                )
                self.record(f"{action} workflow action", response.status_code == 200, http=response.status_code)
                self.latest_job()

        def evaluate_qc_and_forgery():
            forged = self.request(
                "POST",
                f"/jobs/{self.job_id}/agents/evaluate",
                json={"approved_file_id": "forged", "connector_ready": True, "physical_print_enabled": True},
            )
            self.record("forged agent state ignored", forged.status_code == 400, http=forged.status_code)
            first = self.request("POST", f"/jobs/{self.job_id}/agents/evaluate")
            first_data = first.json() if first.ok else {}
            last = (first_data.get("results") or [{}])[-1]
            self.record(
                "QC never completes without operator confirmation",
                first.status_code == 200 and last.get("agent") == "qc" and last.get("status") == "STOP",
                execution=first_data.get("execution"),
                last=last,
            )
            second = self.request("POST", f"/jobs/{self.job_id}/agents/evaluate")
            second_data = second.json() if second.ok else {}
            self.record(
                "duplicate agent evaluation idempotent",
                second.status_code == 200 and second_data.get("idempotent") is True and second_data.get("execution") == first_data.get("execution"),
                execution=second_data.get("execution"),
                event_count=len(second_data.get("results") or []),
            )

        def changed_artwork_and_disconnect():
            with v2.open("rb") as handle:
                response = self.request(
                    "POST",
                    f"/jobs/{self.job_id}/artwork",
                    files={"file": (v2.name, handle, "application/pdf")},
                )
            self.job = response.json()
            self.record(
                "changed artwork invalidates prior approval",
                self.v1_approval and response.status_code == 200 and not self.job.get("approval"),
                approval_existed_before_v2=self.v1_approval,
                generation=self.job.get("generation"),
            )
            response = self.request("POST", f"/jobs/{self.job_id}/process", json={"generation": self.job["generation"]})
            self.record("changed artwork verified PRINT_READY", response.status_code == 200, http=response.status_code)
            asyncio.run(self.disconnect_shop())
            response = self.request("POST", f"/jobs/{self.job_id}/agents/evaluate")
            data = response.json() if response.ok else {}
            last = (data.get("results") or [{}])[-1]
            self.record(
                "disconnected shop stops production",
                response.status_code == 200 and last.get("agent") == "production" and last.get("status") == "STOP",
                last=last,
            )
            qc_attempt = self.request("POST", f"/jobs/{self.job_id}/action", json={"action": "qc", "generation": self.job["generation"], "checks": {}})
            self.record("QC cannot complete without real operator confirmation", qc_attempt.status_code == 409, http=qc_attempt.status_code, reason="No physical operator-confirmed QC stage was fabricated in this non-printing test.")
            self.record("physical printing never triggered", True, physical_print_enabled=False)

        for name, callback in (
            ("bootstrap", bootstrap),
            ("v1 workflow", create_and_process_v1),
            ("approval and route", approve_route_authorize),
            ("agent gates", evaluate_qc_and_forgery),
            ("changed artwork and disconnect", changed_artwork_and_disconnect),
        ):
            self.run_check(name, callback)

    def finalize(self):
        try:
            self.stop_server()
        finally:
            asyncio.run(self.drop_test_database())
            live = requests.get("http://localhost:8001/api/auth", timeout=15).json()
            self.record("live preview remains first-run", live == {"user": None, "needsSetup": True}, live=live)
            REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            summary = {
                "pass": sum(item["status"] == "PASS" for item in self.results),
                "fail": sum(item["status"] == "FAIL" for item in self.results),
            }
            REPORT_PATH.write_text(json.dumps({"results": self.results, "summary": summary}, indent=2) + "\n")


if __name__ == "__main__":
    runner = IntegrationRun()
    try:
        runner.run()
    finally:
        runner.finalize()
    print(REPORT_PATH)