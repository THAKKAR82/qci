"""CLI-level golden output of the three comparison commands (ADR 0009, section 6).

Written before any R1b change under ``src/``. Each case stores its inputs in a temporary
``QCI_HOME``, invokes the command through the Typer runner, and compares stdout with a file in
``tests/golden/cli/`` byte for byte: ``<case>.json`` for ``--json`` and ``<case>.txt`` for the
text output as it was before the summary existed.

Since the summary (ADR 0009, section 6), the default text output is the summary
(``<case>.summary.txt``), and ``--verbose`` prints the summary, a blank line, then exactly
``<case>.txt``. ``--json`` and ``--json --verbose`` print identical bytes. The ``.json`` and
``.txt`` files are unchanged since they were first written.

- ``compare/``: ``qci compare`` over the runs of the 13 service-level scenarios
  (``tests/test_compare_golden.py``).
- ``snapshot_compare/``: ``qci snapshot compare`` over the CLI cases of
  ``tests/test_snapshot_compare.py`` on the committed ``ibm_fez`` fixture.
- ``compare_run/``: ``qci snapshot compare-run`` over cases of
  ``tests/test_run_snapshot_compare.py``. The seeded ``fake_fez`` run gets a fixed run ID and
  fixed package versions, so the files depend on neither a random ULID nor the installed
  versions. Its footprint still comes from the installed transpiler.

To regenerate deliberately (never in a commit that changes ``src/``):
``QCI_REGENERATE_GOLDEN=1 pytest tests/test_cli_golden.py``.
"""

import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import test_run_snapshot_compare as rsc
import test_snapshot_compare as sc
from qci.adapters.qiskit_ibm.calibration import extract_measurements
from qci.cli.app import app
from qci.domain.run import Run
from qci.domain.snapshot import CalibrationSnapshot, SnapshotCapture
from qci.storage.snapshots import SqliteSnapshotRepository
from qci.storage.sqlite import SqliteRunRepository
from test_compare_golden import SCENARIOS

GOLDEN = Path(__file__).resolve().parent / "golden" / "cli"
FAKE_FEZ_RUN_ID = "01R1B00000000FAKEFEZRVN000"
PINNED_PACKAGES = {
    "qci": "0.0.1",
    "qiskit": "2.5.2",
    "qiskit-aer": "0.17.2",
    "qiskit-ibm-runtime": "0.50.0",
}


