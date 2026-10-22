"""Customer-facing job status. Proof approval must not keep saying it is waiting."""


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
