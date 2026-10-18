"""Check backfilled lookups against stored live captures, offline (M1.5c manual check).

Makes no network request and writes nothing: every store is opened read-only (SQLite
``mode=ro``). It prints only device names, snapshot and capture IDs, times, hashes, row
counts and outcome labels; never a calibration value, payload, path or account data.

    PYTHONPATH=src .venv/bin/python scripts/check_backfill_against_live.py \
        --store PATH [--before BACKUP]

Part 1, with ``--before``: the store compared with a backup taken before the backfill. Every
schema object and every row of the backup must still be in the store, unchanged, except the
``snapshot_db_schema`` version row (1 -> 2 by the upcast). Added rows may only be
``historical_lookup`` snapshots, their measurements, lookup captures and their
``snapshot_lookups`` rows, plus the ``snapshot_lookups`` table itself. Outcome
``only_backfill_additions`` or ``other_change:<what>``.

Part 2, the M1.5b ground-truth cross-check (``scripts/verify_historical_calibration.py``,
``cross_check_outcome``) applied to stored lookups instead of new requests. For a stored live
snapshot stamped L and first captured at T:

- **covering:** every lookup capture whose requested time G satisfies L <= G <= T. The live
  capture shows that the document stamped L was being served at T, so a lookup as of G must
  return L or a document stamped after L and at or before G. Labels as in M1.5b, with G in
  place of T: ``match``, ``different_document:lag_consistent`` (L < R <= G) or
  ``different_document:inconsistent``.
- **same_stamp:** every lookup snapshot whose returned stamp R equals L. ``match`` when the
  properties hashes are equal, otherwise ``different_document:same_stamp``.

A device with no covering or same-stamp lookup is reported as
``inconclusive:no_overlapping_lookup``; that is no evidence either way. Exit code 0 when part
1 (if run) shows only backfill additions and part 2 has no ``inconsistent`` or ``same_stamp``
difference, 1 otherwise.
"""

import argparse
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from verify_historical_calibration import (
    DEVICES,
    Document,
    StoredSnapshot,
    cross_check_outcome,
    stored_live_snapshots,
)

from qci.core.hashing import hash_json
from qci.domain.backend import SnapshotSource
from qci.storage.snapshots import SqliteSnapshotRepository

DEFAULT_STORE = Path.home() / ".qci-live" / "qci.db"
ALL_LIVE = 10**9
VERSION_KEY = "snapshot_db_schema"


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _rows(conn: sqlite3.Connection, table: str) -> Counter[tuple[object, ...]]:
    return Counter(tuple(r) for r in conn.execute(f'select * from "{table}"'))


def _schema(conn: sqlite3.Connection) -> dict[str, str | None]:
    rows = conn.execute("select name, sql from sqlite_master")
    return {str(name): sql for name, sql in rows}


def store_diff(before_path: Path, after_path: Path) -> list[str]:
    """Labels of every change that is not a backfill addition; empty when there is none."""
    problems: list[str] = []
    before, after = _connect(before_path), _connect(after_path)
    try:
        before_schema, after_schema = _schema(before), _schema(after)
        for name, sql in before_schema.items():
            if after_schema.get(name, "<absent>") != sql:
                problems.append(f"schema_object_changed:{name}")
        for name in sorted(set(after_schema) - set(before_schema)):
            if "lookups" not in name:
                problems.append(f"schema_object_added:{name}")

        tables = [n for n, sql in before_schema.items() if sql and sql.startswith("CREATE TABLE")]
        added: dict[str, Counter[tuple[object, ...]]] = {}
        for table in tables:
            old, new = _rows(before, table), _rows(after, table)
            lost = old - new
            if table == "schema_meta":
                lost.pop((VERSION_KEY, "1"), None)
            if lost:
                problems.append(f"rows_removed_or_changed:{table}:{sum(lost.values())}")
            added[table] = new - old
            print(
                f"store_diff  table={table}  before={sum(old.values())}  "
                f"after={sum(new.values())}  added={sum(added[table].values())}",
                flush=True,
            )
        lookup_rows = (
            _rows(after, "snapshot_lookups") if "snapshot_lookups" in after_schema else Counter()
        )
        if "snapshot_lookups" not in tables:
            print(
                f"store_diff  table=snapshot_lookups  before=absent  "
                f"after={sum(lookup_rows.values())}  added={sum(lookup_rows.values())}",
                flush=True,
            )
            added["snapshot_lookups"] = lookup_rows

        meta = dict(after.execute("select key, value from schema_meta").fetchall())
        old_meta = dict(before.execute("select key, value from schema_meta").fetchall())
        print(
            f"store_diff  {VERSION_KEY}_before={old_meta.get(VERSION_KEY)}  "
            f"{VERSION_KEY}_after={meta.get(VERSION_KEY)}",
            flush=True,
        )
        if meta.get(VERSION_KEY) != "2":
            problems.append(f"{VERSION_KEY}_not_2")
        for key in (k for k in added.get("schema_meta", Counter()) if k[0] != VERSION_KEY):
            problems.append(f"schema_meta_row_added:{key[0]}")
        for table in tables:
            if table not in {
                "schema_meta",
                "calibration_snapshots",
                "calibration_measurements",
                "snapshot_captures",
                "snapshot_lookups",
            } and added.get(table):
                problems.append(f"rows_added:{table}")

        lookup_ids = {str(row[0]) for row in lookup_rows}
        added_captures = {str(row[0]) for row in added.get("snapshot_captures", Counter())}
        for capture_id in sorted(added_captures - lookup_ids):
            problems.append(f"live_capture_added:{capture_id}")
        for row in added.get("snapshot_lookups", Counter()):
            if str(row[0]) not in added_captures:
                problems.append(f"lookup_row_for_existing_capture:{row[0]}")
        new_snapshots = set()
        for row in added.get("calibration_snapshots", Counter()):
            new_snapshots.add(row[0])
            if row[5] != SnapshotSource.HISTORICAL_LOOKUP.value:
                problems.append(f"non_lookup_snapshot_added:{row[0]}")
        for row in added.get("calibration_measurements", Counter()):
            if row[0] not in new_snapshots:
                problems.append(f"measurement_added_to_existing_snapshot:{row[0]}")
    finally:
        before.close()
        after.close()
    return problems