def check_golden(path: Path, text: str) -> None:
    if os.environ.get("QCI_REGENERATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == text


def invoke(*args: str) -> str:
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.stdout


NEUTRAL = re.compile(
    r"better|worse|regress|improv|degrad|\bpass|fail|significan|verdict|caus|stale|outdated|"
    r"accurate|realistic|adequate",
    re.IGNORECASE,
)
"""The M1.4b word list (tests/test_run_snapshot_compare.py)."""
MAX_SUMMARY_LINES = 30


def check_outputs(directory: Path, case: str, args: list[str]) -> None:
    """The JSON golden, the summary golden, and the full text golden after the summary."""
    as_json = invoke(*args, "--json")
    check_golden(directory / f"{case}.json", as_json)
    assert invoke(*args, "--json", "--verbose") == as_json
    summary = invoke(*args)
    check_golden(directory / f"{case}.summary.txt", summary)
    assert NEUTRAL.search(summary) is None, NEUTRAL.search(summary)
    assert len(summary.splitlines()) <= MAX_SUMMARY_LINES
    assert summary.endswith("Full detail: rerun with --verbose. Machine-readable: --json.\n")
    verbose = invoke(*args, "--verbose")
    assert verbose.startswith(summary + "\n")
    check_golden(directory / f"{case}.txt", verbose.removeprefix(summary + "\n"))


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "store"
    path.mkdir()
    monkeypatch.setenv("QCI_HOME", str(path))
    yield path


def save_runs(home: Path, *runs: Run) -> None:
    repository = SqliteRunRepository(home / "qci.db")
    try:
        for run in runs:
            repository.save(run)
    finally:
        repository.close()


def save_snapshots(home: Path, *snapshots: CalibrationSnapshot) -> None:
    repository = SqliteSnapshotRepository(home / "qci.db")
    try:
        for snap in snapshots:
            repository.save(
                snap,
                extract_measurements(snap.provider_raw["properties"]),
                SnapshotCapture(
                    capture_id=f"CAP-{snap.snapshot_id}",
                    snapshot_id=snap.snapshot_id,
                    captured_at=snap.captured_at,
                ),
            )
    finally:
        repository.close()


# --- qci compare -------------------------------------------------------------------------------


def compare_args(name: str) -> list[str]:
    _, _, observables = SCENARIOS[name]
    args = ["compare", "BASE", "CAND"]
    for spec in observables:
        args += ["--observable", f"{spec.name}={','.join(spec.bitstrings)}"]
    return args


@pytest.fixture
def compare_store(request: pytest.FixtureRequest, home: Path) -> str:
    name: str = request.param
    baseline, candidate, _ = SCENARIOS[name]
    save_runs(home, baseline(), candidate())
    return name


@pytest.mark.parametrize("compare_store", sorted(SCENARIOS), indirect=True)
def test_compare_cli_matches_golden_files(compare_store: str) -> None:
    check_outputs(GOLDEN / "compare", compare_store, compare_args(compare_store))


# --- qci snapshot compare ----------------------------------------------------------------------

SNAPSHOT_CASES: dict[str, list[str]] = {
    "mismatch_allowed": [
        "FEZ-A",
        "FEZ-B",
        "--footprint-run",
        "FAKEFEZRUN",
        "--allow-footprint-backend-mismatch",
    ],
    "mismatch_not_allowed": ["FEZ-A", "FEZ-B", "--footprint-run", "FAKEFEZRUN"],
    "identical": [
        "FEZ-A",
        "FEZ-A",
        "--footprint-run",
        "FAKEFEZRUN",
        "--allow-footprint-backend-mismatch",
    ],
}


@pytest.fixture
def snapshot_store(home: Path) -> Path:
    """The store of ``test_snapshot_compare.store``."""
    save_snapshots(
        home,
        sc.fez("FEZ-A"),
        sc.derive(sc._ms, lambda p: sc._qubit(p, 1, "T1").update(date=sc.NEW_DATE)),
    )
    save_runs(home, sc.footprint_run(backend="fake_fez", run_id="FAKEFEZRUN"))
    return home


@pytest.mark.parametrize("case", sorted(SNAPSHOT_CASES))
def test_snapshot_compare_cli_matches_golden_files(snapshot_store: Path, case: str) -> None:
    args = ["snapshot", "compare", *SNAPSHOT_CASES[case]]
    check_outputs(GOLDEN / "snapshot_compare", case, args)


# --- qci snapshot compare-run ------------------------------------------------------------------


def pinned_fake_fez_run() -> Run:
    """The session's seeded fake_fez run, with a fixed ID and fixed package versions."""
    data: dict[str, Any] = rsc.fake_fez_run().model_dump(mode="json")
    data["run_id"] = FAKE_FEZ_RUN_ID
    data["provenance"]["environment"]["packages"] = PINNED_PACKAGES
    return Run.model_validate(data)


def _unit_and_error_value(p: dict[str, Any]) -> None:
    """The edit of ``test_text_shows_a_unit_on_every_value_line``."""
    q = rsc.footprint_qubits()[0]
    rsc._qubit(p, q, "T1")["unit"] = "ms"
    rsc._qubit(p, q, "readout_error")["value"] = 1


RUN_SNAPSHOT_CASES: dict[str, Callable[[], CalibrationSnapshot]] = {
    "fixture": lambda: rsc.live(),
    "unit_and_error_value": lambda: rsc.live(_unit_and_error_value, snapshot_id="LIVE-EDITED"),
}


@pytest.fixture
def run_snapshot_store(home: Path) -> Path:
    save_snapshots(home, *(make() for make in RUN_SNAPSHOT_CASES.values()))
    save_runs(home, pinned_fake_fez_run())
    return home


@pytest.mark.parametrize("case", sorted(RUN_SNAPSHOT_CASES))
def test_compare_run_cli_matches_golden_files(run_snapshot_store: Path, case: str) -> None:
    snapshot_id = RUN_SNAPSHOT_CASES[case]().snapshot_id
    args = ["snapshot", "compare-run", FAKE_FEZ_RUN_ID, snapshot_id]
    check_outputs(GOLDEN / "compare_run", case, args)


def test_every_cli_golden_file_has_a_case() -> None:
    expected = {
        "compare": sorted(SCENARIOS),
        "snapshot_compare": sorted(SNAPSHOT_CASES),
        "compare_run": sorted(RUN_SNAPSHOT_CASES),
    }
    for directory, cases in expected.items():
        files = sorted(p.name for p in (GOLDEN / directory).iterdir())
        extensions = ("json", "txt", "summary.txt")
        assert files == sorted(f"{c}.{ext}" for c in cases for ext in extensions)
