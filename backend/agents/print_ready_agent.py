from .base import BaseAgent
from .schemas import AgentName, AgentResult, AgentStatus, JobState

class PrintReadyAgent(BaseAgent):
    name = AgentName.PRINT_READY

    def run(self, job: JobState) -> AgentResult:
        pr = job.print_ready or {}
        if not pr.get("file_id") or not pr.get("checksum"):
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.PRINT_READY,
                summary="PRINT_READY output is missing.",
                stop_reasons=["A generated PRINT_READY file and checksum are required."],
            )
        if pr.get("verified") is not True:
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.PRINT_READY,
                summary="PRINT_READY verification failed or is incomplete.",
                stop_reasons=["Independent verification must PASS before routing."],
                data=pr,
            )
        return AgentResult(
            job_id=job.job_id, agent=self.name, status=AgentStatus.PASS,
            next_agent=AgentName.RECIPE,
            summary="PRINT_READY file independently verified.",
            data={"file_id": pr["file_id"], "checksum": pr["checksum"]},
        )
