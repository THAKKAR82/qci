"""Insert-only SQLite run repository (SQLAlchemy 2 Core).

Each run is stored as its complete JSON document plus a few indexed columns for listing.
There is deliberately no update or delete. See docs/adr/0003-immutable-run-records.md.
"""

from collections.abc import Mapping
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
_RUN_VERSIONS = {DB_SCHEMA_VERSION: {"runs"}}

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


def _names(names: set[str]) -> str:
    return ", ".join(sorted(names))


def open_read_only(
    db_path: Path, label: str, versions: Mapping[int, set[str]], schema_key: str
) -> Engine | None:
    """A read-only engine on the ``label`` store in ``db_path``, or None if it is empty.

    ``versions`` maps each supported schema version to its exact table set. SQLite opens the
    file with ``mode=ro``, so nothing is ever written: the file, its tables and
    ``schema_meta`` are never created. A missing file, or a file with none of the tables, is
    an empty store. Raises ``DamagedStoreError`` when only some of the tables every version
    has are present, when ``schema_meta`` or its ``schema_key`` row is missing, or when the
    tables present are not the set of the recorded version. Another version raises
    ``SchemaVersionError``.
    """
    if not db_path.is_file():
        return None
    known = set().union(*versions.values())
    common = set.intersection(*versions.values())
    engine = create_engine(f"sqlite:///{db_path.resolve().as_uri()}?mode=ro&uri=true")
    try:
        present = set(inspect(engine).get_table_names())
        found = known & present
        if not found:
            engine.dispose()
            return None
        missing = common - present
        if missing:
            listed = (common & present) or found
            raise DamagedStoreError(
                f"{db_path}: the {label} store is damaged: tables {_names(listed)} exist but "
                f"{_names(missing)} {'is' if len(missing) == 1 else 'are'} missing"
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
        version = int(row.value)
        if version not in versions:
            supported = " and ".join(str(v) for v in sorted(versions))
            raise SchemaVersionError(
                f"{db_path} has {schema_key} {row.value}; this QCI supports {supported}"
            )
        expected = versions[version]
        if found != expected:
            parts = []
            if expected - found:
                parts.append(f"{_names(expected - found)} missing")
            if found - expected:
                parts.append(f"{_names(found - expected)} present")
            raise DamagedStoreError(
                f"{db_path}: the {label} store is damaged: {schema_key} {version} but tables "
                + " and ".join(parts)
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
            self._engine: Engine | None = open_read_only(db_path, "run", _RUN_VERSIONS, "db_schema")
            return
        # Check before writing anything: a damaged or other-version store raises here, with
        # nothing created. Only an empty store gets tables and a version row below.
        probe = open_read_only(db_path, "run", _RUN_VERSIONS, "db_schema")
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
