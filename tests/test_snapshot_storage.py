"""Insert-only snapshot store beside the runs table (ADR 0005, section 1)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from conftest import make_run
from qci.core.errors import SchemaVersionError, SnapshotNotFoundError
from qci.domain.snapshot import Measurement
from qci.services.snapshot_service import SnapshotService
from qci.storage.snapshots import SqliteSnapshotRepository
from qci.storage.sqlite import DB_SCHEMA_VERSION, SqliteRunRepository
from snapshot_stubs import CALIBRATED, captured


@pytest.fixture
def snapshot_repo(tmp_path: Path) -> Iterator[SqliteSnapshotRepository]:
    repository = SqliteSnapshotRepository(tmp_path / "qci.db")
    yield repository
    repository.close()


def _rows(db: Path, sql: str) -> list[tuple[object, ...]]:
    engine = create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        rows = [tuple(r) for r in conn.execute(text(sql)).all()]
    engine.dispose()
    return rows


def test_repository_has_no_update_or_delete() -> None:
    names = [n for n in dir(SqliteSnapshotRepository) if not n.startswith("_")]
    assert not [n for n in names if n.startswith(("update", "delete"))]
    assert set(names) == {
        "save",
        "get",
        "get_by_hash",
        "list_snapshots",
        "measurements",
        "captures",
        "close",
    }


def test_existing_run_database_opens_unchanged(tmp_path: Path) -> None:
    db = tmp_path / "qci.db"
    runs = SqliteRunRepository(db)
    run = make_run()
    runs.save(run)
    runs.close()
    runs_ddl = _rows(db, "SELECT sql FROM sqlite_master WHERE tbl_name = 'runs'")
    runs_rows = _rows(db, "SELECT * FROM runs")

    SqliteSnapshotRepository(db).close()

    assert DB_SCHEMA_VERSION == 1
    assert _rows(db, "SELECT sql FROM sqlite_master WHERE tbl_name = 'runs'") == runs_ddl
    assert _rows(db, "SELECT * FROM runs") == runs_rows
    meta = {str(k): str(v) for k, v in _rows(db, "SELECT key, value FROM schema_meta")}
    assert meta == {
        "db_schema": "1",
        "snapshot_db_schema": "1",
    }
    tables = {r[0] for r in _rows(db, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"calibration_snapshots", "snapshot_captures", "calibration_measurements"} <= tables
    reopened = SqliteRunRepository(db)
    assert reopened.get(run.run_id) == run
    reopened.close()


def test_unsupported_snapshot_schema_is_refused(tmp_path: Path) -> None:
    db = tmp_path / "qci.db"
    SqliteSnapshotRepository(db).close()
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(text("UPDATE schema_meta SET value = '9' WHERE key = 'snapshot_db_schema'"))
    engine.dispose()
    with pytest.raises(SchemaVersionError):
        SqliteSnapshotRepository(db)


def test_identical_content_twice_is_one_snapshot_and_two_captures(
    tmp_path: Path, snapshot_repo: SqliteSnapshotRepository
) -> None:
    service = SnapshotService(snapshot_repo)
    first = service.record(captured())
    second = service.record(captured(captured_at=CALIBRATED + timedelta(hours=3)))
    assert first.created and not second.created
    assert second.snapshot.snapshot_id == first.snapshot.snapshot_id
    assert second.capture.snapshot_id == first.snapshot.snapshot_id
    items = snapshot_repo.list_snapshots()
    assert len(items) == 1
    assert items[0].capture_count == 2
    assert items[0].first_captured_at == CALIBRATED
    assert items[0].last_captured_at == CALIBRATED + timedelta(hours=3)
    assert len(snapshot_repo.captures(first.snapshot.snapshot_id)) == 2
    db = tmp_path / "qci.db"
    assert _rows(db, "SELECT COUNT(*) FROM calibration_measurements") == [(1,)]


def test_changed_content_creates_a_second_snapshot(
    snapshot_repo: SqliteSnapshotRepository,
) -> None:
    service = SnapshotService(snapshot_repo)
    first = service.record(captured(t1=182.4))
    second = service.record(captured(t1=170.0, captured_at=CALIBRATED + timedelta(days=1)))
    assert second.created
    assert first.snapshot.content_hash != second.snapshot.content_hash
    assert [i.snapshot_id for i in snapshot_repo.list_snapshots()] == [
        second.snapshot.snapshot_id,
        first.snapshot.snapshot_id,
    ]
    assert snapshot_repo.get_by_hash(first.snapshot.content_hash) == first.snapshot
    assert snapshot_repo.get(second.snapshot.snapshot_id) == second.snapshot


def test_list_filters_by_backend_and_limits(snapshot_repo: SqliteSnapshotRepository) -> None:
    service = SnapshotService(snapshot_repo)
    service.record(captured(t1=1.0))
    service.record(captured(t1=2.0))
    assert len(snapshot_repo.list_snapshots(limit=1)) == 1
    assert len(snapshot_repo.list_snapshots(backend_name="ibm_stub")) == 2
    assert snapshot_repo.list_snapshots(backend_name="ibm_other") == []


def test_unknown_snapshot_raises(snapshot_repo: SqliteSnapshotRepository) -> None:
    with pytest.raises(SnapshotNotFoundError):
        snapshot_repo.get("NOPE")
    assert snapshot_repo.get_by_hash("sha256:none") is None


def test_unavailable_values_are_null_in_both_columns_never_zero(
    tmp_path: Path, snapshot_repo: SqliteSnapshotRepository
) -> None:
    rows = [
        Measurement(resource_kind="qubit", resource="qubit/0", parameter="T1", value=150.0),
        Measurement(resource_kind="qubit", resource="qubit/0", parameter="odd", value=None),
        Measurement(resource_kind="qubit", resource="qubit/0", parameter="flag", value="True"),
    ]
    outcome = SnapshotService(snapshot_repo).record(captured(measurements=rows))
    stored = _rows(
        tmp_path / "qci.db",
        "SELECT parameter, value_real, value_text FROM calibration_measurements ORDER BY seq",
    )
    assert stored == [("T1", 150.0, None), ("odd", None, None), ("flag", None, "True")]
    assert snapshot_repo.measurements(outcome.snapshot.snapshot_id) == rows


def test_non_qubit_resources_round_trip_without_migration(
    tmp_path: Path, snapshot_repo: SqliteSnapshotRepository
) -> None:
    at = datetime(2026, 11, 2, 9, tzinfo=UTC)
    rows = [
        Measurement(
            resource_kind="site",
            resource="site/zone=entangling/row=3/col=7",
            parameter="occupancy_probability",
            value=0.991,
            measured_at=at,
        ),
        Measurement(
            resource_kind="site",
            resource="site/zone=entangling/row=3/col=7",
            parameter="trap_frequency",
            value=92.0,
            unit="kHz",
            measured_at=at,
        ),
        Measurement(
            resource_kind="logical_patch",
            resource="patch/L0",
            parameter="logical_error_per_round",
            value=0.0012,
        ),
        Measurement(
            resource_kind="logical_patch",
            resource="patch/L0",
            parameter="decoder",
            value="pymatching-2.2",
        ),
        Measurement(
            resource_kind="logical_patch", resource="patch/L0", parameter="code_distance", value=7
        ),
    ]
    schema_before = _rows(tmp_path / "qci.db", "SELECT sql FROM sqlite_master ORDER BY name")
    outcome = SnapshotService(snapshot_repo).record(captured(measurements=rows))
    assert snapshot_repo.measurements(outcome.snapshot.snapshot_id) == rows
    assert _rows(tmp_path / "qci.db", "SELECT sql FROM sqlite_master ORDER BY name") == (
        schema_before
    )
