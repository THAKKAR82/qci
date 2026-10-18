"""Backfilled calibration data can never be committed (ADR 0008 section 6, D29).

Backfilled data stays in the user's local store. Three safeguards: ``qci snapshot export``
refuses historical lookup data (tested in ``test_backfill.py``), ``.gitignore`` ignores store
files and their backups, and no tracked JSON file holds a historical lookup.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MARKER = "historical_lookup"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False
    )


def _in_git_checkout() -> bool:
    return shutil.which("git") is not None and _git("rev-parse", "--git-dir").returncode == 0


needs_git = pytest.mark.skipif(not _in_git_checkout(), reason="not a git checkout")

IGNORED = [
    "qci.db",
    "qci.db-journal",
    "qci.db-wal",
    "qci.db-shm",
    "anywhere/below/qci.db",
    "backup-2026-10-18.db",
    "store.sqlite",
    "store.sqlite3",
    ".qci/qci.db",
    ".qci-live/qci.db",
    "qci-backups/qci-live-20261018T000000Z.db",
    "tests/fixtures/snapshots/qci.db",
]


@needs_git
@pytest.mark.parametrize("path", IGNORED)
def test_store_files_and_backups_are_ignored(path: str) -> None:
    result = _git("check-ignore", "--no-index", "-q", path)
    assert result.returncode == 0, f"{path} is not ignored by .gitignore"


@needs_git
def test_no_store_file_is_tracked() -> None:
    tracked = _git("ls-files").stdout.splitlines()
    suffixes = (".db", ".db-journal", ".db-wal", ".db-shm", ".sqlite", ".sqlite3")
    assert [p for p in tracked if p.endswith(suffixes)] == []


def _json_files() -> list[Path]:
    if _in_git_checkout():
        listed = _git("ls-files", "-z", "--", "*.json").stdout.split("\0")
        return [ROOT / p for p in listed if p]
    return [
        p
        for top in ("tests", "docs", "experiments", "examples")
        for p in sorted((ROOT / top).rglob("*.json"))
    ]


def test_no_tracked_json_file_holds_a_historical_lookup() -> None:
    files = _json_files()
    assert ROOT / "tests" / "fixtures" / "snapshots" / "ibm_fez.json" in files
    holding = [
        str(p.relative_to(ROOT)) for p in files if p.is_file() and MARKER in p.read_text("utf-8")
    ]
    assert holding == []


def test_the_committed_ibm_fez_fixture_validates_unchanged_as_a_live_capture() -> None:
    from qci.domain.backend import SnapshotSource
    from qci.domain.snapshot import SnapshotFixture

    path = ROOT / "tests" / "fixtures" / "snapshots" / "ibm_fez.json"
    fixture = SnapshotFixture.model_validate_json(path.read_text("utf-8"))
    assert fixture.fixture_origin == "live_capture"
    assert fixture.snapshot.source is SnapshotSource.LIVE_CALIBRATION
    assert fixture.captures
    assert all(c.method == "live_capture" and c.requested_before is None for c in fixture.captures)
