"""Shared configuration for the M1.1v repeated-sampling experiment and its addendum.

See docs/experiments/2026-10-repeated-sampling.md. Scripts use the service API, never the CLI,
and write to a separate store (``QCI_HOME``; default ``.qci-exp``, or ``.qci-exp-addendum``
for the addendum).
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

# M1.1v-addendum: the sweep rerun with a distinct simulator seed per run.
ADDENDUM_OPTIMIZATION_LEVELS = (1, 2, 3)
ADDENDUM_TRANSPILER_SEEDS = range(30)
ADDENDUM_STORE = ".qci-exp-addendum"

MANIFEST_NAME = "manifest.json"
DEFAULT_STORE = ".qci-exp"


def addendum_simulator_seed(optimization_level: int, seed_transpiler: int) -> int:
    """Simulator seed for an addendum run: distinct for every (level, transpiler seed)."""
    return 1000 + 100 * optimization_level + seed_transpiler


def store_dir(default: str = DEFAULT_STORE) -> Path:
    home = os.environ.get("QCI_HOME")
    return Path(home) if home else REPO_ROOT / default


def db_path(default: str = DEFAULT_STORE) -> Path:
    return store_dir(default) / "qci.db"


def manifest_path(default: str = DEFAULT_STORE) -> Path:
    return store_dir(default) / MANIFEST_NAME
