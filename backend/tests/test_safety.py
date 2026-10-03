from run_tests import cases
from test_agents import base_job
from agents.schemas import AgentName, AgentStatus
from agents.orchestrator import MultiAgentOrchestrator
from agents.optimization_agent import OptimizationAgent
from agents.production_agent import ProductionAgent
from agents.qc_agent import QCAgent
from agents.preflight_agent import PreflightAgent


def confirmed_job():
    j = base_job()
    evidence = dict(confirmed=True, actor_id='operator-fixture', confirmed_at='2026-10-03T12:00:00Z',
                    file_id=j.approved_file_id, checksum=j.approved_checksum, generation=j.generation)
    j.production = {k:dict(evidence) for k in ('proof_approval', 'authorization', 'printed', 'cut_finished', 'packed')}
    j.production['mode'] = 'LIVE_OPERATOR_ASSISTED'
    j.qc = dict(evidence, result='PASS')
    return j


def test_recorded_physical_confirmations_reach_advisory_complete():
    results = MultiAgentOrchestrator().run_until_gate(confirmed_job())
    assert results[-1].status == AgentStatus.PASS
    assert results[-1].next_agent == AgentName.COMPLETE

@cases('key', ['proof_approval', 'authorization', 'printed', 'cut_finished', 'packed'])
def test_each_missing_confirmation_stops_completion(key):
    j = confirmed_job(); del j.production[key]
    r = MultiAgentOrchestrator().run_step(AgentName.COMPLETE, j)
    assert r.status == AgentStatus.STOP

@cases('field,value', [('file_id','old'), ('checksum','old'), ('generation',99), ('actor_id',''), ('confirmed_at','')])
def test_stale_or_unattributed_authorization_stops(field, value):
    j = confirmed_job(); j.production['authorization'][field] = value
    assert ProductionAgent().run(j).status == AgentStatus.STOP

@cases('mode', ['SIMULATION', 'SIMULATION_OR_OPERATOR_ASSISTED', None])
def test_simulation_never_completes_live_job(mode):
    j = confirmed_job(); j.production['mode'] = mode
    assert QCAgent().run(j).status == AgentStatus.STOP


def test_approval_must_match_print_ready():
    j = confirmed_job(); j.approved_file_id = 'different'
    assert ProductionAgent().run(j).status == AgentStatus.STOP


def test_missing_resources_cannot_win_or_get_high_confidence():
    j = base_job()
    j.optimization['candidate_plans'].append(dict(plan_id='unknown', quality_pass=True, spec_pass=True,
                                               turnaround_pass=True, safety_pass=True))
    r = OptimizationAgent().run(j)
    assert r.status == AgentStatus.STOP
    assert 'selected_plan' not in r.data
    assert len(r.data['incomplete'][0]['unknowns']) == len(OptimizationAgent.WEIGHTS)

@cases('value', [-1, float('nan'), float('inf'), 'unknown', True, {}, []])
def test_invalid_numeric_plan_is_rejected_without_crashing(value):
    j = base_job(); j.optimization['candidate_plans'] = [j.optimization['candidate_plans'][0]]
    j.optimization['candidate_plans'][0]['sheets'] = value
    assert OptimizationAgent().run(j).status == AgentStatus.STOP


def test_risk_outside_probability_range_rejected():
    j = base_job(); j.optimization['candidate_plans'] = [j.optimization['candidate_plans'][0]]
    j.optimization['candidate_plans'][0]['reprint_risk'] = 1.1
    assert OptimizationAgent().run(j).status == AgentStatus.STOP


def test_duplicate_plan_ids_stop():
    j = base_job(); j.optimization['candidate_plans'][1]['plan_id'] = j.optimization['candidate_plans'][0]['plan_id']
    assert OptimizationAgent().run(j).status == AgentStatus.STOP

@cases('bleed', [None, 'yes', 1])
def test_unknown_bleed_stops(bleed):
    j = base_job(); j.preflight['bleed_ok'] = bleed
    assert PreflightAgent().run(j).status == AgentStatus.STOP


def test_arbitrary_bleed_decision_stops():
    j = base_job(); j.preflight.update(bleed_ok=False, bleed_decision='stretch everything')
    assert PreflightAgent().run(j).status == AgentStatus.STOP


def test_trusted_explicit_bleed_decision_can_pass():
    j = base_job(); j.preflight.update(bleed_ok=False, bleed_decision='preserve_design_with_border',
                    decision_actor_id='operator', decision_at='2026-10-03', decision_original_file_id='orig-1')
    assert PreflightAgent().run(j).status == AgentStatus.PASS


def test_example_exposes_no_payload_route():
    import integration_example
    assert not hasattr(integration_example, 'router')
