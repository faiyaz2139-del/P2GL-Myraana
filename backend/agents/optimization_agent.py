from __future__ import annotations
from typing import Any, Dict, List
from .base import BaseAgent
from .schemas import AgentName, AgentResult, AgentStatus, JobState

class OptimizationAgent(BaseAgent):
    """
    Chooses the lowest-resource production plan that still satisfies all hard
    quality/specification constraints. It never invents monetary costs.
    """
    name = AgentName.OPTIMIZATION

    HARD_FIELDS = ("quality_pass", "spec_pass", "turnaround_pass", "safety_pass")

    def _valid(self, option: Dict[str, Any]) -> bool:
        return all(option.get(k) is True for k in self.HARD_FIELDS)

    def _score(self, option: Dict[str, Any]) -> float:
        # Lower is better. Unknown values receive a modest penalty instead of fake costs.
        weights = {
            "sheets": 1.0,
            "waste_sheets": 2.0,
            "clicks": 0.35,
            "machine_minutes": 0.50,
            "operator_minutes": 0.85,
            "setup_count": 5.0,
            "finishing_steps": 3.0,
            "reprint_risk": 20.0,
            "outsourced": 15.0,
            "turnaround_risk": 20.0,
        }
        score = 0.0
        unknowns = 0
        for key, weight in weights.items():
            value = option.get(key)
            if value is None:
                unknowns += 1
                continue
            if isinstance(value, bool):
                value = 1 if value else 0
            score += float(value) * weight
        return score + (unknowns * 2.5)

    def run(self, job: JobState) -> AgentResult:
        if job.print_ready.get("verified") is not True:
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.PRINT_READY,
                summary="Optimization cannot start before PRINT_READY verification.",
                stop_reasons=["PRINT_READY verification is not PASS."],
            )

        options: List[Dict[str, Any]] = list(job.optimization.get("candidate_plans", []))
        if not options:
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.OPTIMIZATION,
                summary="No verified production options are available.",
                stop_reasons=["Machine/stock/capability data is required to create candidate plans."],
            )

        valid, rejected = [], []
        for option in options:
            if self._valid(option):
                enriched = dict(option)
                enriched["efficiency_score"] = round(self._score(option), 3)
                valid.append(enriched)
            else:
                rejected.append({
                    "plan_id": option.get("plan_id", "unknown"),
                    "reason": "Rejected: one or more hard quality/spec/turnaround/safety constraints failed.",
                })

        if not valid:
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.OPTIMIZATION,
                summary="No production method satisfies all hard constraints.",
                stop_reasons=["All candidate production plans were rejected."],
                data={"rejected": rejected},
            )

        valid.sort(key=lambda x: x["efficiency_score"])
        selected = valid[0]
        unknowns = [k for k, v in selected.items() if v is None]
        confidence = "HIGH" if not unknowns else "MEDIUM"

        return AgentResult(
            job_id=job.job_id, agent=self.name, status=AgentStatus.PASS,
            next_agent=AgentName.PRODUCTION,
            summary="Lowest-resource valid production method selected without reducing required quality.",
            data={
                "selected_plan": selected,
                "alternatives_considered": valid[1:],
                "rejected": rejected,
                "confidence": confidence,
                "unknowns": unknowns,
                "money_cost": "UNKNOWN",
            },
        )
