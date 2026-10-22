"""Headline for an advisory production review.

A later STOP does not erase checks that already passed.
"""


def review_headline(results):
    results = results or []
    passed = [item for item in results if item.get("status") == "PASS"]
    stopped = next((item for item in results if item.get("status") == "STOP"), None)
    passed_count = len(passed)
    if stopped is None:
        return {
            "title": "Production review complete",
            "detail": f"{passed_count} check{'s' if passed_count != 1 else ''} passed.",
        }
    if passed_count:
        noun = "check" if passed_count == 1 else "checks"
        return {
            "title": f"{passed_count} {noun} passed",
            "detail": f"Stopped at {stopped.get('agent')}: {stopped.get('summary')}",
        }
    return {"title": "Not production-ready", "detail": stopped.get("summary") or "Review stopped."}
