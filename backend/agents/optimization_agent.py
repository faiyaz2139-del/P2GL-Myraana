"""Advisory resource ranking. Monetary cost remains unknown without cost sheets."""
import math
from .base import BaseAgent
from .schemas import AgentName, AgentResult, AgentStatus
from p2g.costing import estimate

class OptimizationAgent(BaseAgent):
    name = AgentName.OPTIMIZATION
    HARD_FIELDS = ('quality_pass', 'spec_pass', 'turnaround_pass', 'safety_pass')
    WEIGHTS = dict(sheets=1., waste_sheets=2., clicks=.35, machine_minutes=.5,
                   operator_minutes=.85, setup_count=5., finishing_steps=3.,
                   reprint_risk=20., outsourced=15., turnaround_risk=20.)

    def run(self, job):
        def stop(summary, **data):
            return AgentResult(job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                               next_agent=self.name, summary=summary,
                               stop_reasons=[summary], data=data)
        if job.print_ready.get('verified') is not True:
            return stop('Verify PRINT_READY before comparing production plans.')
        options = job.optimization.get('candidate_plans', [])
        if not isinstance(options, list) or not options:
            return stop('Configure verified machine, stock and capability data first.')
        valid, rejected, incomplete, seen = [], [], [], set()
        for option in options:
            if not isinstance(option, dict):
                return stop('Invalid production plan data.')
            plan_id = option.get('plan_id')
            if not isinstance(plan_id, str) or not plan_id.strip() or plan_id in seen:
                return stop('Production plans require unique identities.')
            seen.add(plan_id)
            if not all(option.get(k) is True for k in self.HARD_FIELDS):
                rejected.append(dict(plan_id=plan_id, reason='Hard quality, specification, turnaround or safety check failed.'))
                continue
            unknowns = [k for k in self.WEIGHTS if option.get(k) is None]
            if unknowns:
                incomplete.append(dict(plan_id=plan_id, unknowns=unknowns))
                continue
            invalid = []
            for key in self.WEIGHTS:
                value = option[key]
                if key == 'outsourced':
                    ok = type(value) is bool
                else:
                    ok = (type(value) in (int, float) and math.isfinite(value) and value >= 0)
                    if key in ('reprint_risk', 'turnaround_risk'):
                        ok = ok and value <= 1
                if not ok: invalid.append(key)
            if invalid:
                rejected.append(dict(plan_id=plan_id, reason='Invalid measurements.', invalid=invalid))
                continue
            score = sum(float(option[k]) * w for k, w in self.WEIGHTS.items())
            if not math.isfinite(score):
                rejected.append(dict(plan_id=plan_id, reason='Resource score exceeds a finite range.'))
                continue
            candidate = dict(option, efficiency_score=round(score, 3))
            profile = option.get("cost_profile")
            if profile:
                try:
                    candidate["cost_estimate"] = estimate(option, profile, job.quantity)
                except (KeyError, TypeError, ValueError):
                    rejected.append(dict(plan_id=plan_id, reason="Cost profile is incomplete or invalid."))
                    continue
            valid.append(candidate)
        # Missing data cannot beat measured plans or be concealed as high confidence.
        if incomplete:
            return stop('Measure missing plan resources before comparing options.', incomplete=incomplete,
                        rejected=rejected, money_cost='UNKNOWN')
        if not valid:
            return stop('No measured production plan passes all constraints.', rejected=rejected)
        priced = [item for item in valid if item.get("cost_estimate")]
        if priced and len(priced) != len(valid):
            return stop("Some eligible production plans lack verified cost profiles; no cheapest monetary route can be claimed.",
                        unpriced_plans=[item["plan_id"] for item in valid if not item.get("cost_estimate")],
                        rejected=rejected, money_cost="UNKNOWN")
        if priced:
            priced.sort(key=lambda item: (item["cost_estimate"]["total"], item["plan_id"]))
            return AgentResult(job_id=job.job_id, agent=self.name, status=AgentStatus.PASS,
                               next_agent=AgentName.PRODUCTION,
                               summary="Measured cost comparison completed. Operator must confirm the production route.",
                               data=dict(selected_plan=priced[0], alternatives_considered=priced[1:], rejected=rejected,
                                         method="Auditable configured cost inputs; quality constraints applied first.",
                                         confidence="CONFIGURED_COST_INPUTS", unknowns=[]))
        valid.sort(key=lambda p: (p['efficiency_score'], p['plan_id']))
        return AgentResult(job_id=job.job_id, agent=self.name, status=AgentStatus.PASS,
                           next_agent=AgentName.PRODUCTION,
                           summary='Resource estimate compared. Operator must confirm the production route.',
                           data=dict(selected_plan=valid[0], alternatives_considered=valid[1:], rejected=rejected,
                                     method='Weighted resource heuristic; not a monetary cost quote.',
                                     confidence='MEASURED_INPUTS_HEURISTIC', unknowns=['cost_profile'],
                                     money_cost='UNKNOWN'))
