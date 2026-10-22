"""Customer-facing job status. Proof approval must not keep saying it is waiting."""


def reset_result(task, reason):
    """Keep the initial text on a step the job has not reached."""
    reached = task.get("status") != "Pending" or task.get("result") != "Not started."
    return reason if reached else "Not started."


def status_label(job):
    state = job.get("state")
    if state == "paused":
        return "Paused"
    if state == "complete":
        return "Completed"
    if state == "cancelled":
        return "Cancelled"
    task = next(
        (
            item
            for item in job.get("tasks") or []
            if item.get("status") not in {"Completed", "Cancelled"}
        ),
        None,
    )
    if not task:
        return "Completed"
    if job.get("approval") and task.get("title") == "Choose production route":
        return "Proof approved"
    return task.get("status") or "Pending"