@dataclass(frozen=True)
class StoredLookup:
    snapshot_id: str
    capture_id: str
    requested_before: datetime
    returned: Document


def stored_lookups(store: Path) -> dict[str, list[StoredLookup]]:
    repository = SqliteSnapshotRepository(store, read_only=True)
    try:
        found: dict[str, list[StoredLookup]] = {}
        for device in DEVICES:
            rows: list[StoredLookup] = []
            for item in repository.list_snapshots(backend_name=device):
                snapshot = repository.get(item.snapshot_id)
                if snapshot.source is not SnapshotSource.HISTORICAL_LOOKUP:
                    continue
                properties = snapshot.provider_raw.get("properties")
                document = Document(
                    present=properties is not None,
                    last_update=snapshot.calibrated_at,
                    hash=hash_json(properties) if properties is not None else None,
                )
                for capture in repository.captures(snapshot.snapshot_id):
                    if capture.requested_before is not None:
                        rows.append(
                            StoredLookup(
                                snapshot.snapshot_id,
                                capture.capture_id,
                                capture.requested_before.astimezone(UTC),
                                document,
                            )
                        )
            found[device] = sorted(rows, key=lambda r: r.requested_before)
        return found
    finally:
        repository.close()


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "none"


def cross_check(store: Path) -> Counter[str]:
    live = stored_live_snapshots(store, ALL_LIVE)
    lookups = stored_lookups(store)
    totals: Counter[str] = Counter()
    for device in DEVICES:
        print(
            f"{device}  live_snapshots={len(live[device])}  lookup_captures={len(lookups[device])}",
            flush=True,
        )
        checked = 0
        for snap in live[device]:
            stamp = snap.calibrated_at
            for lookup in lookups[device]:
                if stamp is not None and stamp <= lookup.requested_before <= snap.captured_at:
                    as_of_lookup = StoredSnapshot(
                        snapshot_id=snap.snapshot_id,
                        captured_at=lookup.requested_before,
                        calibrated_at=stamp,
                        properties_hash=snap.properties_hash,
                    )
                    kind, outcome = "covering", cross_check_outcome(as_of_lookup, lookup.returned)
                elif stamp is not None and lookup.returned.last_update == stamp:
                    same = lookup.returned.hash == snap.properties_hash
                    kind, outcome = (
                        "same_stamp",
                        ("match" if same else "different_document:same_stamp"),
                    )
                else:
                    continue
                checked += 1
                totals[outcome] += 1
                print(
                    f"{device}  {kind}  live_snapshot={snap.snapshot_id}  "
                    f"lookup_snapshot={lookup.snapshot_id}  capture={lookup.capture_id}  "
                    f"requested_before={lookup.requested_before.isoformat()}  "
                    f"live_last_update={_iso(stamp)}  "
                    f"live_first_captured={snap.captured_at.isoformat()}  "
                    f"returned_last_update={_iso(lookup.returned.last_update)}  "
                    f"live_hash={snap.properties_hash or 'none'}  "
                    f"returned_hash={lookup.returned.hash or 'none'}  outcome={outcome}",
                    flush=True,
                )
        if not checked:
            totals["inconclusive:no_overlapping_lookup"] += 1
            print(f"{device}  outcome=inconclusive:no_overlapping_lookup", flush=True)
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description="Check backfilled lookups, offline.")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE, help="Read-only.")
    parser.add_argument("--before", type=Path, help="Backup taken before the backfill.")
    args = parser.parse_args()
    store: Path = args.store.expanduser()
    status = 0
    if args.before is not None:
        problems = store_diff(args.before.expanduser(), store)
        for problem in problems:
            print(f"store_diff  outcome=other_change:{problem}", flush=True)
        if problems:
            status = 1
        else:
            print("store_diff  outcome=only_backfill_additions", flush=True)
    totals = cross_check(store)
    print("summary  " + "  ".join(f"{k}={v}" for k, v in sorted(totals.items())), flush=True)
    if totals["different_document:inconsistent"] or totals["different_document:same_stamp"]:
        status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
