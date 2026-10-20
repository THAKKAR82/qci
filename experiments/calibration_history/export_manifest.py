"""Data manifest of the M1.5d analysis: export it from a store, or verify a store against it.

Usage (from the repository root):

    PYTHONPATH=src:experiments/calibration_history .venv/bin/python \
        experiments/calibration_history/export_manifest.py export \
        --store STORE.db --collection-date YYYY-MM-DD --out MANIFEST.csv

    PYTHONPATH=src:experiments/calibration_history .venv/bin/python \
        experiments/calibration_history/export_manifest.py verify \
        --manifest MANIFEST.csv --store STORE.db

``export`` writes one row per lookup the analysis used: every device, the dense and the sparse
set selected exactly as ``history_analysis.analyze`` selects them for the collection date.
A row holds identifiers, the grid time, the provider stamp and the content hash, never a
parameter value. It refuses to run on a dirty tree and to overwrite a file, and writes nothing
if the store's SHA-256 changed while it was read.

``verify`` reports, for each row, whether the store holds a lookup at that grid time that
returned a snapshot with that content hash. Snapshot and capture IDs are not compared: a
re-fetched store has new ones. Both modes open the store read-only. See
docs/experiments/2026-10-calibration-history.md, "Data and reproducibility".
"""

import argparse
import csv
import io
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from history_analysis import FOOTPRINTS, dense_grid, sparse_grid
from run_analysis import git_state, sha256_file

from qci.adapters.qiskit_ibm.adapter_ids import PROVIDER_ID
from qci.storage.snapshots import SqliteSnapshotRepository

METHOD_VERSION = "qci.m15d.manifest.1"
COLUMNS = (
    "device",
    "set",
    "grid_time",
    "capture_id",
    "snapshot_id",
    "provider_stamp",
    "content_hash",
)
PRESENT = "present"
MISSING = "missing"
DIFFERS = "differs"


@dataclass(frozen=True)
class LookupRecord:
    grid_time: datetime
    captured_at: datetime
    capture_id: str
    snapshot_id: str
    provider_stamp: datetime | None
    content_hash: str


@dataclass(frozen=True)
class ManifestRow:
    device: str
    set: str
    grid_time: datetime
    capture_id: str
    snapshot_id: str
    provider_stamp: datetime | None
    content_hash: str

    def cells(self) -> list[str]:
        return [
            self.device,
            self.set,
            iso(self.grid_time),
            self.capture_id,
            self.snapshot_id,
            "" if self.provider_stamp is None else iso(self.provider_stamp),
            self.content_hash,
        ]


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def device_lookups(repository: SqliteSnapshotRepository, backend: str) -> list[LookupRecord]:
    """Every historical lookup of ``backend``, ordered as ``StoreReader.lookups`` orders them:
    by grid time, then capture time, capture ID and snapshot ID."""
    found: list[LookupRecord] = []
    for item in repository.list_snapshots(backend_name=backend):
        if item.provider != PROVIDER_ID:
            continue
        snapshot = repository.get(item.snapshot_id)
        for capture in repository.captures(item.snapshot_id):
            if capture.method != "historical_lookup" or capture.requested_before is None:
                continue
            found.append(
                LookupRecord(
                    grid_time=capture.requested_before.astimezone(UTC),
                    captured_at=capture.captured_at,
                    capture_id=capture.capture_id,
                    snapshot_id=capture.snapshot_id,
                    provider_stamp=snapshot.calibrated_at,
                    content_hash=snapshot.content_hash,
                )
            )
    return sorted(found, key=lambda r: (r.grid_time, r.captured_at, r.capture_id, r.snapshot_id))


def first_by_time(records: Iterable[LookupRecord]) -> dict[datetime, LookupRecord]:
    """The earliest capture at each grid time, the one the analysis uses."""
    by_time: dict[datetime, LookupRecord] = {}
    for record in records:
        by_time.setdefault(record.grid_time, record)
    return by_time


def manifest_rows(repository: SqliteSnapshotRepository, collection_date: date) -> list[ManifestRow]:
    rows: list[ManifestRow] = []
    for backend in FOOTPRINTS:
        by_time = first_by_time(device_lookups(repository, backend))
        for set_name, grid in (
            ("dense", dense_grid(collection_date)),
            ("sparse", sparse_grid(collection_date)),
        ):
            for t in grid:
                record = by_time.get(t)
                if record is None:
                    continue
                rows.append(
                    ManifestRow(
                        device=backend,
                        set=set_name,
                        grid_time=t,
                        capture_id=record.capture_id,
                        snapshot_id=record.snapshot_id,
                        provider_stamp=record.provider_stamp,
                        content_hash=record.content_hash,
                    )
                )
    return sorted(rows, key=lambda r: (r.device, r.set, r.grid_time))


def render_manifest(rows: Sequence[ManifestRow], metadata: Sequence[tuple[str, str]]) -> str:
    """Leading ``# key: value`` lines, then the CSV header and the rows."""
    buffer = io.StringIO()
    for key, value in metadata:
        buffer.write(f"# {key}: {value}\n")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(row.cells() for row in rows)
    return buffer.getvalue()


