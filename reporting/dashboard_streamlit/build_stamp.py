"""When this deployment's code was last changed.

Streamlit Cloud redeploys on every push, so "is my fix live yet?" is a real
question with no visible answer in the app. This reads the HEAD commit's own
timestamp - the time the code was written, not the time the container
happened to start - so a stale deploy is visibly stale.

Falls back to the newest source file's mtime where no git metadata is present
(a zip deploy, a container that dropped .git), and to None when even that
fails, so a missing stamp never breaks the page.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_KST = timezone(timedelta(hours=9))


def _git_commit_time() -> tuple[datetime, str] | None:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI %h"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    stamp, _, short_sha = result.stdout.strip().partition(" ")
    try:
        return datetime.fromisoformat(stamp), short_sha.strip()
    except ValueError:
        return None


def _newest_source_mtime() -> tuple[datetime, str] | None:
    newest = 0.0
    for path in _PROJECT_ROOT.rglob("*.py"):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    if not newest:
        return None
    return datetime.fromtimestamp(newest, timezone.utc), ""


@lru_cache(maxsize=1)
def build_stamp() -> tuple[str, str] | None:
    """(local-time label, commit sha) for the code currently running."""
    resolved = _git_commit_time() or _newest_source_mtime()
    if resolved is None:
        return None
    moment, short_sha = resolved
    return moment.astimezone(_KST).strftime("%Y-%m-%d %H:%M"), short_sha


def build_stamp_html() -> str:
    """Fixed bottom-right stamp. Returns "" when the time can't be resolved -
    an empty corner is better than a made-up timestamp."""
    stamp = build_stamp()
    if stamp is None:
        return ""
    label, short_sha = stamp
    suffix = f" · {short_sha}" if short_sha else ""
    return (
        f'<div class="ts-build-stamp" title="이 앱이 실행 중인 코드의 최종 수정 시각 (KST)">'
        f"최종 수정 {label}{suffix}</div>"
    )
