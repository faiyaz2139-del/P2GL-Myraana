from .schemas import AgentName, JobState

class ManagerAgent:
    """Deterministic router. AI may recommend, but this router owns transitions."""
    ORDER = [
        AgentName.ORDER,
        AgentName.ARTWORK,
        AgentName.PREFLIGHT,
        AgentName.PRINT_READY,
        AgentName.RECIPE,
        AgentName.OPTIMIZATION,
        AgentName.PRODUCTION,
        AgentName.QC,
    ]

    def first_agent(self, job: JobState) -> AgentName:
        return AgentName.ORDER