def parse_manifest(text: str) -> tuple[dict[str, str], list[ManifestRow]]:
    metadata: dict[str, str] = {}
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("# ") and not body:
            key, _, value = line[2:].partition(": ")
            metadata[key] = value
        else:
            body.append(line)
    reader = csv.reader(body)
    header = next(reader, None)
    if header is None or tuple(header) != COLUMNS:
        raise ValueError(f"manifest header must be {','.join(COLUMNS)}, got {header}")
    rows = [
        ManifestRow(
            device=device,
            set=set_name,
            grid_time=datetime.fromisoformat(grid_time),
            capture_id=capture_id,
            snapshot_id=snapshot_id,
            provider_stamp=datetime.fromisoformat(stamp) if stamp else None,
            content_hash=content_hash,
        )
        for device, set_name, grid_time, capture_id, snapshot_id, stamp, content_hash in reader
    ]
    return metadata, rows


@dataclass(frozen=True)
class RowCheck:
    row: ManifestRow
    status: str
    found_hashes: tuple[str, ...]
    """The content hashes of every lookup at the row's grid time in the store."""


def verify_rows(
    repository: SqliteSnapshotRepository, rows: Sequence[ManifestRow]
) -> list[RowCheck]:
    hashes: dict[tuple[str, datetime], list[str]] = {}
    for backend in sorted({row.device for row in rows}):
        for record in device_lookups(repository, backend):
            hashes.setdefault((backend, record.grid_time), []).append(record.content_hash)
    checks: list[RowCheck] = []
    for row in rows:
        found = tuple(dict.fromkeys(hashes.get((row.device, row.grid_time), [])))
        if not found:
            status = MISSING
        elif row.content_hash in found:
            status = PRESENT
        else:
            status = DIFFERS
        checks.append(RowCheck(row, status, found))
    return checks


def run_export(store: Path, collection_date: date, out: Path) -> int:
    git = git_state()
    if git.commit is None or git.dirty is not False:
        print(
            "refusing to run: the export must run from a clean, committed tree "
            f"(commit={git.commit}, dirty={git.dirty})",
            file=sys.stderr,
        )
        return 2
    if not store.is_file():
        print(f"refusing to run: no store at {store}", file=sys.stderr)
        return 2
    if out.exists():
        print(f"refusing to overwrite {out}", file=sys.stderr)
        return 2

    before = sha256_file(store)
    print(f"store SHA-256 before: {before}")
    repository = SqliteSnapshotRepository(store, read_only=True)
    try:
        rows = manifest_rows(repository, collection_date)
    finally:
        repository.close()
    after = sha256_file(store)
    print(f"store SHA-256 after:  {after}")
    print(f"git commit: {git.commit}  dirty: {git.dirty}")
    if before != after:
        print("the store changed while it was read; nothing written", file=sys.stderr)
        return 1

    metadata = [
        ("method_version", METHOD_VERSION),
        ("collection_date", collection_date.isoformat()),
        ("store_file", store.name),
        ("store_sha256", before),
        ("git_commit", git.commit),
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_manifest(rows, metadata), encoding="utf-8")
    print(f"wrote {len(rows)} rows to {out}")
    return 0


def run_verify(manifest: Path, store: Path) -> int:
    if not store.is_file():
        print(f"refusing to run: no store at {store}", file=sys.stderr)
        return 2
    metadata, rows = parse_manifest(manifest.read_text(encoding="utf-8"))
    before = sha256_file(store)
    repository = SqliteSnapshotRepository(store, read_only=True)
    try:
        checks = verify_rows(repository, rows)
    finally:
        repository.close()
    after = sha256_file(store)

    for check in checks:
        row = check.row
        line = f"{check.status:8} {row.device} {row.set} {iso(row.grid_time)} {row.content_hash}"
        if check.status == DIFFERS:
            line += f" (store has {', '.join(check.found_hashes)})"
        print(line)
    counts = {s: sum(c.status == s for c in checks) for s in (PRESENT, MISSING, DIFFERS)}
    print(f"manifest store SHA-256: {metadata.get('store_sha256', 'not recorded')}")
    print(f"this store SHA-256:     {before}")
    print(
        f"rows: {len(checks)}; present {counts[PRESENT]}, missing {counts[MISSING]}, "
        f"differs {counts[DIFFERS]}"
    )
    if before != after:
        print("the store changed while it was read", file=sys.stderr)
        return 1
    if counts[PRESENT] == len(checks):
        print("all present")
        return 0
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export or verify the M1.5d data manifest.")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="write the manifest of a store, read-only")
    export.add_argument("--store", type=Path, required=True, help="path to qci.db")
    export.add_argument(
        "--collection-date",
        type=date.fromisoformat,
        required=True,
        help="D, as given to run_analysis.py (YYYY-MM-DD)",
    )
    export.add_argument("--out", type=Path, required=True, help="manifest CSV to write")
    verify = commands.add_parser("verify", help="check a store against a manifest, read-only")
    verify.add_argument("--manifest", type=Path, required=True, help="manifest CSV")
    verify.add_argument("--store", type=Path, required=True, help="path to qci.db")
    args = parser.parse_args(argv)
    if args.command == "export":
        return run_export(args.store.expanduser(), args.collection_date, args.out.expanduser())
    return run_verify(args.manifest.expanduser(), args.store.expanduser())


if __name__ == "__main__":
    raise SystemExit(main())
