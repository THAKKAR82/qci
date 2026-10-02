from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from conftest import RAW_PROPERTIES, make_run
from qci.core.errors import DuplicateRunError, RunNotFoundError, SchemaVersionError
from qci.storage.sqlite import SqliteRunRepository


def test_save_get_round_trip(repo: SqliteRunRepository) -> None:
    run = make_run()
    repo.save(run)
    assert repo.get(run.run_id) == run


def test_get_unknown_run_raises(repo: SqliteRunRepository) -> None:
    with pytest.raises(RunNotFoundError):
        repo.get("NOPE")


def test_duplicate_run_id_is_rejected_and_original_kept(repo: SqliteRunRepository) -> None:
    original = make_run()
    repo.save(original)
    with pytest.raises(DuplicateRunError):
        repo.save(make_run(tags={"changed": "yes"}))
    assert repo.get(original.run_id) == original


def test_repository_has_no_mutation_api() -> None:
    public = {name for name in dir(SqliteRunRepository) if not name.startswith("_")}
    assert public == {"save", "get", "list_runs", "close"}


def test_list_runs_newest_first_with_limit(repo: SqliteRunRepository) -> None:
    ids = ["01AAAAAAAAAAAAAAAAAAAAAAAA", "01BBBBBBBBBBBBBBBBBBBBBBBB", "01CCCCCCCCCCCCCCCCCCCCCCCC"]
    for run_id in ids:
        repo.save(make_run(run_id=run_id))
    items = repo.list_runs()
    assert [i.run_id for i in items] == list(reversed(ids))
    assert items[0].workload_name == "bell"
    assert items[0].backend_name == "stub_backend"
    assert items[0].git_commit == "c0ffee"
    assert len(repo.list_runs(limit=2)) == 2


def test_raw_provider_payload_survives_storage_verbatim(repo: SqliteRunRepository) -> None:
    repo.save(make_run())
    snapshot = repo.get("01TESTRUN00000000000000000").backend_snapshot
    assert snapshot is not None
    assert snapshot.provider_raw["properties"] == RAW_PROPERTIES


def test_unsupported_db_schema_version_is_refused(tmp_path: Path) -> None:
    db = tmp_path / "qci.db"
    SqliteRunRepository(db).close()
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(text("UPDATE schema_meta SET value = '99' WHERE key = 'db_schema'"))
    engine.dispose()
    with pytest.raises(SchemaVersionError):
        SqliteRunRepository(db)
