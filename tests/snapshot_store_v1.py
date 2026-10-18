"""A schema-1 snapshot store, built from frozen DDL, for upcast tests (ADR 0008, section 3).

The DDL below is exactly what ``SqliteSnapshotRepository`` on ``main`` (snapshot DB schema 1)
created, read from ``sqlite_master`` on 2026-10-18. It is frozen here so that tests never
depend on the current code to produce an old store, and never touch a real store.
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from conftest import make_run
from qci.domain.snapshot import CalibrationSnapshot
from qci.services.snapshot_service import snapshot_content_hash
from qci.storage.sqlite import SqliteRunRepository
from snapshot_stubs import CALIBRATED, captured

V1_DDL = (
    'CREATE TABLE schema_meta (\n\t"key" VARCHAR NOT NULL, \n\tvalue VARCHAR NOT NULL, \n\t'
    'PRIMARY KEY ("key")\n)',
    "CREATE TABLE calibration_snapshots (\n\tsnapshot_id VARCHAR NOT NULL, \n\tcontent_hash "
    "VARCHAR NOT NULL, \n\tschema_version INTEGER NOT NULL, \n\tprovider VARCHAR NOT NULL, \n\t"
    "backend_name VARCHAR NOT NULL, \n\tsource VARCHAR NOT NULL, \n\tfirst_captured_at VARCHAR "
    "NOT NULL, \n\tcalibrated_at VARCHAR, \n\trecord_json TEXT NOT NULL, \n\tPRIMARY KEY "
    "(snapshot_id), \n\tUNIQUE (content_hash)\n)",
    "CREATE INDEX ix_snapshots_backend ON calibration_snapshots (provider, backend_name, "
    "first_captured_at)",
    "CREATE TABLE snapshot_captures (\n\tcapture_id VARCHAR NOT NULL, \n\tsnapshot_id VARCHAR "
    "NOT NULL, \n\tcaptured_at VARCHAR NOT NULL, \n\tPRIMARY KEY (capture_id)\n)",
    "CREATE INDEX ix_captures_snapshot ON snapshot_captures (snapshot_id)",
    "CREATE INDEX ix_captures_captured_at ON snapshot_captures (captured_at)",
    "CREATE TABLE calibration_measurements (\n\tsnapshot_id VARCHAR NOT NULL, \n\tseq INTEGER "
    "NOT NULL, \n\tresource_kind VARCHAR NOT NULL, \n\tresource VARCHAR NOT NULL, \n\tparameter "
    "VARCHAR NOT NULL, \n\tvalue_real FLOAT, \n\tvalue_text TEXT, \n\tunit VARCHAR, \n\t"
    "measured_at VARCHAR, \n\tPRIMARY KEY (snapshot_id, seq)\n)",
    "CREATE INDEX ix_measurements_resource ON calibration_measurements (resource, parameter)",
)

V1_SNAPSHOTS = ("01V1SNAPSHOT00000000000000", "01V1SNAPSHOT00000000000001")
V1_CAPTURES = (
    ("01V1CAPTURE000000000000000", V1_SNAPSHOTS[0], CALIBRATED),
    ("01V1CAPTURE000000000000001", V1_SNAPSHOTS[0], CALIBRATED + timedelta(hours=2)),
    ("01V1CAPTURE000000000000002", V1_SNAPSHOTS[1], CALIBRATED + timedelta(days=1)),
)
V1_RUN = "01V1RUN0000000000000000000"


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def build_v1_store(db: Path) -> None:
    """A store with one run, two live snapshots, three captures and their measurements, with
    the snapshot tables at schema 1."""
    runs = SqliteRunRepository(db)
    runs.save(make_run(V1_RUN))
    runs.close()
    conn = sqlite3.connect(db)
    try:
        for statement in V1_DDL[1:]:  # schema_meta exists: the run store created it
            conn.execute(statement)
        conn.execute("insert into schema_meta (key, value) values ('snapshot_db_schema', '1')")
        for index, snapshot_id in enumerate(V1_SNAPSHOTS):
            c = captured(t1=180.0 + index, captured_at=CALIBRATED + timedelta(days=index))
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
            assert snapshot.calibrated_at is not None
            conn.execute(
                "insert into calibration_snapshots values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot_id,
                    snapshot.content_hash,
                    snapshot.schema_version,
                    snapshot.provider,
                    snapshot.backend_name,
                    snapshot.source.value,
                    _utc(snapshot.captured_at),
                    _utc(snapshot.calibrated_at),
                    snapshot.model_dump_json(),
                ),
            )
            for seq, m in enumerate(c.measurements):
                conn.execute(
                    "insert into calibration_measurements values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        snapshot_id,
                        seq,
                        m.resource_kind,
                        m.resource,
                        m.parameter,
                        m.value,
                        None,
                        m.unit,
                        None,
                    ),
                )
        for capture_id, snapshot_id, at in V1_CAPTURES:
            conn.execute(
                "insert into snapshot_captures values (?, ?, ?)",
                (capture_id, snapshot_id, _utc(at)),
            )
        conn.commit()
    finally:
        conn.close()


def dump(db: Path) -> list[str]:
    """Every schema object and row, as SQL, through a read-only connection."""
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()
