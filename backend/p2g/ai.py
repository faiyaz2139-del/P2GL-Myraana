import os
from emergentintegrations.llm.chat import LlmChat, UserMessage


def configured():
    return bool(
        os.environ.get("EMERGENT_LLM_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )


async def assistant_reply(job, message):
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        return None
    system = (
        "You are Print2Go Assistant. Reply briefly from verified job records only. "
        "Never approve proofs, authorize production, confirm printing, or claim a task completed. "
        "Use plain text and do not mention providers or models."
    )
    chat = LlmChat(api_key=key, session_id=f"p2g-{job['id']}", system_message=system)
    chat = chat.with_model("openai", os.environ.get("P2G_MANAGED_MODEL", "gpt-5.6-terra"))
    response = await chat.send_message_with_tools(
        UserMessage(text=f"Verified job: {job}. Operator message: {message}")
    )
    return getattr(response, "content", None) or "I could not prepare a response. Use the job controls."