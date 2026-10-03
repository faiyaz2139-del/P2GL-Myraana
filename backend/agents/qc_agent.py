from .base import BaseAgent
from .schemas import AgentName, AgentResult, AgentStatus
from .production_agent import ProductionAgent, confirmation_matches

class QCAgent(BaseAgent):
    name = AgentName.QC

    def run(self, job):
        if job.qc.get('result') == 'FAIL':
            reason = 'QC rejected the job. Start rework through the existing workflow and authorize the revised version.'
            return AgentResult(job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                               next_agent=AgentName.PRODUCTION, summary=reason,
                               stop_reasons=[reason], data=job.qc)
        production = ProductionAgent().run(job)
        if production.status == AgentStatus.STOP:
            return AgentResult(job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                               next_agent=AgentName.PRODUCTION, summary=production.summary,
                               stop_reasons=production.stop_reasons)
        if job.qc.get('result') != 'PASS' or not confirmation_matches(job.qc, job):
            reason = 'Operator quality check for this version is required.'
        elif not confirmation_matches(job.production.get('packed'), job):
            reason = 'Confirm packing and collection or delivery readiness.'
        else:
            return AgentResult(job_id=job.job_id, agent=self.name, status=AgentStatus.PASS,
                               next_agent=AgentName.COMPLETE, summary='Recorded production, quality and packing confirmations checked.')
        return AgentResult(job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                           next_agent=self.name, summary=reason, stop_reasons=[reason])
