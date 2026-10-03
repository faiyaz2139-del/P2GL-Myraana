from __future__ import annotations
from typing import Dict, List
from .schemas import AgentName, AgentResult, AgentStatus, JobState
from .order_agent import OrderAgent
from .artwork_agent import ArtworkAgent
from .preflight_agent import PreflightAgent
from .print_ready_agent import PrintReadyAgent
from .recipe_agent import RecipeAgent
from .optimization_agent import OptimizationAgent
from .production_agent import ProductionAgent
from .qc_agent import QCAgent

class MultiAgentOrchestrator:
    def __init__(self):
        self.agents = {
            AgentName.ORDER: OrderAgent(),
            AgentName.ARTWORK: ArtworkAgent(),
            AgentName.PREFLIGHT: PreflightAgent(),
            AgentName.PRINT_READY: PrintReadyAgent(),
            AgentName.RECIPE: RecipeAgent(),
            AgentName.OPTIMIZATION: OptimizationAgent(),
            AgentName.PRODUCTION: ProductionAgent(),
            AgentName.QC: QCAgent(),
        }

    def run_step(self, agent_name: AgentName, job: JobState) -> AgentResult:
        if agent_name == AgentName.COMPLETE:
            return self.agents[AgentName.QC].run(job)
        return self.agents[agent_name].run(job)

    def run_until_gate(self, job: JobState, start: AgentName = AgentName.ORDER, max_steps: int = 20) -> List[AgentResult]:
        results: List[AgentResult] = []
        current = start
        for _ in range(max_steps):
            if current == AgentName.COMPLETE:
                break
            result = self.run_step(current, job)
            results.append(result)
            if result.status == AgentStatus.STOP:
                break
            current = result.next_agent
        return results
