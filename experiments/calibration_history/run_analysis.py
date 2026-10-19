"""Run the M1.5d analysis once on a store, read-only.

Usage (from the repository root, on a clean tree):

    PYTHONPATH=src:experiments/calibration_history .venv/bin/python \
        experiments/calibration_history/run_analysis.py \
        --store ~/.qci-live/qci.db --collection-date YYYY-MM-DD --out ~/qci-m15d

Writes ``results.json`` and ``results.md`` to ``--out`` and refuses to overwrite them. Refuses
to run on a dirty tree. Prints the store's SHA-256 before and after, the commit and the dirty
flag, and exits non-zero if the store changed. See
docs/experiments/2026-10-calibration-history.md.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from history_analysis import analyze, render_markdown

from qci.domain.provenance import GitProvenance
from qci.provenance.git import collect_git
from qci.storage.snapshots import SqliteSnapshotRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_JSON = "results.json"
RESULTS_MD = "results.md"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state() -> GitProvenance:
    return collect_git(REPO_ROOT)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the M1.5d analysis once on a store, read-only."
    )
    parser.add_argument("--store", type=Path, required=True, help="path to qci.db")
    parser.add_argument(
        "--collection-date",
        type=date.fromisoformat,
        required=True,
        help="D: the UTC date recorded before the first dense invocation (YYYY-MM-DD)",
    )
    parser.add_argument("--out", type=Path, required=True, help="directory for the results")
    args = parser.parse_args(argv)
    store: Path = args.store.expanduser()
    out: Path = args.out.expanduser()

    git = git_state()
    if git.commit is None or git.dirty is not False:
        print(
            "refusing to run: the analysis must run from a clean, committed tree "
            f"(commit={git.commit}, dirty={git.dirty})",
            file=sys.stderr,
        )
        return 2
    if not store.is_file():
        print(f"refusing to run: no store at {store}", file=sys.stderr)
        return 2
    targets = [out / RESULTS_JSON, out / RESULTS_MD]
    existing = [str(p) for p in targets if p.exists()]
    if existing:
        print(f"refusing to overwrite {', '.join(existing)}", file=sys.stderr)
        return 2

    before = sha256_file(store)
    print(f"store SHA-256 before: {before}")
    repository = SqliteSnapshotRepository(store, read_only=True)
    try:
        result = analyze(repository, args.collection_date)
    finally:
        repository.close()
    after = sha256_file(store)
    print(f"store SHA-256 after:  {after}")
    print(f"git commit: {git.commit}  dirty: {git.dirty}")
    p3 = result["predictions"]["P3"]
    reference = p3["random_order_reference"]
    print(
        f"P3 overall: {p3['overall']}; P(tau-b < 0.5) under a uniformly random relative "
        f"ordering of {reference['untied_items']} untied qubits: "
        f"{reference['below']}/{reference['orderings']} = {reference['probability']:.4g} "
        "(interpretation only)"
    )

    result["provenance"] = {
        "store_path": str(store),
        "store_sha256_before": before,
        "store_sha256_after": after,
        "store_unchanged": before == after,
        "git_commit": git.commit,
        "git_branch": git.branch,
        "git_dirty": git.dirty,
    }
    out.mkdir(parents=True, exist_ok=True)
    targets[0].write_text(json.dumps(result, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    targets[1].write_text(render_markdown(result) + "\n", encoding="utf-8")
    print(f"wrote {targets[0]} and {targets[1]}")
    if before != after:
        print("the store changed during the analysis", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
