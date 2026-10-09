import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPOSITORY_ROOT / "backend" / "build_metadata.json"


def git_commit():
    configured = os.environ.get("GIT_COMMIT", "").strip()
    if configured:
        return configured

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit("Build metadata requires GIT_COMMIT or a Git worktree.") from error


def build_timestamp():
    configured = os.environ.get("BUILD_TIMESTAMP", "").strip()
    if configured:
        return configured
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main():
    metadata = {"commit": git_commit(), "builtAt": build_timestamp()}
    OUTPUT_PATH.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()