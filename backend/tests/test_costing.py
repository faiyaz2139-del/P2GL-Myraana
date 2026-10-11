from agents.optimization_agent import OptimizationAgent
from p2g.costing import estimate

from test_agents import base_job


def test_cost_estimate_has_auditable_breakdown():
    profile = {
        "material_per_sheet": 0.08,
        "click_per_side": 0.02,
        "setup": 5,
        "finishing_per_unit": 0.01,
        "labour_per_hour": 24,
        "machine_per_hour": 18,
        "waste_percent": 5,
        "outsourcing": 0,
        "sell_price_per_unit": 0.25,
    }
    result = estimate(base_job().optimization["candidate_plans"][0], profile, 500)
    assert result["total"] > 0
    assert result["profit_margin_percent"] is not None
    assert set(result["breakdown"]) == {
        "paper_material",
        "expected_waste",
        "ink_toner_clicks",
        "setup",
        "finishing_binding",
        "labour",
        "machine_running",
        "outsourcing",
    }


def test_cheapest_eligible_configured_cost_plan_wins():
    job = base_job()
    profile = {
        "material_per_sheet": 0.08,
        "click_per_side": 0.02,
        "setup": 5,
        "finishing_per_unit": 0.01,
        "labour_per_hour": 24,
        "machine_per_hour": 18,
        "waste_percent": 5,
        "outsourcing": 0,
        "sell_price_per_unit": 0.25,
    }
    for plan in job.optimization["candidate_plans"]:
        plan["cost_profile"] = profile
    result = OptimizationAgent().run(job)
    assert result.status.value == "PASS"
    assert result.data["selected_plan"]["cost_estimate"]["total"] > 0

def test_mixed_priced_and_unpriced_plans_do_not_claim_cheapest():
    job = base_job()
    profile = {
        "material_per_sheet": 0.08,
        "click_per_side": 0.02,
        "setup": 5,
        "finishing_per_unit": 0.01,
        "labour_per_hour": 24,
        "machine_per_hour": 18,
        "waste_percent": 5,
        "outsourcing": 0,
        "sell_price_per_unit": 0.25,
    }
    plans = job.optimization["candidate_plans"]
    assert len(plans) >= 2
    plans[0]["cost_profile"] = profile
    plans[1].pop("cost_profile", None)
    result = OptimizationAgent().run(job)
    assert result.status.value == "STOP"
    assert result.data["money_cost"] == "UNKNOWN"
    assert plans[1]["plan_id"] in result.data["unpriced_plans"]
