from .base import BaseAgent
from .schemas import AgentName, AgentResult, AgentStatus, JobState

class PreflightAgent(BaseAgent):
    name = AgentName.PREFLIGHT

    def run(self, job: JobState) -> AgentResult:
        pf = job.preflight or {}
        if pf.get("unsafe_content") is True:
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.PREFLIGHT,
                summary="Preflight stopped the job.",
                stop_reasons=["Artwork violates a hard safety/quality rule."],
                data=pf,
            )
        if pf.get("measured") is not True:
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.PREFLIGHT,
                summary="Measured preflight has not completed.",
                stop_reasons=["Preflight evidence is missing."],
            )
        if pf.get("bleed_ok") is False and not pf.get("bleed_decision"):
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.PREFLIGHT,
                summary="Explicit bleed decision required.",
                stop_reasons=["Missing bleed decision."],
                data=pf,
            )
        warnings = []
        if pf.get("dpi_warning"):
            warnings.append(str(pf["dpi_warning"]))
        status = AgentStatus.WARNING if warnings else AgentStatus.PASS
        return AgentResult(
            job_id=job.job_id, agent=self.name, status=status,
            next_agent=AgentName.PRINT_READY,
            summary="Measured preflight completed.",
            warnings=warnings,
            data=pf,
        )
