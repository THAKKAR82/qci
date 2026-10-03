"""Shared configuration for the M1.1v repeated-sampling experiment.

See docs/experiments/2026-10-repeated-sampling.md. Scripts use the service API, never the CLI,
and write to a separate store (``QCI_HOME``, default ``.qci-exp``).
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKLOAD = REPO_ROOT / "examples" / "ghz_star.py"
BACKEND = "fake_sherbrooke"
SHOTS = 1000

GROUP_OPTIMIZATION_LEVEL = 2
GROUP_TRANSPILER_SEEDS = {"A": 7, "B": 0}
GROUP_SIMULATOR_SEEDS = range(1, 11)

SWEEP_OPTIMIZATION_LEVELS = (1, 2, 3)
SWEEP_TRANSPILER_SEEDS = range(30)
SWEEP_SIMULATOR_SEED = 7

RESAMPLES = 2000
POOLED_SEED = 20261003
P5_SEEDS = range(1000, 1020)

MANIFEST_NAME = "manifest.json"


def store_dir() -> Path:
    home = os.environ.get("QCI_HOME")
    return Path(home) if home else REPO_ROOT / ".qci-exp"


def db_path() -> Path:
    return store_dir() / "qci.db"


def manifest_path() -> Path:
    return store_dir() / MANIFEST_NAME
