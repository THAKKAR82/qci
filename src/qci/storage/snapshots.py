"""Insert-only SQLite calibration snapshot repository (ADR 0005, section 1).

Snapshot tables live in the same file as runs but are owned here. They record their own
schema version under ``snapshot_db_schema``, so the runs table and ``DB_SCHEMA_VERSION`` are
untouched. There is deliberately no update or delete.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    Connection,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    insert,
    select,
)

from qci.core.errors import SchemaVersionError, SnapshotNotFoundError
from qci.domain.snapshot import (
    CalibrationSnapshot,
    Measurement,
    SnapshotCapture,
    SnapshotListItem,
)
from qci.storage.sqlite import schema_meta_table

SNAPSHOT_DB_SCHEMA_VERSION = 1
_SCHEMA_KEY = "snapshot_db_schema"

_metadata = MetaData()

snapshots_table = Table(
    "calibration_snapshots",
    _metadata,
    Column("snapshot_id", String, primary_key=True),
    Column("content_hash", String, nullable=False, unique=True),
    Column("schema_version", Integer, nullable=False),
    Column("provider", String, nullable=False),
    Column("backend_name", String, nullable=False),
    Column("source", String, nullable=False),
    Column("first_captured_at", String, nullable=False),
    Column("calibrated_at", String, nullable=True),
    Column("record_json", Text, nullable=False),
    Index("ix_snapshots_backend", "provider", "backend_name", "first_captured_at"),
)

captures_table = Table(
    "snapshot_captures",
    _metadata,
    Column("capture_id", String, primary_key=True),
    Column("snapshot_id", String, nullable=False),
    Column("captured_at", String, nullable=False),
    Index("ix_captures_snapshot", "snapshot_id"),
    Index("ix_captures_captured_at", "captured_at"),
)

measurements_table = Table(
    "calibration_measurements",
    _metadata,
    Column("snapshot_id", String, primary_key=True),
    Column("seq", Integer, primary_key=True),
    Column("resource_kind", String, nullable=False),
    Column("resource", String, nullable=False),
    Column("parameter", String, nullable=False),
    Column("value_real", Float, nullable=True),
    Column("value_text", Text, nullable=True),
    Column("unit", String, nullable=True),
    Column("measured_at", String, nullable=True),
    Index("ix_measurements_resource", "resource", "parameter"),
)


def _utc(value: datetime) -> str:
    """UTC ISO-8601, so that stored timestamps sort lexicographically."""
    return value.astimezone(UTC).isoformat()


def _measurement_row(snapshot_id: str, seq: int, m: Measurement) -> dict[str, object]:
    return {
        "snapshot_id": snapshot_id,
        "seq": seq,
        "resource_kind": m.resource_kind,
        "resource": m.resource,
        "parameter": m.parameter,
        "value_real": m.value if isinstance(m.value, float) else None,
        "value_text": m.value if isinstance(m.value, str) else None,
        "unit": m.unit,
        "measured_at": _utc(m.measured_at) if m.measured_at else None,
    }


class SqliteSnapshotRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{db_path}")
        schema_meta_table.create(self._engine, checkfirst=True)
        _metadata.create_all(self._engine)
        with self._engine.begin() as conn:
            row = conn.execute(
                select(schema_meta_table.c.value).where(schema_meta_table.c.key == _SCHEMA_KEY)
            ).first()
            if row is None:
                conn.execute(
                    insert(schema_meta_table).values(
                        key=_SCHEMA_KEY, value=str(SNAPSHOT_DB_SCHEMA_VERSION)
                    )
                )
            elif int(row.value) != SNAPSHOT_DB_SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"{db_path} has snapshot DB schema {row.value}; this QCI supports "
                    f"{SNAPSHOT_DB_SCHEMA_VERSION}"
                )

    @staticmethod
    def _by_hash(conn: Connection, content_hash: str) -> CalibrationSnapshot | None:
        row = conn.execute(
            select(snapshots_table.c.record_json).where(
                snapshots_table.c.content_hash == content_hash
            )
        ).first()
        return None if row is None else CalibrationSnapshot.model_validate_json(row.record_json)

    def save(
        self,
        snapshot: CalibrationSnapshot,
        measurements: Sequence[Measurement],
        capture: SnapshotCapture,
    ) -> tuple[CalibrationSnapshot, bool]:
        with self._engine.begin() as conn:
            existing = self._by_hash(conn, snapshot.content_hash)
            if existing is None:
                conn.execute(
                    insert(snapshots_table).values(
                        snapshot_id=snapshot.snapshot_id,
                        content_hash=snapshot.content_hash,
                        schema_version=snapshot.schema_version,
                        provider=snapshot.provider,
                        backend_name=snapshot.backend_name,
                        source=snapshot.source.value,
                        first_captured_at=_utc(snapshot.captured_at),
                        calibrated_at=(
                            _utc(snapshot.calibrated_at) if snapshot.calibrated_at else None
                        ),
                        record_json=snapshot.model_dump_json(),
                    )
                )
                if measurements:
                    conn.execute(
                        insert(measurements_table),
                        [
                            _measurement_row(snapshot.snapshot_id, seq, m)
                            for seq, m in enumerate(measurements)
                        ],
                    )
            stored = existing or snapshot
            conn.execute(
                insert(captures_table).values(
                    capture_id=capture.capture_id,
                    snapshot_id=stored.snapshot_id,
                    captured_at=_utc(capture.captured_at),
                )
            )
        return stored, existing is None

    def get(self, snapshot_id: str) -> CalibrationSnapshot:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(snapshots_table.c.record_json).where(
                    snapshots_table.c.snapshot_id == snapshot_id
                )
            ).first()
        if row is None:
            raise SnapshotNotFoundError(f"no snapshot with id {snapshot_id!r}")
        return CalibrationSnapshot.model_validate_json(row.record_json)

    def get_by_hash(self, content_hash: str) -> CalibrationSnapshot | None:
        with self._engine.connect() as conn:
            return self._by_hash(conn, content_hash)

    def list_snapshots(
        self, backend_name: str | None = None, limit: int | None = None
    ) -> list[SnapshotListItem]:
        s, c = snapshots_table.c, captures_table.c
        query = (
            select(
                s.snapshot_id,
                s.provider,
                s.backend_name,
                s.calibrated_at,
                s.first_captured_at,
                func.max(c.captured_at).label("last_captured_at"),
                func.count(c.capture_id).label("capture_count"),
            )
            .select_from(snapshots_table.join(captures_table, c.snapshot_id == s.snapshot_id))
            .group_by(s.snapshot_id)
            .order_by(s.first_captured_at.desc(), s.snapshot_id.desc())
        )
        if backend_name is not None:
            query = query.where(s.backend_name == backend_name)
        if limit is not None:
            query = query.limit(limit)
        with self._engine.connect() as conn:
            rows = conn.execute(query).all()
        return [SnapshotListItem.model_validate(row._asdict()) for row in rows]

    def measurements(self, snapshot_id: str) -> list[Measurement]:
        m = measurements_table.c
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(measurements_table).where(m.snapshot_id == snapshot_id).order_by(m.seq)
            ).all()
        return [
            Measurement(
                resource_kind=row.resource_kind,
                resource=row.resource,
                parameter=row.parameter,
                value=row.value_real if row.value_real is not None else row.value_text,
                unit=row.unit,
                measured_at=(datetime.fromisoformat(row.measured_at) if row.measured_at else None),
            )
            for row in rows
        ]

    def captures(self, snapshot_id: str) -> list[SnapshotCapture]:
        c = captures_table.c
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(c.capture_id, c.snapshot_id, c.captured_at)
                .where(c.snapshot_id == snapshot_id)
                .order_by(c.captured_at, c.capture_id)
            ).all()
        return [SnapshotCapture.model_validate(row._asdict()) for row in rows]

    def close(self) -> None:
        self._engine.dispose()
