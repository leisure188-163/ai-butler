"""workbuddy credential file location and reading (with transient file-lock retries) (ADR-006 decision 3: fetch and use on demand, never persisted).

The credential file is automatically written by the desktop client after login; the client briefly holds the file
exclusively when refreshing its token — reading at that exact moment hits PermissionError; the lock is transient,
wait two seconds and retry. The five candidate paths have the same semantics as the old repo (PROTOCOL §1);
the WORKBUDDY_AUTH_FILE override takes priority and, when missing, only reports that path without falling back.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

_URL_STATIC = Path("CodeBuddyExtension") / "Data" / "Public" / "auth"
#: Windows/macOS desktop client credential relative paths (appended to %LOCALAPPDATA% and Application Support respectively).
AUTH_BASENAME = _URL_STATIC / "workbuddy-desktop.info"
#: Linux has no desktop client; the entry point is the CodeBuddy CLI, whose credential filename differs and lives in the XDG data directory.
CLI_AUTH_BASENAME = _URL_STATIC / "Tencent-Cloud.coding-copilot.info"


def _candidate_paths() -> list[Path]:
    home = Path.home()
    app_data_local = os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local"
    xdg_data = os.environ.get("XDG_DATA_HOME") or home / ".local" / "share"
    return [
        Path(app_data_local) / AUTH_BASENAME,  # Windows desktop client
        home / "Library" / "Application Support" / AUTH_BASENAME,  # macOS desktop client
        Path(xdg_data) / CLI_AUTH_BASENAME,  # Linux CodeBuddy CLI
        home / ".config" / AUTH_BASENAME,  # Linux (old guess, kept)
        home / ".workbuddy" / "auth" / "workbuddy-desktop.info",  # fallback
    ]


def find_auth_file() -> tuple[Path | None, list[str]]:
    """Probe the credential file by platform; return (path or None, actually-checked candidate list).

    The WORKBUDDY_AUTH_FILE override takes priority (both dock/run go through here); when overridden and missing,
    only that path is reported — no irrelevant suggestions like "reinstall the client".
    """
    override = os.environ.get("WORKBUDDY_AUTH_FILE", "").strip()
    if override:
        path = Path(override).expanduser()
        return (path if path.exists() else None), [str(path)]
    candidates = [str(c) for c in _candidate_paths()]
    for text in candidates:
        if Path(text).exists():
            return Path(text), candidates
    return None, candidates


def load_session(path: Path) -> dict:
    """Read the credential JSON."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_session_retry(
    path: Path, *, attempts: int = 3, delay: float = 2.0, sleep=time.sleep
) -> dict:
    """Retry the credential read on PermissionError (lock is transient); exhausted → raise the original exception as-is."""
    last: PermissionError | None = None
    for index in range(attempts):
        try:
            return load_session(path)
        except PermissionError as exc:
            last = exc
            if index < attempts - 1:
                sleep(delay)
    if last is None:  # theoretically unreachable (the loop always returns or assigns), defensive against -O stripping
        raise RuntimeError("credential read retry produced no result")
    raise last
