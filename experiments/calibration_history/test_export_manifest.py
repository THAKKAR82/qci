"""Offline tests of the M1.5d data manifest on synthetic stores built in temporary directories."""

import csv
import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import export_manifest
import pytest
from export_manifest import (
    COLUMNS,
    DIFFERS,
    MISSING,
    PRESENT,
    manifest_rows,
    parse_manifest,
    render_manifest,
    verify_rows,
)
from history_analysis import FOOTPRINTS, StoreReader, all_keys, build_set, dense_grid, sparse_grid
from test_calibration_history import E_D, FEZ_QUBITS, D, StoreBuilder, build_experiment, m

from qci.domain.backend import SnapshotSource
from qci.domain.provenance import GitProvenance
from qci.domain.snapshot import CalibrationSnapshot, Measurement, SnapshotCapture
from qci.storage.snapshots import SqliteSnapshotRepository

H = timedelta(hours=1)
CAPTURED = datetime(2026, 10, 20, 12, tzinfo=UTC)


def save(
    repo: SqliteSnapshotRepository,
    snapshot_id: str,
    content_hash: str,
    grid_times: Sequence[datetime | None],
    *,
    backend: str = "ibm_fez",
    provider: str = "qiskit_ibm",
    stamp: datetime | None = None,
    rows: Sequence[Measurement] = (),
    first_capture: int = 0,
) -> None:
    """One document with these IDs and hash, captured once per entry of ``grid_times``
    (``None`` is a live capture)."""
    snapshot = CalibrationSnapshot(
        snapshot_id=snapshot_id,
        content_hash=content_hash,
        provider=provider,
        backend_name=backend,
        backend_version="1.0.0",
        source=SnapshotSource.HISTORICAL_LOOKUP,
        captured_at=CAPTURED,
        calibrated_at=stamp,
        capture_options={},
        extraction_method="synthetic",
        extraction_method_version="1",
        redactions=[],
        environment={},
        provider_raw={},
    )
    for i, t in enumerate(grid_times):
        n = first_capture + i
        capture = SnapshotCapture(
            capture_id=f"{snapshot_id}-CAP-{n:03d}",
            snapshot_id=snapshot_id,
            captured_at=CAPTURED + n * H,
            method="live_capture" if t is None else "historical_lookup",
            requested_before=t,
        )
        repo.save(snapshot, rows, capture)


def clean_git() -> GitProvenance:
    return GitProvenance(commit="b" * 40, branch="chore/test", dirty=False)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def builder(tmp_path: Path) -> StoreBuilder:
    return StoreBuilder(tmp_path / "qci.db")


def build_awkward(builder: StoreBuilder) -> None:
    """The analysis experiment plus every case the selection must skip or resolve: a lookup off
    the grid, one outside both windows, a live capture, another provider, a duplicate lookup and
    an unstamped document."""
    build_experiment(builder)
    builder.add("ibm_fez", E_D - 3 * H, [], [E_D - 30 * H - 30 * timedelta(minutes=1)])
    builder.add("ibm_fez", E_D - 400 * H, [], [E_D - 400 * H])
    builder.add("ibm_fez", E_D, [], [], live=True)
    builder.add("ibm_fez", None, [], [E_D - 7 * H])
    # A second lookup at E_D - H, captured after the first: the analysis keeps the first.
    builder.add("ibm_kingston", E_D - 2 * H, [], [E_D - H])
    save(builder.repo, "OTHER-1", "sha256:other", [E_D - 2 * H], provider="other_provider")


