"""Write commands check the store before writing anything (empty, damaged or other version).

A damaged or other-version store makes ``qci run`` and ``qci snapshot capture`` exit 1 with
the database file byte-identical: no tables, version rows, runs or snapshots are written.
Capture uses the stub client only. Its store check runs before the client is built.
"""

import re
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import make_run
from qci.adapters.qiskit_ibm import live
from qci.cli.app import app
from qci.core.errors import DamagedStoreError, SchemaVersionError
from qci.storage.snapshots import SqliteSnapshotRepository
from qci.storage.sqlite import SqliteRunRepository
from snapshot_stubs import StubFactory
from test_store_read_only import DAMAGE, _damaged_store

ROOT = Path(__file__).resolve().parents[1]
BELL = ROOT / "examples" / "bell.py"

WRONG_VERSION: list[tuple[str, list[str], set[str], str]] = [
    (
        "run_store_other_version",
        ["update schema_meta set value = '99' where key = 'db_schema'"],
        {"runs"},
        "has db_schema 99; this QCI supports 1",
    ),
    (
        "snapshot_store_other_version",
        ["update schema_meta set value = '99' where key = 'snapshot_db_schema'"],
        {"snapshots"},
        "has snapshot_db_schema 99; this QCI supports 1",
    ),
]
SHAPES = DAMAGE + WRONG_VERSION
IDS = [s[0] for s in SHAPES]

RUN = ["run", str(BELL), "--backend", "fake_sherbrooke", "--seed", "7", "--shots", "10"]
CAPTURE = ["snapshot", "capture", "--backend", "ibm_stub"]


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "store"
    monkeypatch.setenv("QCI_HOME", str(path))
    return path


@pytest.fixture
def factory(monkeypatch: pytest.MonkeyPatch) -> StubFactory:
    stub = StubFactory()
    monkeypatch.setattr(live, "create_service", stub)
    return stub


def _rows(db: Path, table: str) -> int | None:
    """Row count, or None if the table does not exist. Opened read-only."""
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        names = {r[0] for r in conn.execute("select name from sqlite_master")}
        if table not in names:
            return None
        count: int = conn.execute(f"select count(*) from {table}").fetchone()[0]
        return count
    finally:
        conn.close()


@pytest.mark.parametrize(("shape", "statements", "damaged", "message"), SHAPES, ids=IDS)
def test_run_checks_the_store_before_writing(
    home: Path, shape: str, statements: list[str], damaged: set[str], message: str
) -> None:
    db = home / "qci.db"
    _damaged_store(db, statements)
    before = db.read_bytes()

    result = CliRunner().invoke(app, RUN)

    if "runs" in damaged:
        assert result.exit_code == 1, result.output
        assert "error: " in result.stderr and message in result.stderr
        assert result.stdout == ""  # no run ID: no run, succeeded or failed, was recorded
        assert db.read_bytes() == before
        assert sorted(p.name for p in home.iterdir()) == ["qci.db"]
    else:
        # Only the snapshot store is damaged: the run store is healthy, so the run is
        # recorded, and the damaged snapshot store is left exactly as it was.
        assert result.exit_code == 0, result.output
        assert _rows(db, "runs") == 2
        for table in ("calibration_snapshots", "snapshot_captures", "calibration_measurements"):
            assert _rows(db, table) == _rows_before(statements, table)


@pytest.mark.parametrize(("shape", "statements", "damaged", "message"), SHAPES, ids=IDS)
def test_capture_checks_the_store_before_the_network_read(
    home: Path,
    factory: StubFactory,
    shape: str,
    statements: list[str],
    damaged: set[str],
    message: str,
) -> None:
    db = home / "qci.db"
    _damaged_store(db, statements)
    before = db.read_bytes()

    result = CliRunner().invoke(app, CAPTURE)

    if "snapshots" in damaged:
        assert result.exit_code == 1, result.output
        assert "error: " in result.stderr and message in result.stderr
        assert factory.calls == []  # no client was built
        assert result.stdout == ""
        assert db.read_bytes() == before
        assert sorted(p.name for p in home.iterdir()) == ["qci.db"]
    else:
        # Only the run store is damaged: the snapshot is recorded, and the run store is left
        # exactly as it was.
        assert result.exit_code == 0, result.output
        assert _rows(db, "calibration_snapshots") == 2
        assert _rows(db, "runs") == 1
        with sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True) as conn:
            keys = {r[0]: r[1] for r in conn.execute("select key, value from schema_meta")}
        assert keys.get("db_schema") == ("99" if "other_version" in shape else None)


def _rows_before(statements: list[str], table: str) -> int | None:
    dropped = {s.split()[-1] for s in statements if s.startswith("drop table")}
    return None if table in dropped else 1


@pytest.mark.parametrize(("shape", "statements", "damaged", "message"), SHAPES, ids=IDS)
def test_writable_repositories_raise_before_writing(
    tmp_path: Path, shape: str, statements: list[str], damaged: set[str], message: str
) -> None:
    db = tmp_path / "qci.db"
    _damaged_store(db, statements)
    before = db.read_bytes()
    error = SchemaVersionError if "other_version" in shape else DamagedStoreError
    for store, repository_class in (
        ("runs", SqliteRunRepository),
        ("snapshots", SqliteSnapshotRepository),
    ):
        if store in damaged:
            with pytest.raises(error, match=re.escape(message)):
                repository_class(db)
            assert db.read_bytes() == before, (shape, store)


def test_empty_stores_are_created_as_before(tmp_path: Path) -> None:
    db = tmp_path / "qci.db"
    runs = SqliteRunRepository(db)
    runs.save(make_run("RUN"))
    runs.close()
    snapshots = SqliteSnapshotRepository(db)  # the snapshot store is empty: tables created
    snapshots.close()
    assert _rows(db, "calibration_snapshots") == 0
    assert _rows(db, "runs") == 1
