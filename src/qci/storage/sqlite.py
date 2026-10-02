"""Insert-only SQLite run repository (SQLAlchemy 2 Core).

Each run is stored as its complete JSON document plus a few indexed columns for listing.
There is deliberately no update or delete. See docs/adr/0003-immutable-run-records.md.
"""

from pathlib import Path

from sqlalchemy import (
    Column,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
)
from sqlalchemy.exc import IntegrityError

from qci.core.errors import DuplicateRunError, RunNotFoundError, SchemaVersionError
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


class SqliteRunRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{db_path}")
        _metadata.create_all(self._engine)
        with self._engine.begin() as conn:
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
        with self._engine.connect() as conn:
            row = conn.execute(
                select(runs_table.c.record_json).where(runs_table.c.run_id == run_id)
            ).first()
        if row is None:
            raise RunNotFoundError(f"no run with id {run_id!r}")
        return Run.model_validate_json(row.record_json)

    def list_runs(self, limit: int | None = None) -> list[RunListItem]:
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
        self._engine.dispose()
