"""Snapshot store schema 1 -> 2 (ADR 0008, section 3). Never against a real store.

Every test builds a schema-1 store from frozen DDL in a temporary directory, copies it, and
works on the copy, so the original stays as the reference.
"""

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qci.cli.app import app
from qci.core.errors import DamagedStoreError, SchemaVersionError
from qci.domain.snapshot import SnapshotCapture
from qci.storage import snapshots as snapshot_storage
from qci.storage.snapshots import SqliteSnapshotRepository
from snapshot_store_v1 import V1_CAPTURES, V1_SNAPSHOTS, build_v1_store, dump
from snapshot_stubs import captured

LOOKUP_LINES = ("snapshot_lookups", "ix_lookups_requested_before")
VERSION_ROW = "INSERT INTO \"schema_meta\" VALUES('snapshot_db_schema','{}');"


@pytest.fixture
def v1(tmp_path: Path) -> tuple[Path, Path]:
    """(original, copy) of one schema-1 store."""
    original = tmp_path / "original" / "qci.db"
    original.parent.mkdir()
    build_v1_store(original)
    copy = tmp_path / "copy" / "qci.db"
    copy.parent.mkdir()
    shutil.copy2(original, copy)
    return original, copy


def _version(db: Path) -> str:
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "select value from schema_meta where key = 'snapshot_db_schema'"
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


def test_the_frozen_store_is_schema_1(v1: tuple[Path, Path]) -> None:
    original, _ = v1
    assert _version(original) == "1"
    assert VERSION_ROW.format(1) in dump(original)
    assert not [line for line in dump(original) if "snapshot_lookups" in line]


def test_read_only_open_reads_every_capture_as_live_and_writes_nothing(
    v1: tuple[Path, Path],
) -> None:
    _, db = v1
    before = db.read_bytes()
    repository = SqliteSnapshotRepository(db, read_only=True)
    try:
        captures = [c for s in V1_SNAPSHOTS for c in repository.captures(s)]
        assert [c.capture_id for c in captures] == [c[0] for c in V1_CAPTURES]
        assert all(c.method == "live_capture" and c.requested_before is None for c in captures)
        assert repository.lookup_times("qiskit_ibm", "ibm_stub") == set()
        assert len(repository.list_snapshots()) == 2
    finally:
        repository.close()
    assert db.read_bytes() == before
    assert _version(db) == "1"


