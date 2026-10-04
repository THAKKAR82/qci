"""Create every run for the M1.1v-addendum sweep and write a run-ID manifest.

Usage (from the repository root, on a clean, committed tree):

    PYTHONPATH=src:experiments/repeated_sampling QCI_HOME=.qci-exp-addendum \
        .venv/bin/python experiments/repeated_sampling/run_addendum.py

Refuses to run if the git working tree is dirty (or its state is unknown), so every run records
``dirty=false``. Refuses to run if the store already holds a database or manifest, so a store
is never mixed across runs.
"""

import json
import sys
import time

from common import (
    ADDENDUM_OPTIMIZATION_LEVELS,
    ADDENDUM_STORE,
    ADDENDUM_TRANSPILER_SEEDS,
    BACKEND,
    REPO_ROOT,
    SHOTS,
    WORKLOAD,
    addendum_simulator_seed,
    db_path,
    manifest_path,
    store_dir,
)

from qci.adapters.qiskit_ibm import QiskitIbmAdapter
from qci.domain.circuit import CompileConfig
from qci.domain.execution import ExecutionConfig
from qci.domain.run import RunStatus
from qci.provenance.git import collect_git
from qci.services.run_service import RunRequest, RunService
from qci.storage.sqlite import SqliteRunRepository


def _run(service: RunService, opt: int, seed_transpiler: int, seed_simulator: int) -> str:
    run = service.run(
        RunRequest(
            workload_path=WORKLOAD,
            backend_name=BACKEND,
            compile_config=CompileConfig(optimization_level=opt, seed_transpiler=seed_transpiler),
            execution_config=ExecutionConfig(shots=SHOTS, seed_simulator=seed_simulator),
            tags={"experiment": "m1.1v-addendum", "set": f"sweep-o{opt}"},
        )
    )
    if run.status is not RunStatus.SUCCEEDED:
        raise RuntimeError(f"run {run.run_id} failed: {run.error}")
    return run.run_id


def main() -> int:
    git = collect_git(REPO_ROOT)
    if git.dirty is not False:
        print(
            f"error: git working tree is not clean (dirty={git.dirty}); commit first",
            file=sys.stderr,
        )
        return 2
    if db_path(ADDENDUM_STORE).exists() or manifest_path(ADDENDUM_STORE).exists():
        print(
            f"error: {store_dir(ADDENDUM_STORE)} is not empty; use a fresh QCI_HOME",
            file=sys.stderr,
        )
        return 2
    store_dir(ADDENDUM_STORE).mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    repository = SqliteRunRepository(db_path(ADDENDUM_STORE))
    service = RunService(QiskitIbmAdapter(), repository)
    sweep: dict[str, dict[str, str]] = {}
    try:
        for opt in ADDENDUM_OPTIMIZATION_LEVELS:
            sweep[str(opt)] = {
                str(seed_t): _run(service, opt, seed_t, addendum_simulator_seed(opt, seed_t))
                for seed_t in ADDENDUM_TRANSPILER_SEEDS
            }
            print(f"sweep level {opt}: {len(sweep[str(opt)])} runs", file=sys.stderr)
    finally:
        repository.close()
    elapsed = time.perf_counter() - start
    manifest = {"git_commit": git.commit, "run_seconds": round(elapsed, 1), "sweep": sweep}
    manifest_path(ADDENDUM_STORE).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(
        f"runs created in {elapsed:.1f} s; manifest: {manifest_path(ADDENDUM_STORE)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
