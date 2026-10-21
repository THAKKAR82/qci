"""Insert-only SQLite calibration snapshot repository (ADR 0005, section 1).

Snapshot tables live in the same file as runs but are owned here. They record their own
schema version under ``snapshot_db_schema``, so the runs table and ``DB_SCHEMA_VERSION`` are
untouched. There is deliberately no update or delete.

Version 2 (ADR 0008, section 3) adds ``snapshot_lookups``: one row per historical lookup
capture. A capture without a row is a live capture. Opening a version 1 store for writing
upcasts it in one transaction: it creates ``snapshot_lookups`` and records version 2, and
changes no other row. A read-only open of a version 1 store reads every capture as live.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    Connection,
    Engine,
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
    inspect,
    select,
    update,
)

from qci.core.errors import ReadOnlyStoreError, SchemaVersionError, SnapshotNotFoundError
from qci.domain.snapshot import (
    HISTORICAL_LOOKUP_METHOD_VERSION,
    CalibrationSnapshot,
    Measurement,
    SnapshotCapture,
    SnapshotListItem,
)
from qci.storage.sqlite import open_read_only, schema_meta_table, stored_schema_version

SNAPSHOT_DB_SCHEMA_VERSION = 2
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


lookups_table = Table(
    "snapshot_lookups",
    _metadata,
    Column("capture_id", String, primary_key=True),
    Column("requested_before", String, nullable=False),
    Column("method_version", String, nullable=False),
    Index("ix_lookups_requested_before", "requested_before"),
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


_V1_TABLES = {"calibration_snapshots", "snapshot_captures", "calibration_measurements"}
_VERSIONS = {1: _V1_TABLES, 2: _V1_TABLES | {"snapshot_lookups"}}


def snapshot_store_summary(db_path: Path) -> tuple[int, int] | None:
    """``(schema version, number of snapshots)``, read-only, or None for an empty store.

    Raises ``DamagedStoreError`` or ``SchemaVersionError`` as a read-only open does.
    """
    engine = open_read_only(db_path, "snapshot", _VERSIONS, _SCHEMA_KEY)
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            count = conn.execute(select(func.count()).select_from(snapshots_table)).scalar_one()
        return stored_schema_version(engine, _SCHEMA_KEY), int(count)
    finally:
        engine.dispose()


class SqliteSnapshotRepository:
    def __init__(self, db_path: Path, *, read_only: bool = False) -> None:
        """``read_only`` never creates or writes the store. A store with none of the snapshot
        tables has no snapshots. In either mode, a damaged store raises ``DamagedStoreError``
        and another version raises ``SchemaVersionError`` before anything is written. Opening
        a version 1 store for writing upcasts it to version 2."""
        self._read_only = read_only
        if read_only:
            self._engine: Engine | None = open_read_only(
                db_path, "snapshot", _VERSIONS, _SCHEMA_KEY
            )
            self._has_lookups = self._engine is not None and "snapshot_lookups" in set(
                inspect(self._engine).get_table_names()
            )
            return
        # Check before writing anything: a damaged or other-version store raises here, with
        # nothing created.
        probe = open_read_only(db_path, "snapshot", _VERSIONS, _SCHEMA_KEY)
        if probe is not None:
            probe.dispose()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = engine = create_engine(f"sqlite:///{db_path}")
        self._has_lookups = True
        schema_meta_table.create(engine, checkfirst=True)
        # One transaction. The version row is written first because the SQLite driver opens
        # a transaction only at a data statement; the table DDL that follows is then part of
        # it, so a failure leaves the store as it was.
        with engine.begin() as conn:
            row = conn.execute(
                select(schema_meta_table.c.value).where(schema_meta_table.c.key == _SCHEMA_KEY)
            ).first()
            if row is None:
                conn.execute(
                    insert(schema_meta_table).values(
                        key=_SCHEMA_KEY, value=str(SNAPSHOT_DB_SCHEMA_VERSION)
                    )
                )
                _metadata.create_all(conn)
            elif int(row.value) == 1:
                conn.execute(
                    update(schema_meta_table)
                    .where(schema_meta_table.c.key == _SCHEMA_KEY)
                    .values(value=str(SNAPSHOT_DB_SCHEMA_VERSION))
                )
                lookups_table.create(conn)
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
        if self._read_only or self._engine is None:
            raise ReadOnlyStoreError("this snapshot repository was opened read-only")
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
            if capture.requested_before is not None:
                conn.execute(
                    insert(lookups_table).values(
                        capture_id=capture.capture_id,
                        requested_before=_utc(capture.requested_before),
                        method_version=HISTORICAL_LOOKUP_METHOD_VERSION,
                    )
                )
        return stored, existing is None

    def get(self, snapshot_id: str) -> CalibrationSnapshot:
        row = None
        if self._engine is not None:
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
        if self._engine is None:
            return None
        with self._engine.connect() as conn:
            return self._by_hash(conn, content_hash)

    def list_snapshots(
        self, backend_name: str | None = None, limit: int | None = None
    ) -> list[SnapshotListItem]:
        if self._engine is None:
            return []
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
        if self._engine is None:
            return []
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
        if self._engine is None:
            return []
        c = captures_table.c
        if self._has_lookups:
            query = select(
                c.capture_id, c.snapshot_id, c.captured_at, lookups_table.c.requested_before
            ).select_from(
                captures_table.outerjoin(lookups_table, lookups_table.c.capture_id == c.capture_id)
            )
        else:  # a version 1 store, opened read-only: every capture is live
            query = select(c.capture_id, c.snapshot_id, c.captured_at)
        with self._engine.connect() as conn:
            rows = conn.execute(
                query.where(c.snapshot_id == snapshot_id).order_by(c.captured_at, c.capture_id)
            ).all()
        captures = []
        for row in rows:
            fields = row._asdict()
            requested = fields.pop("requested_before", None)
            if requested is not None:
                fields["method"] = "historical_lookup"
                fields["requested_before"] = datetime.fromisoformat(requested)
            captures.append(SnapshotCapture.model_validate(fields))
        return captures

    def lookup_times(self, provider: str, backend_name: str) -> set[datetime]:
        if self._engine is None or not self._has_lookups:
            return set()
        s, c, lk = snapshots_table.c, captures_table.c, lookups_table.c
        query = (
            select(lk.requested_before)
            .select_from(
                lookups_table.join(captures_table, c.capture_id == lk.capture_id).join(
                    snapshots_table, s.snapshot_id == c.snapshot_id
                )
            )
            .where(s.provider == provider, s.backend_name == backend_name)
        )
        with self._engine.connect() as conn:
            rows = conn.execute(query).all()
        return {datetime.fromisoformat(row.requested_before) for row in rows}

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
