from .base import BaseAgent
from .schemas import AgentName, AgentResult, AgentStatus, JobState

class OrderAgent(BaseAgent):
    name = AgentName.ORDER

    def run(self, job: JobState) -> AgentResult:
        missing = []
        if not job.product:
            missing.append("product")
        if not job.quantity or job.quantity <= 0:
            missing.append("quantity")
        if missing:
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.ORDER,
                summary="Order information is incomplete.",
                stop_reasons=[f"Missing or invalid: {x}" for x in missing],
            )
        return AgentResult(
            job_id=job.job_id, agent=self.name, status=AgentStatus.PASS,
            next_agent=AgentName.ARTWORK,
            summary="Order requirements captured.",
            data={"product": job.product, "quantity": job.quantity, "order_spec": job.order_spec},
        )
