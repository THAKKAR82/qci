"""Insert-only SQLite run repository (SQLAlchemy 2 Core).

Each run is stored as its complete JSON document plus a few indexed columns for listing.
There is deliberately no update or delete. See docs/adr/0003-immutable-run-records.md.
"""

from pathlib import Path

from sqlalchemy import (
    Column,
    Engine,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    inspect,
    select,
)
from sqlalchemy.exc import IntegrityError

from qci.core.errors import (
    DamagedStoreError,
    DuplicateRunError,
    ReadOnlyStoreError,
    RunNotFoundError,
    SchemaVersionError,
)
from qci.domain.run import Run, RunListItem

DB_SCHEMA_VERSION = 1

_metadata = MetaData()

runs_table = Table(
    "runs",
    _metadata,
    Column("run_id", String, primary_key=True),
    Column("schema_version", Integer, nullable=False),
    Column("created_at", String, nullable=False),
    Column("status", String, nullable=False),
    Column("workload_name", String, nullable=False),
    Column("backend_name", String, nullable=True),
    Column("git_commit", String, nullable=True),
    Column("record_json", Text, nullable=False),
    Index("ix_runs_created_at", "created_at"),
)

schema_meta_table = Table(
    "schema_meta",
    _metadata,
    Column("key", String, primary_key=True),
    Column("value", String, nullable=False),
)


def open_read_only(
    db_path: Path, label: str, tables: set[str], schema_key: str, supported: int
) -> Engine | None:
    """A read-only engine on the ``label`` store in ``db_path``, or None if it is empty.

    SQLite opens the file with ``mode=ro``, so nothing is ever written: the file, its tables
    and ``schema_meta`` are never created. A missing file, or a file with none of ``tables``,
    is an empty store. Some but not all of ``tables``, or all of them without a ``schema_key``
    row in ``schema_meta``, raises ``DamagedStoreError``. Another version raises
    ``SchemaVersionError``.
    """
    if not db_path.is_file():
        return None
    engine = create_engine(f"sqlite:///{db_path.resolve().as_uri()}?mode=ro&uri=true")
    try:
        present = set(inspect(engine).get_table_names())
        found, missing = sorted(tables & present), sorted(tables - present)
        if not found:
            engine.dispose()
            return None
        if missing:
            raise DamagedStoreError(
                f"{db_path}: the {label} store is damaged: tables {', '.join(found)} exist but "
                f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} missing"
            )
        if "schema_meta" not in present:
            raise DamagedStoreError(
                f"{db_path}: the {label} store is damaged: its tables exist but the "
                "schema_meta table is missing"
            )
        with engine.connect() as conn:
            row = conn.execute(
                select(schema_meta_table.c.value).where(schema_meta_table.c.key == schema_key)
            ).first()
        if row is None:
            raise DamagedStoreError(
                f"{db_path}: the {label} store is damaged: its tables exist but schema_meta has "
                f"no {schema_key!r} row"
            )
        if int(row.value) != supported:
            raise SchemaVersionError(
                f"{db_path} has {schema_key} {row.value}; this QCI supports {supported}"
            )
    except Exception:
        engine.dispose()
        raise
    return engine


class SqliteRunRepository:
    def __init__(self, db_path: Path, *, read_only: bool = False) -> None:
        """``read_only`` never creates or writes the store. A missing or empty store has no
        runs. In either mode, a damaged store raises ``DamagedStoreError`` and another version
        raises ``SchemaVersionError`` before anything is written."""
        self._read_only = read_only
        if read_only:
            self._engine: Engine | None = open_read_only(
                db_path, "run", {"runs"}, "db_schema", DB_SCHEMA_VERSION
            )
            return
        # Check before writing anything: a damaged or other-version store raises here, with
        # nothing created. Only an empty store gets tables and a version row below.
        probe = open_read_only(db_path, "run", {"runs"}, "db_schema", DB_SCHEMA_VERSION)
        if probe is not None:
            probe.dispose()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = engine = create_engine(f"sqlite:///{db_path}")
        _metadata.create_all(engine)
        with engine.begin() as conn:
            row = conn.execute(
                select(schema_meta_table.c.value).where(schema_meta_table.c.key == "db_schema")
            ).first()
            if row is None:
                conn.execute(
                    insert(schema_meta_table).values(key="db_schema", value=str(DB_SCHEMA_VERSION))
                )
            elif int(row.value) != DB_SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"{db_path} has DB schema {row.value}; this QCI supports {DB_SCHEMA_VERSION}"
                )

    def save(self, run: Run) -> None:
        if self._read_only or self._engine is None:
            raise ReadOnlyStoreError("this run repository was opened read-only")
        values = {
            "run_id": run.run_id,
            "schema_version": run.schema_version,
            "created_at": run.created_at.isoformat(),
            "status": run.status.value,
            "workload_name": run.workload.name,
            "backend_name": run.backend.name if run.backend else None,
            "git_commit": run.provenance.git.commit,
            "record_json": run.model_dump_json(),
        }
        try:
            with self._engine.begin() as conn:
                conn.execute(insert(runs_table).values(**values))
        except IntegrityError as exc:
            raise DuplicateRunError(f"run {run.run_id} already exists") from exc

    def get(self, run_id: str) -> Run:
        row = None
        if self._engine is not None:
            with self._engine.connect() as conn:
                row = conn.execute(
                    select(runs_table.c.record_json).where(runs_table.c.run_id == run_id)
                ).first()
        if row is None:
            raise RunNotFoundError(f"no run with id {run_id!r}")
        return Run.model_validate_json(row.record_json)

    def list_runs(self, limit: int | None = None) -> list[RunListItem]:
        if self._engine is None:
            return []
        query = select(
            runs_table.c.run_id,
            runs_table.c.created_at,
            runs_table.c.status,
            runs_table.c.workload_name,
            runs_table.c.backend_name,
            runs_table.c.git_commit,
        ).order_by(runs_table.c.run_id.desc())
        if limit is not None:
            query = query.limit(limit)
        with self._engine.connect() as conn:
            rows = conn.execute(query).all()
        return [RunListItem.model_validate(row._asdict()) for row in rows]

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
