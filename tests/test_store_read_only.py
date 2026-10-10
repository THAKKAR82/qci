"""Read-only commands never write to the store: no file, table or schema row is created.

Covers the run commands (runs, show, compare) and the snapshot commands (snapshots, snapshot
show, export and compare).
"""

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import make_run
from qci.adapters.qiskit_ibm import live
from qci.cli.app import app
from qci.core.errors import (
    ReadOnlyStoreError,
    RunNotFoundError,
    SchemaVersionError,
    SnapshotNotFoundError,
)
from qci.domain.snapshot import CalibrationSnapshot, SnapshotCapture
from qci.services.snapshot_service import snapshot_content_hash
from qci.storage.snapshots import SqliteSnapshotRepository
from qci.storage.sqlite import SqliteRunRepository
from snapshot_stubs import CALIBRATED, captured

# Each read-only snapshot command, with its expected exit code against a store that has no
# snapshot tables.
COMMANDS: list[tuple[list[str], int]] = [
    (["snapshots"], 0),
    (["snapshots", "--backend", "ibm_fez"], 0),
    (["snapshot", "show", "NOPE"], 1),
    (["snapshot", "show", "NOPE", "--json"], 1),
    (["snapshot", "export", "NOPE", "--fixture", "OUT"], 1),
    (["snapshot", "compare", "NOPE", "NOPE2", "--footprint-run", "RUN"], 1),
    (["snapshot", "compare", "NOPE", "NOPE2", "--footprint-run", "RUN", "--json"], 1),
]


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {row[0] for row in conn.execute("select name from sqlite_master")}


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "store"
    monkeypatch.setenv("QCI_HOME", str(path))
    monkeypatch.setattr(live, "load_account_secrets", lambda name: [])
    return path


def _invoke(args: list[str], tmp_path: Path) -> tuple[int, str, str]:
    args = [str(tmp_path / "fixture.json") if a == "OUT" else a for a in args]
    result = CliRunner().invoke(app, args)
    return result.exit_code, result.stdout, result.stderr


@pytest.mark.parametrize(("args", "code"), COMMANDS, ids=lambda v: str(v))
def test_read_only_snapshot_commands_leave_a_runs_only_store_byte_identical(
    home: Path, tmp_path: Path, args: list[str], code: int
) -> None:
    repository = SqliteRunRepository(home / "qci.db")
    repository.save(make_run("RUN"))
    repository.close()
    db = home / "qci.db"
    before = db.read_bytes()

    exit_code, out, err = _invoke(args, tmp_path)

    assert exit_code == code, err
    assert db.read_bytes() == before
    assert not {"calibration_snapshots", "snapshot_captures"} & _tables(db)
    assert sorted(p.name for p in home.iterdir()) == ["qci.db"]
    assert not (tmp_path / "fixture.json").exists()
    if args[0] == "snapshots":
        assert out.strip() == "No snapshots recorded yet."
    else:
        assert "error: no snapshot with id 'NOPE'" in err


@pytest.mark.parametrize(("args", "code"), COMMANDS, ids=lambda v: str(v))
def test_read_only_snapshot_commands_never_create_a_store(
    home: Path, tmp_path: Path, args: list[str], code: int
) -> None:
    exit_code, _, err = _invoke(args, tmp_path)
    assert exit_code == code, err
    assert not home.exists()


def _save_snapshot(db: Path, snapshot_id: str = "SNAP") -> CalibrationSnapshot:
    c = captured()
    snapshot = CalibrationSnapshot(
        snapshot_id=snapshot_id,
        content_hash=snapshot_content_hash(c),
        provider=c.provider,
        backend_name=c.backend_name,
        backend_version=c.backend_version,
        source=c.source,
        captured_at=c.captured_at,
        calibrated_at=c.calibrated_at,
        capture_options=c.capture_options,
        extraction_method=c.extraction_method,
        extraction_method_version=c.extraction_method_version,
        redactions=c.redactions,
        environment=c.environment,
        provider_raw=c.provider_raw,
    )
    repository = SqliteSnapshotRepository(db)
    try:
        stored, _ = repository.save(
            snapshot,
            c.measurements,
            SnapshotCapture(capture_id="CAP", snapshot_id=snapshot_id, captured_at=CALIBRATED),
        )
    finally:
        repository.close()
    return stored


# Each read-only run command, with its expected exit code against a store without runs.
RUN_COMMANDS: list[tuple[list[str], int]] = [
    (["runs"], 0),
    (["show", "NOPE"], 1),
    (["show", "NOPE", "--json"], 1),
    (["compare", "NOPE", "NOPE2"], 1),
    (["compare", "NOPE", "NOPE2", "--json"], 1),
]


