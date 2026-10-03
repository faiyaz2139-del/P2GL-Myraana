"""Trusted adapter contract. This module deliberately exposes no HTTP route.
Never accept JobState or evidence from browser request bodies.
"""
from agents.orchestrator import MultiAgentOrchestrator

def evaluate_persisted_job(job_state):
    """Call ONLY with an authenticated, version-fenced database snapshot.
    Results are advisory. Never map PASS to workflow task completion.
    The existing workflow owns file checks, approvals, leases and physical confirmations.
    """
    return MultiAgentOrchestrator().run_until_gate(job_state)

