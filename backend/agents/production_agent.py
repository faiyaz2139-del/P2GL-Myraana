from .base import BaseAgent
from .schemas import AgentName, AgentResult, AgentStatus


def confirmation_matches(evidence, job):
    """Evidence must be loaded by the trusted DB adapter, never from request JSON."""
    return (isinstance(evidence, dict) and evidence.get('confirmed') is True
            and bool(evidence.get('actor_id')) and bool(evidence.get('confirmed_at'))
            and evidence.get('file_id') == job.print_ready.get('file_id')
            and evidence.get('checksum') == job.print_ready.get('checksum')
            and evidence.get('generation') == job.generation)

class ProductionAgent(BaseAgent):
    name = AgentName.PRODUCTION

    def run(self, job):
        reason = None
        if (job.print_ready.get('verified') is not True or not job.approved_file_id
                or not job.approved_checksum
                or job.approved_file_id != job.print_ready.get('file_id')
                or job.approved_checksum != job.print_ready.get('checksum')):
            reason = 'Approve the exact verified PRINT_READY file first.'
        elif not confirmation_matches(job.production.get('proof_approval'), job):
            reason = 'Current-version human proof approval evidence is required.'
        elif not job.human_authorized or not confirmation_matches(job.production.get('authorization'), job):
            reason = 'Human authorization for this exact job version is required.'
        elif not job.connector_ready:
            reason = 'Check the shop connector and destination readiness.'
        elif job.production.get('mode') != 'LIVE_OPERATOR_ASSISTED':
            reason = 'Select a live operator-assisted route. Simulation is separate from live production.'
        elif not confirmation_matches(job.production.get('printed'), job):
            reason = 'Operator must confirm actual printing. Handoff is not proof of printing.'
        elif not confirmation_matches(job.production.get('cut_finished'), job):
            reason = 'Operator must confirm cutting and finishing.'
        if reason:
            return AgentResult(job_id=job.job_id, agent=self.name, status=AgentStatus.STOP,
                               next_agent=self.name, summary=reason, stop_reasons=[reason])
        return AgentResult(job_id=job.job_id, agent=self.name, status=AgentStatus.PASS,
                           next_agent=AgentName.QC, summary='Recorded operator printing and finishing confirmations checked.',
                           data={'mode': 'LIVE_OPERATOR_ASSISTED'})
