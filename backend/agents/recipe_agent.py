from .base import BaseAgent
from .schemas import AgentName, AgentResult, AgentStatus, JobState

class RecipeAgent(BaseAgent):
    name = AgentName.RECIPE

    def run(self, job: JobState) -> AgentResult:
        recipe = job.recipe or {}
        if not recipe.get("version"):
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.RECIPE,
                summary="Versioned product recipe is required.",
                stop_reasons=["No pinned recipe version."],
            )
        if recipe.get("product") and recipe["product"] != job.product:
            return AgentResult(
                job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                next_agent=AgentName.RECIPE,
                summary="Recipe does not match the ordered product.",
                stop_reasons=["Recipe/product mismatch."],
            )
        return AgentResult(
            job_id=job.job_id, agent=self.name, status=AgentStatus.PASS,
            next_agent=AgentName.OPTIMIZATION,
            summary="Versioned production recipe selected.",
            data=recipe,
        )