def test_rows_are_the_lookups_the_analysis_selects(builder: StoreBuilder) -> None:
    build_awkward(builder)
    rows = manifest_rows(builder.repo, D)
    reader = StoreReader(builder.repo)
    expected: set[tuple[str, str, datetime, str, str]] = set()
    for backend, footprint in FOOTPRINTS.items():
        lookups = reader.lookups(backend)
        for set_name, grid in (("dense", dense_grid(D)), ("sparse", sparse_grid(D))):
            data = build_set(reader, lookups, grid, all_keys(footprint))
            for t, (lookup, document) in data.lookups.items():
                expected.add((backend, set_name, t, lookup.snapshot_id, document.content_hash))
    got = {(r.device, r.set, r.grid_time, r.snapshot_id, r.content_hash) for r in rows}
    assert got == expected
    assert len(rows) == len(expected)
    # ibm_fez: 5 hourly, G_0 and G_1 (also in the dense window) and the unstamped document in
    # the dense set; G_0..G_6 in the sparse set.
    assert sum(r.device == "ibm_fez" and r.set == "dense" for r in rows) == 8
    assert sum(r.device == "ibm_fez" and r.set == "sparse" for r in rows) == 7
    assert any(r.provider_stamp is None for r in rows)
    assert not any(r.snapshot_id == "OTHER-1" for r in rows)
    kingston = {r.grid_time: r for r in rows if r.device == "ibm_kingston"}
    assert kingston[E_D - H].content_hash != f"sha256:{builder.count:064x}"
    assert rows == sorted(rows, key=lambda r: (r.device, r.set, r.grid_time))


