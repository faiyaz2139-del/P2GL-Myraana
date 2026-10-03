from agents.schemas import AgentName, AgentStatus, JobState
from agents.orchestrator import MultiAgentOrchestrator
from agents.optimization_agent import OptimizationAgent

def base_job():
    return JobState(
        job_id="BC-1045",
        product="business_card",
        quantity=500,
        order_spec={"size":"3.5x2", "stock":"14pt", "duplex":True},
        artwork={"original_file_id":"orig-1"},
        preflight={"measured":True, "bleed_ok":True, "unsafe_content":False},
        print_ready={"file_id":"pr-1", "checksum":"abc123", "verified":True},
        recipe={"product":"business_card", "version":"bc-v1"},
        optimization={
            "candidate_plans":[
                {
                    "plan_id":"xerox-12up",
                    "quality_pass":True, "spec_pass":True, "turnaround_pass":True, "safety_pass":True,
                    "sheets":46, "waste_sheets":4, "clicks":92, "machine_minutes":10,
                    "operator_minutes":7, "setup_count":1, "finishing_steps":1,
                    "reprint_risk":0.02, "outsourced":False, "turnaround_risk":0.02
                },
                {
                    "plan_id":"alt-8up",
                    "quality_pass":True, "spec_pass":True, "turnaround_pass":True, "safety_pass":True,
                    "sheets":67, "waste_sheets":6, "clicks":134, "machine_minutes":14,
                    "operator_minutes":14, "setup_count":2, "finishing_steps":2,
                    "reprint_risk":0.03, "outsourced":False, "turnaround_risk":0.05
                }
            ]
        },
        approved_file_id="pr-1",
        approved_checksum="abc123",
        human_authorized=True,
        connector_ready=True,
        physical_print_enabled=False,
        qc={"result":"PASS"}
    )

def test_full_chain_stops_before_unconfirmed_physical_work():
    results = MultiAgentOrchestrator().run_until_gate(base_job())
    assert results[-1].agent == AgentName.PRODUCTION
    assert results[-1].status == AgentStatus.STOP

def test_optimization_selects_lower_resource_valid_plan():
    r = OptimizationAgent().run(base_job())
    assert r.status == AgentStatus.PASS
    assert r.data["selected_plan"]["plan_id"] == "xerox-12up"
    assert r.data["money_cost"] == "UNKNOWN"

def test_optimization_rejects_quality_failure_even_if_cheaper():
    job = base_job()
    job.optimization["candidate_plans"].insert(0, {
        "plan_id":"cheap-bad-quality",
        "quality_pass":False, "spec_pass":True, "turnaround_pass":True, "safety_pass":True,
        "sheets":1, "waste_sheets":0, "clicks":1, "machine_minutes":1,
        "operator_minutes":1, "setup_count":0, "finishing_steps":0,
        "reprint_risk":0, "outsourced":False, "turnaround_risk":0
    })
    r = OptimizationAgent().run(job)
    assert r.data["selected_plan"]["plan_id"] != "cheap-bad-quality"
    assert any(x["plan_id"] == "cheap-bad-quality" for x in r.data["rejected"])

def test_missing_print_ready_verification_stops():
    job = base_job()
    job.print_ready["verified"] = False
    results = MultiAgentOrchestrator().run_until_gate(job)
    assert results[-1].status == AgentStatus.STOP
    assert results[-1].agent == AgentName.PRINT_READY

def test_no_human_authorization_stops_production():
    job = base_job()
    job.human_authorized = False
    results = MultiAgentOrchestrator().run_until_gate(job)
    assert results[-1].agent == AgentName.PRODUCTION
    assert results[-1].status == AgentStatus.STOP

def test_disconnected_connector_stops_production():
    job = base_job()
    job.connector_ready = False
    results = MultiAgentOrchestrator().run_until_gate(job)
    assert results[-1].agent == AgentName.PRODUCTION
    assert results[-1].status == AgentStatus.STOP

def test_qc_failure_routes_to_rework():
    job = base_job()
    job.qc = {"result":"FAIL", "reason":"cutting tolerance"}
    from agents.qc_agent import QCAgent
    results = [QCAgent().run(job)]
    assert results[-1].agent == AgentName.QC
    assert results[-1].status == AgentStatus.STOP
    assert results[-1].next_agent == AgentName.PRODUCTION
