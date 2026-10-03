from .base import BaseAgent
from .schemas import AgentName, AgentResult, AgentStatus, JobState

class QCAgent(BaseAgent):
    name = AgentName.QC

    def run(self, job: JobState) -> AgentResult:
        qc = job.qc or {}
        if qc.get("result") in ("PASS", "FAIL") and not (qc.get("confirmed_by") and qc.get("confirmed_at")):
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.QC,
                summary="QC result lacks operator confirmation.",
                stop_reasons=["QC must be confirmed by an identified operator (confirmed_by/confirmed_at)."],
            )
        if qc.get("result") == "PASS":
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.PASS,
                next_agent=AgentName.COMPLETE,
                summary="QC passed.",
                data=qc,
            )
        if qc.get("result") == "FAIL":
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.PRODUCTION,
                summary="QC failed; rework and reauthorization required.",
                stop_reasons=[qc.get("reason", "QC failure")],
                data=qc,
            )
        return AgentResult(
            job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
            next_agent=AgentName.QC,
            summary="QC confirmation is required.",
            stop_reasons=["No QC result recorded."],
        )