def test_read_only_commands_on_a_schema_1_store_write_nothing(
    v1: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, db = v1
    monkeypatch.setenv("QCI_HOME", str(db.parent))
    before = db.read_bytes()
    runner = CliRunner()
    shown = runner.invoke(app, ["snapshot", "show", V1_SNAPSHOTS[0]])
    assert shown.exit_code == 0, shown.stderr
    assert "historical lookups" not in shown.stdout
    assert "captures:       2" in shown.stdout
    assert runner.invoke(app, ["snapshots"]).exit_code == 0
    assert db.read_bytes() == before


def test_writable_open_upcasts_and_changes_nothing_else(v1: tuple[Path, Path]) -> None:
    original, db = v1
    SqliteSnapshotRepository(db).close()

    assert _version(db) == "2"
    assert _version(original) == "1"
    before, after = dump(original), dump(db)
    added = [line for line in after if line not in before]
    removed = [line for line in before if line not in after]
    assert removed == [VERSION_ROW.format(1)]
    assert VERSION_ROW.format(2) in added
    others = [line for line in added if line != VERSION_ROW.format(2)]
    assert others and all(any(name in line for name in LOOKUP_LINES) for line in others)
    assert not [line for line in others if line.startswith("INSERT")]  # the table is empty
    # Every existing row and schema object is byte-identical, in the same order.
    assert [line for line in after if line not in added] == [
        line for line in before if line not in removed
    ]


def test_upcast_store_reads_old_captures_as_live_and_accepts_lookups(
    v1: tuple[Path, Path],
) -> None:
    _, db = v1
    repository = SqliteSnapshotRepository(db)
    try:
        old = repository.captures(V1_SNAPSHOTS[0])
        assert [c.method for c in old] == ["live_capture", "live_capture"]
        at = datetime(2026, 10, 7, tzinfo=UTC)
        snapshot = repository.get(V1_SNAPSHOTS[1])
        repository.save(
            snapshot,
            captured().measurements,
            SnapshotCapture(
                capture_id="01LOOKUP000000000000000000",
                snapshot_id=snapshot.snapshot_id,
                captured_at=datetime(2026, 10, 18, tzinfo=UTC),
                method="historical_lookup",
                requested_before=at,
            ),
        )
        assert repository.lookup_times("qiskit_ibm", "ibm_stub") == {at}
        assert repository.captures(V1_SNAPSHOTS[0]) == old
    finally:
        repository.close()


def test_a_failed_upcast_leaves_the_store_as_it_was(
    v1: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    original, db = v1
    create = snapshot_storage.lookups_table.create

    def fail(*args: Any, **kwargs: Any) -> None:
        create(*args, **kwargs)  # the DDL runs, then the transaction fails
        raise RuntimeError("simulated failure while creating snapshot_lookups")

    monkeypatch.setattr(snapshot_storage.lookups_table, "create", fail)
    with pytest.raises(RuntimeError, match="simulated failure"):
        SqliteSnapshotRepository(db)
    assert dump(db) == dump(original)
    assert _version(db) == "1"


def _sql(db: Path, *statements: str) -> None:
    conn = sqlite3.connect(db)
    try:
        for statement in statements:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()


TABLE_SETS: list[tuple[str, list[str], str | None]] = [
    ("v1_tables_v1_version", [], None),
    (
        "v2_tables_v2_version",
        [
            "create table snapshot_lookups (capture_id varchar primary key, "
            "requested_before varchar not null, method_version varchar not null)",
            "update schema_meta set value = '2' where key = 'snapshot_db_schema'",
        ],
        None,
    ),
    (
        "v1_tables_v2_version",
        ["update schema_meta set value = '2' where key = 'snapshot_db_schema'"],
        "snapshot_db_schema 2 but tables snapshot_lookups missing",
    ),
    (
        "v2_tables_v1_version",
        [
            "create table snapshot_lookups (capture_id varchar primary key, "
            "requested_before varchar not null, method_version varchar not null)"
        ],
        "snapshot_db_schema 1 but tables snapshot_lookups present",
    ),
    (
        "v2_tables_without_captures",
        [
            "create table snapshot_lookups (capture_id varchar primary key, "
            "requested_before varchar not null, method_version varchar not null)",
            "update schema_meta set value = '2' where key = 'snapshot_db_schema'",
            "drop table snapshot_captures",
        ],
        "tables calibration_measurements, calibration_snapshots exist but snapshot_captures "
        "is missing",
    ),
    (
        "only_lookups_left",
        [
            "create table snapshot_lookups (capture_id varchar primary key, "
            "requested_before varchar not null, method_version varchar not null)",
            "drop table snapshot_captures",
            "drop table calibration_measurements",
            "drop table calibration_snapshots",
        ],
        "tables snapshot_lookups exist but calibration_measurements, calibration_snapshots, "
        "snapshot_captures are missing",
    ),
]


@pytest.mark.parametrize(
    ("shape", "statements", "damage"), TABLE_SETS, ids=[s[0] for s in TABLE_SETS]
)
def test_only_the_version_1_and_version_2_table_sets_are_accepted(
    v1: tuple[Path, Path], shape: str, statements: list[str], damage: str | None
) -> None:
    _, db = v1
    _sql(db, *statements)
    before = db.read_bytes()
    for read_only in (True, False):
        if damage is None:
            SqliteSnapshotRepository(db, read_only=read_only).close()
        else:
            with pytest.raises(DamagedStoreError, match=damage):
                SqliteSnapshotRepository(db, read_only=read_only)
            assert db.read_bytes() == before, (shape, read_only)


def test_another_version_names_both_supported_versions(v1: tuple[Path, Path]) -> None:
    _, db = v1
    _sql(db, "update schema_meta set value = '3' where key = 'snapshot_db_schema'")
    before = db.read_bytes()
    for read_only in (True, False):
        with pytest.raises(SchemaVersionError, match="this QCI supports 1 and 2"):
            SqliteSnapshotRepository(db, read_only=read_only)
    assert db.read_bytes() == before


def test_a_new_store_is_created_at_version_2(tmp_path: Path) -> None:
    db = tmp_path / "qci.db"
    SqliteSnapshotRepository(db).close()
    assert _version(db) == "2"
    SqliteSnapshotRepository(db, read_only=True).close()


def test_listing_and_show_output_of_an_existing_store_is_unchanged_by_the_upcast(
    v1: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, db = v1
    monkeypatch.setenv("QCI_HOME", str(db.parent))
    runner = CliRunner()
    commands = [["snapshots"], *[["snapshot", "show", s] for s in V1_SNAPSHOTS]]
    before = [runner.invoke(app, args).stdout for args in commands]
    SqliteSnapshotRepository(db).close()
    assert _version(db) == "2"
    assert [runner.invoke(app, args).stdout for args in commands] == before
    assert before[0].count("\n") == 3  # header and two snapshots
