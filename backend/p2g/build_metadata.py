"""Commit identity for /api/build-info.

A live value wins: GIT_COMMIT (and the other deploy env names), then
`git rev-parse HEAD`, then a file written by scripts/stamp_build_metadata.py.
The lookup is cached for the process. A committed JSON file is not shipped,
because a stale SHA was being served after the real commit had moved on.
"""
import json
import os
import subprocess
from pathlib import Path


BUILD_METADATA_PATH = Path(__file__).resolve().parents[1] / "build_metadata.json"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMMIT_ENV_NAMES = (
    "GIT_COMMIT",
    "SOURCE_COMMIT",
    "COMMIT_SHA",
    "RENDER_GIT_COMMIT",
    "HEROKU_SLUG_COMMIT",
    "VERCEL_GIT_COMMIT_SHA",
)
_CACHE = None


def _file_metadata(path):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    commit = str(raw.get("commit") or "").strip()
    built_at = str(raw.get("builtAt") or "").strip()
    if not commit or not built_at or commit == "unavailable" or built_at == "unavailable":
        return None
    return {"commit": commit, "builtAt": built_at}


def _git_head():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def resolve_build_metadata(environ=None, path=None, git_commit=None):
    """Return {commit, builtAt}. Pass git_commit to avoid a real git call in tests."""
    environ = os.environ if environ is None else environ
    path = BUILD_METADATA_PATH if path is None else Path(path)
    stamped = _file_metadata(path)
    commit = ""
    for name in COMMIT_ENV_NAMES:
        commit = str(environ.get(name) or "").strip()
        if commit:
            break
    if not commit:
        reader = _git_head if git_commit is None else git_commit
        commit = str(reader() or "").strip()
    built_at = str(environ.get("BUILD_TIMESTAMP") or "").strip()
    if commit:
        if not built_at and stamped and stamped["commit"] == commit:
            built_at = stamped["builtAt"]
        return {"commit": commit, "builtAt": built_at or "runtime"}
    if stamped:
        return dict(stamped)
    return {"commit": "unavailable", "builtAt": "unavailable"}


def read_build_metadata():
    global _CACHE
    if _CACHE is None:
        _CACHE = resolve_build_metadata()
    return dict(_CACHE)


def clear_build_metadata_cache():
    global _CACHE
    _CACHE = None
