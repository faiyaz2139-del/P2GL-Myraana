from __future__ import annotations
from abc import ABC, abstractmethod
from .schemas import AgentResult, JobState

class BaseAgent(ABC):
    name = None

    @abstractmethod
    def run(self, job: JobState) -> AgentResult:
        raise NotImplementedError
