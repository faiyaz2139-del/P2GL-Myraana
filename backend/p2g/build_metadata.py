import json
from pathlib import Path


BUILD_METADATA_PATH = Path(__file__).resolve().parents[1] / "build_metadata.json"
REQUIRED_FIELDS = ("commit", "builtAt")


def read_build_metadata():
    try:
        raw = json.loads(BUILD_METADATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"commit": "unavailable", "builtAt": "unavailable"}

    if not isinstance(raw, dict):
        return {"commit": "unavailable", "builtAt": "unavailable"}

    if any(not isinstance(raw.get(field), str) or not raw[field].strip() for field in REQUIRED_FIELDS):
        return {"commit": "unavailable", "builtAt": "unavailable"}

    return {field: raw[field].strip() for field in REQUIRED_FIELDS}