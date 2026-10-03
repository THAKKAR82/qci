"""Create every run for the M1.1v experiment and write a run-ID manifest.

Usage (from the repository root):

    PYTHONPATH=src:experiments/repeated_sampling QCI_HOME=.qci-exp \
        .venv/bin/python experiments/repeated_sampling/run_experiment.py

Refuses to run if the manifest already exists, so a store is never mixed across runs.
"""

import json
import sys
import time

from common import (
    BACKEND,
    GROUP_OPTIMIZATION_LEVEL,
    GROUP_SIMULATOR_SEEDS,
    GROUP_TRANSPILER_SEEDS,
    SHOTS,
    SWEEP_OPTIMIZATION_LEVELS,
    SWEEP_SIMULATOR_SEED,
    SWEEP_TRANSPILER_SEEDS,
    WORKLOAD,
    db_path,
    manifest_path,
    store_dir,
)

from qci.adapters.qiskit_ibm import QiskitIbmAdapter
from qci.domain.circuit import CompileConfig
from qci.domain.execution import ExecutionConfig
from qci.domain.run import RunStatus
from qci.services.run_service import RunRequest, RunService
from qci.storage.sqlite import SqliteRunRepository


def _run(service: RunService, opt: int, seed_transpiler: int, seed_simulator: int, tag: str) -> str:
    run = service.run(
        RunRequest(
            workload_path=WORKLOAD,
            backend_name=BACKEND,
            compile_config=CompileConfig(optimization_level=opt, seed_transpiler=seed_transpiler),
            execution_config=ExecutionConfig(shots=SHOTS, seed_simulator=seed_simulator),
            tags={"experiment": "m1.1v", "set": tag},
        )
    )
    if run.status is not RunStatus.SUCCEEDED:
        raise RuntimeError(f"run {run.run_id} failed: {run.error}")
    return run.run_id


def main() -> int:
    if manifest_path().exists():
        print(f"error: {manifest_path()} exists; use a fresh QCI_HOME", file=sys.stderr)
        return 2
    store_dir().mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    repository = SqliteRunRepository(db_path())
    service = RunService(QiskitIbmAdapter(), repository)
    groups: dict[str, dict[str, str]] = {}
    sweep: dict[str, dict[str, str]] = {}
    try:
        for name, seed_t in GROUP_TRANSPILER_SEEDS.items():
            groups[name] = {
                str(seed_s): _run(service, GROUP_OPTIMIZATION_LEVEL, seed_t, seed_s, f"group{name}")
                for seed_s in GROUP_SIMULATOR_SEEDS
            }
            print(f"group {name}: {len(groups[name])} runs", file=sys.stderr)
        for opt in SWEEP_OPTIMIZATION_LEVELS:
            sweep[str(opt)] = {
                str(seed_t): _run(service, opt, seed_t, SWEEP_SIMULATOR_SEED, f"sweep-o{opt}")
                for seed_t in SWEEP_TRANSPILER_SEEDS
            }
            print(f"sweep level {opt}: {len(sweep[str(opt)])} runs", file=sys.stderr)
    finally:
        repository.close()
    elapsed = time.perf_counter() - start
    manifest = {"groups": groups, "sweep": sweep, "run_seconds": round(elapsed, 1)}
    manifest_path().write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"runs created in {elapsed:.1f} s; manifest: {manifest_path()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
