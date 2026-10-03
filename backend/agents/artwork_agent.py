from .base import BaseAgent
from .schemas import AgentName, AgentResult, AgentStatus, JobState

class ArtworkAgent(BaseAgent):
    name = AgentName.ARTWORK

    def run(self, job: JobState) -> AgentResult:
        if not job.artwork.get("original_file_id"):
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.ARTWORK,
                summary="Artwork is required.",
                stop_reasons=["No immutable ORIGINAL artwork file is attached."],
            )
        return AgentResult(
            job_id=job.job_id, agent=self.name, status=AgentStatus.PASS,
            next_agent=AgentName.PREFLIGHT,
            summary="Artwork registered without modifying the original.",
            data={"original_file_id": job.artwork.get("original_file_id")},
        )