@pytest.mark.parametrize(("args", "code"), RUN_COMMANDS, ids=lambda v: str(v))
def test_read_only_run_commands_leave_a_snapshots_only_store_byte_identical(
    home: Path, tmp_path: Path, args: list[str], code: int
) -> None:
    db = home / "qci.db"
    _save_snapshot(db)
    before = db.read_bytes()

    exit_code, out, err = _invoke(args, tmp_path)

    assert exit_code == code, err
    assert db.read_bytes() == before
    assert "runs" not in _tables(db)
    assert sorted(p.name for p in home.iterdir()) == ["qci.db"]
    if args[0] == "runs":
        assert out.strip() == "No runs recorded yet."
    else:
        assert "error: no run with id 'NOPE'" in err


@pytest.mark.parametrize(("args", "code"), RUN_COMMANDS, ids=lambda v: str(v))
def test_read_only_run_commands_never_create_a_store(
    home: Path, tmp_path: Path, args: list[str], code: int
) -> None:
    exit_code, _, err = _invoke(args, tmp_path)
    assert exit_code == code, err
    assert not home.exists()


def test_read_only_run_commands_on_stored_runs_leave_the_store_byte_identical(
    home: Path, tmp_path: Path
) -> None:
    repository = SqliteRunRepository(home / "qci.db")
    repository.save(make_run("RUNA"))
    repository.save(make_run("RUNB"))
    repository.close()
    db = home / "qci.db"
    before = db.read_bytes()
    for args in (
        ["runs"],
        ["show", "RUNA"],
        ["show", "RUNA", "--json"],
        ["compare", "RUNA", "RUNB"],
        ["compare", "RUNA", "RUNB", "--json"],
    ):
        exit_code, out, err = _invoke(args, tmp_path)
        assert exit_code == 0, (args, err)
        assert out
        assert db.read_bytes() == before, args


def test_snapshot_compare_on_a_snapshots_only_store_reports_the_unknown_run(
    home: Path, tmp_path: Path
) -> None:
    db = home / "qci.db"
    snapshot = _save_snapshot(db)
    before = db.read_bytes()
    args = ["snapshot", "compare", snapshot.snapshot_id, snapshot.snapshot_id]
    exit_code, _, err = _invoke([*args, "--footprint-run", "RUN"], tmp_path)
    assert exit_code == 1
    assert "error: no run with id 'RUN'" in err
    assert db.read_bytes() == before
    assert "runs" not in _tables(db)


def test_read_only_repositories_read_existing_data_and_refuse_writes(tmp_path: Path) -> None:
    db = tmp_path / "qci.db"
    snapshot = _save_snapshot(db)
    writable = SqliteRunRepository(db)
    writable.save(make_run("RUN"))
    writable.close()
    before = db.read_bytes()

    snapshots = SqliteSnapshotRepository(db, read_only=True)
    runs = SqliteRunRepository(db, read_only=True)
    try:
        assert snapshots.get(snapshot.snapshot_id) == snapshot
        assert [i.snapshot_id for i in snapshots.list_snapshots()] == [snapshot.snapshot_id]
        assert len(snapshots.measurements(snapshot.snapshot_id)) == 1
        assert runs.get("RUN").run_id == "RUN"
        with pytest.raises(ReadOnlyStoreError):
            runs.save(make_run("OTHER"))
        with pytest.raises(ReadOnlyStoreError):
            snapshots.save(
                snapshot,
                [],
                SnapshotCapture(capture_id="X", snapshot_id="SNAP", captured_at=CALIBRATED),
            )
    finally:
        snapshots.close()
        runs.close()
    assert db.read_bytes() == before


def test_read_only_repositories_on_a_missing_store(tmp_path: Path) -> None:
    db = tmp_path / "absent" / "qci.db"
    snapshots = SqliteSnapshotRepository(db, read_only=True)
    runs = SqliteRunRepository(db, read_only=True)
    assert snapshots.list_snapshots() == [] and runs.list_runs() == []
    assert snapshots.get_by_hash("x") is None and snapshots.captures("x") == []
    with pytest.raises(SnapshotNotFoundError):
        snapshots.get("x")
    with pytest.raises(RunNotFoundError):
        runs.get("x")
    snapshots.close()
    runs.close()
    assert not (tmp_path / "absent").exists()


def test_read_only_open_checks_the_snapshot_schema_version(tmp_path: Path) -> None:
    db = tmp_path / "qci.db"
    _save_snapshot(db)
    with sqlite3.connect(db) as conn:
        conn.execute("update schema_meta set value = '99' where key = 'snapshot_db_schema'")
    before = db.read_bytes()
    with pytest.raises(SchemaVersionError):
        SqliteSnapshotRepository(db, read_only=True)
    assert db.read_bytes() == before
