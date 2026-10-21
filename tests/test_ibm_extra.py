"""Commands with and without the ``ibm`` extra (ADR 0009, section 2).

Each command runs in a subprocess. "Without the extra" blocks ``qiskit``, ``qiskit_ibm_runtime``
and ``qiskit_aer`` by setting them to None in ``sys.modules`` before QCI is imported: an import
then raises ``ImportError`` and ``importlib.util.find_spec`` returns None, as for a package that
is not installed. ``HOME`` is a fresh temporary directory, so no saved account is visible.
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from conftest import physical_bell_qasm, physical_run
from qci.adapters.qiskit_ibm.extra import EXTRA_MESSAGE, SDK_MODULES, missing_sdk_modules
from test_cli_golden import FAKE_FEZ_RUN_ID, pinned_fake_fez_run, save_runs, save_snapshots
from test_snapshot_compare import fez

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
BELL = ROOT / "examples" / "bell.py"

LAUNCH = (
    "import sys\n"
    "for name in {blocked!r}:\n"
    "    sys.modules[name] = None\n"
    "from qci.cli.app import main\n"
    "sys.argv = ['qci', *sys.argv[1:]]\n"
    "main()\n"
)


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: str
    stderr: str


def qci(*args: str, home: Path, store: Path, blocked: bool, cwd: Path | None = None) -> Result:
    """Run ``qci ARGS`` in a subprocess with ``QCI_HOME=store`` and ``HOME=home``."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(SRC),
        "HOME": str(home),
        "QCI_HOME": str(store),
    }
    if (systemroot := os.environ.get("SYSTEMROOT")) is not None:
        env["SYSTEMROOT"] = systemroot
    code = LAUNCH.format(blocked=SDK_MODULES if blocked else ())
    out = subprocess.run(
        [sys.executable, "-c", code, *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd or home,
        timeout=300,
    )
    return Result(out.returncode, out.stdout, out.stderr)


@dataclass(frozen=True)
class Prepared:
    home: Path
    store: Path

    @property
    def db(self) -> Path:
        return self.store / "qci.db"


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> Prepared:
    """A store with two runs, the fake_fez run and the ibm_fez snapshot."""
    root = tmp_path_factory.mktemp("extra")
    home, store = root / "home", root / "store"
    home.mkdir()
    store.mkdir()
    qasm = physical_bell_qasm(1, 0)
    save_runs(
        store,
        physical_run("BASE", qasm3=qasm, seed_simulator=7),
        physical_run("CAND", qasm3=qasm, seed_simulator=8),
        pinned_fake_fez_run(),
    )
    save_snapshots(store, fez("FEZ-A"))
    return Prepared(home, store)


CORE_COMMANDS: list[list[str]] = [
    ["runs"],
    ["show", "BASE"],
    ["show", "BASE", "--json"],
    ["compare", "BASE", "CAND"],
    ["compare", "BASE", "CAND", "--json", "--observable", "bell=00,11"],
    ["snapshots"],
    ["snapshot", "show", "FEZ-A"],
    ["snapshot", "compare", "FEZ-A", "FEZ-A", "--footprint-run", "BASE"],
    ["snapshot", "compare-run", FAKE_FEZ_RUN_ID, "FEZ-A"],
    ["snapshot", "compare-run", FAKE_FEZ_RUN_ID, "FEZ-A", "--json"],
    ["where"],
]


def test_the_check_finds_the_installed_sdks() -> None:
    assert missing_sdk_modules() == []


@pytest.mark.parametrize("args", CORE_COMMANDS, ids=" ".join)
def test_core_commands_behave_the_same_without_the_extra(
    prepared: Prepared, args: list[str]
) -> None:
    before = prepared.db.read_bytes()
    with_sdks = qci(*args, home=prepared.home, store=prepared.store, blocked=False)
    without = qci(*args, home=prepared.home, store=prepared.store, blocked=True)
    assert with_sdks.returncode == 0, with_sdks.stderr
    assert (without.returncode, without.stdout) == (with_sdks.returncode, with_sdks.stdout)
    assert EXTRA_MESSAGE not in without.stderr
    assert prepared.db.read_bytes() == before


def test_doctor_differs_only_in_the_extra_and_account_lines(prepared: Prepared) -> None:
    """By design, the two checks that depend on the extra differ; every other line and the
    exit code are the same (ADR 0009, section 4)."""
    before = prepared.db.read_bytes()
    with_sdks = qci("doctor", home=prepared.home, store=prepared.store, blocked=False)
    without = qci("doctor", home=prepared.home, store=prepared.store, blocked=True)
    assert with_sdks.returncode == without.returncode == 0, with_sdks.stdout + without.stdout
    differs = ("ibm extra:", "saved IBM account:")
    a, b = with_sdks.stdout.splitlines(), without.stdout.splitlines()
    assert len(a) == len(b)
    for line_with, line_without in zip(a, b, strict=True):
        if line_with.split(maxsplit=1)[1].startswith(differs):
            continue
        assert line_with == line_without
    assert "ok       ibm extra: qiskit " in with_sdks.stdout
    assert "note     ibm extra: not installed" in without.stdout
    assert "note     saved IBM account: no account file" in with_sdks.stdout
    assert "note     saved IBM account: not checked" in without.stdout
    assert "ok       store: runs healthy, schema version 1, 3 runs" in without.stdout
    assert prepared.db.read_bytes() == before
    assert list(prepared.home.iterdir()) == []


EXTRA_COMMANDS: list[list[str]] = [
    ["run", str(BELL), "--backend", "fake_fez", "--seed", "7"],
    ["snapshot", "capture", "--backend", "ibm_fez"],
    ["snapshot", "backfill", "--backend", "ibm_fez", "--days", "1"],
    ["snapshot", "export", "FEZ-A", "--fixture", "exported.json"],
]


@pytest.mark.parametrize("args", EXTRA_COMMANDS, ids=" ".join)
def test_extra_commands_exit_2_without_the_extra(prepared: Prepared, args: list[str]) -> None:
    before = prepared.db.read_bytes()
    result = qci(*args, home=prepared.home, store=prepared.store, blocked=True)
    assert result.returncode == 2
    assert result.stderr == f"error: {EXTRA_MESSAGE}\n"
    assert result.stdout == ""
    assert prepared.db.read_bytes() == before
    assert not (prepared.home / "exported.json").exists()


@pytest.mark.parametrize("args", EXTRA_COMMANDS, ids=" ".join)
def test_the_check_comes_before_the_store_and_the_workload(tmp_path: Path, args: list[str]) -> None:
    """A damaged store would exit 1 if it were opened, and a missing one would be created."""
    damaged = tmp_path / "damaged"
    damaged.mkdir()
    (damaged / "qci.db").write_bytes(b"not a database")
    absent = tmp_path / "absent"
    for store in (damaged, absent):
        result = qci(*args, home=tmp_path, store=store, blocked=True)
        assert result.returncode == 2, result.stderr
    assert (damaged / "qci.db").read_bytes() == b"not a database"
    assert not absent.exists()