def test_export_writes_a_sorted_csv_without_values_and_leaves_the_store_unchanged(
    builder: StoreBuilder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_awkward(builder)
    builder.close()
    before_bytes = builder.path.read_bytes()
    files_before = sorted(p.name for p in builder.path.parent.iterdir())
    out = tmp_path / "manifest" / "m.csv"
    monkeypatch.setattr(export_manifest, "git_state", clean_git)
    args = ["export", "--store", str(builder.path), "--collection-date", D.isoformat()]
    assert export_manifest.main([*args, "--out", str(out)]) == 0
    assert builder.path.read_bytes() == before_bytes
    assert sorted(p.name for p in builder.path.parent.iterdir() if p.name != "manifest") == (
        files_before
    )

    text = out.read_text()
    lines = text.splitlines()
    assert lines[:5] == [
        "# method_version: qci.m15d.manifest.1",
        f"# collection_date: {D.isoformat()}",
        "# store_file: qci.db",
        f"# store_sha256: {sha256(builder.path)}",
        f"# git_commit: {'b' * 40}",
    ]
    assert lines[5] == ",".join(COLUMNS)
    records = list(csv.reader(lines[6:]))
    assert records == sorted(records, key=lambda r: (r[0], r[1], r[2]))
    assert all(len(r) == len(COLUMNS) for r in records)
    # No stored parameter value appears in any cell, in any rendering.
    stored = {v for v in builder.values if v != 0.0}
    assert stored
    cells = {cell for r in records for cell in r}
    renderings = {f"{v}" for v in stored} | {f"{v:.4g}" for v in stored}
    assert not renderings & cells
    assert not any(str(v) in text for v in stored)
    # The text round-trips.
    metadata, rows = parse_manifest(text)
    assert metadata["store_sha256"] == sha256(builder.path)
    repo = SqliteSnapshotRepository(builder.path, read_only=True)
    assert rows == manifest_rows(repo, D)
    repo.close()
    # A second export refuses to overwrite.
    assert export_manifest.main([*args, "--out", str(out)]) == 2


@pytest.mark.parametrize(
    "git",
    [
        GitProvenance(commit="a" * 40, branch="x", dirty=True),
        GitProvenance(commit=None, branch=None, dirty=None),
    ],
)
def test_export_refuses_a_dirty_or_unknown_tree(
    builder: StoreBuilder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git: GitProvenance
) -> None:
    builder.add("ibm_fez", E_D - H, [], [E_D])
    builder.close()
    out = tmp_path / "m.csv"
    monkeypatch.setattr(export_manifest, "git_state", lambda: git)
    args = ["export", "--store", str(builder.path), "--collection-date", D.isoformat()]
    assert export_manifest.main([*args, "--out", str(out)]) == 2
    assert not out.exists()


def test_export_refuses_a_missing_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(export_manifest, "git_state", clean_git)
    store = tmp_path / "absent.db"
    args = ["export", "--store", str(store), "--collection-date", D.isoformat()]
    assert export_manifest.main([*args, "--out", str(tmp_path / "m.csv")]) == 2
    assert not store.exists()


def write_manifest(tmp_path: Path, builder: StoreBuilder) -> Path:
    path = tmp_path / "m.csv"
    path.write_text(render_manifest(manifest_rows(builder.repo, D), [("store_sha256", "x")]))
    return path


def test_verify_accepts_a_refetched_store_with_new_ids_and_the_same_hashes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    original = SqliteSnapshotRepository(tmp_path / "original.db")
    refetched = SqliteSnapshotRepository(tmp_path / "refetched.db")
    rows = [m(f"qubit/{q}", "T1", 71.3, E_D - H, "us") for q in FEZ_QUBITS]
    save(original, "A", "sha256:a", [E_D, E_D - H], stamp=E_D - 2 * H, rows=rows)
    save(original, "B", "sha256:b", [sparse_grid(D)[1]], stamp=E_D - 145 * H)
    # Re-fetched: other IDs, other capture times and order, and an extra lookup off the grid.
    save(refetched, "NEW-B", "sha256:b", [sparse_grid(D)[1]], first_capture=5)
    save(refetched, "NEW-A", "sha256:a", [E_D - H, E_D, E_D - 500 * H], first_capture=9)
    original.close()
    refetched.close()

    manifest = tmp_path / "m.csv"
    repo = SqliteSnapshotRepository(tmp_path / "original.db", read_only=True)
    manifest.write_text(render_manifest(manifest_rows(repo, D), [("store_sha256", "x")]))
    repo.close()
    before = sha256(tmp_path / "refetched.db")
    args = ["verify", "--manifest", str(manifest), "--store", str(tmp_path / "refetched.db")]
    assert export_manifest.main(args) == 0
    assert sha256(tmp_path / "refetched.db") == before
    out = capsys.readouterr().out
    assert "rows: 4; present 4, missing 0, differs 0" in out  # G_1 is in both sets
    assert "all present" in out
    assert "manifest store SHA-256: x" in out


def test_verify_reports_missing_and_differing_rows(
    builder: StoreBuilder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    save(builder.repo, "A", "sha256:a", [E_D, E_D - H], stamp=E_D - 2 * H)
    save(builder.repo, "B", "sha256:b", [E_D - 2 * H], stamp=E_D - 3 * H)
    manifest = write_manifest(tmp_path, builder)
    builder.close()

    other = SqliteSnapshotRepository(tmp_path / "other.db")
    save(other, "X", "sha256:a", [E_D])
    save(other, "Y", "sha256:changed", [E_D - H])
    # E_D - 2 h is not looked up at all.
    checks = verify_rows(other, parse_manifest(manifest.read_text())[1])
    other.close()
    by_time = {c.row.grid_time: c for c in checks}
    assert by_time[E_D].status == PRESENT
    assert by_time[E_D - H].status == DIFFERS
    assert by_time[E_D - H].found_hashes == ("sha256:changed",)
    assert by_time[E_D - 2 * H].status == MISSING

    args = ["verify", "--manifest", str(manifest), "--store", str(tmp_path / "other.db")]
    assert export_manifest.main(args) == 1
    out = capsys.readouterr().out
    assert "rows: 3; present 1, missing 1, differs 1" in out
    assert "(store has sha256:changed)" in out
    assert "all present" not in out


def test_verify_counts_a_duplicate_lookup_with_the_hash_as_present(
    builder: StoreBuilder, tmp_path: Path
) -> None:
    save(builder.repo, "A", "sha256:a", [E_D])
    manifest = write_manifest(tmp_path, builder)
    builder.close()
    other = SqliteSnapshotRepository(tmp_path / "other.db")
    save(other, "Z", "sha256:z", [E_D])
    save(other, "A2", "sha256:a", [E_D], first_capture=3)
    (check,) = verify_rows(other, parse_manifest(manifest.read_text())[1])
    other.close()
    assert check.status == PRESENT
    assert check.found_hashes == ("sha256:z", "sha256:a")


def test_parse_rejects_another_header() -> None:
    with pytest.raises(ValueError, match="manifest header"):
        parse_manifest("# store_sha256: x\ndevice,grid_time\n")
