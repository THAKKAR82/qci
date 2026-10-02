"""Git provenance. Never raises: every field is None when it cannot be determined."""

import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from qci.domain.provenance import GitProvenance

_TIMEOUT_S = 10


def _git(cwd: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def strip_credentials(url: str) -> str:
    """Remove ``user:password@`` from URL-style remotes. SCP-style remotes are unchanged."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.scheme or "@" not in parts.netloc:
        return url
    host = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def collect_git(directory: Path) -> GitProvenance:
    """Collect git state for the repository containing ``directory``."""
    if _git(directory, "rev-parse", "--is-inside-work-tree") != "true":
        return GitProvenance()
    status = _git(directory, "status", "--porcelain")
    remote = _git(directory, "remote", "get-url", "origin")
    return GitProvenance(
        commit=_git(directory, "rev-parse", "--verify", "-q", "HEAD") or None,
        branch=_git(directory, "symbolic-ref", "--short", "-q", "HEAD") or None,
        dirty=None if status is None else bool(status),
        remote=strip_credentials(remote) if remote else None,
    )
