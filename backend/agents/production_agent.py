from .base import BaseAgent
from .schemas import AgentName, AgentResult, AgentStatus, JobState

class ProductionAgent(BaseAgent):
    name = AgentName.PRODUCTION

    def run(self, job: JobState) -> AgentResult:
        # Critical safety boundary: selection of a production plan is not authorization to print.
        if not job.approved_file_id or not job.approved_checksum:
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.PRODUCTION,
                summary="Exact-file human proof approval is required.",
                stop_reasons=["No approved production file/checksum."],
            )
        pr = job.print_ready or {}
        if job.approved_file_id != pr.get("file_id") or job.approved_checksum != pr.get("checksum"):
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.PRODUCTION,
                summary="Proof approval does not match the current PRINT_READY file; re-approval required.",
                stop_reasons=["Approved file/checksum differs from current verified PRINT_READY (artwork changed)."],
            )
        if not job.human_authorized:
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.PRODUCTION,
                summary="Human production authorization required.",
                stop_reasons=["Production authorization is not present."],
            )
        if not job.connector_ready:
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.PRODUCTION,
                summary="Shop connector is not ready.",
                stop_reasons=["Disconnected or stale connector."],
            )
        # Physical print remains disabled in this patch by design.
        if not job.physical_print_enabled:
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.PASS,
                next_agent=AgentName.QC,
                summary="Production plan authorized for simulated/operator-assisted handoff only; physical print remains disabled.",
                data={"mode": "SIMULATION_OR_OPERATOR_ASSISTED"},
            )
        return AgentResult(
            job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
            next_agent=AgentName.PRODUCTION,
            summary="Physical printing is intentionally not enabled by this patch.",
            stop_reasons=["A separately verified printer integration is required."],
        )
