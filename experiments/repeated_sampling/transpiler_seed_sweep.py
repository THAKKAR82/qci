"""Vary the transpiler seed with the simulator seed held fixed, and record what the
comparison does when the sampling floor is unavailable.

Usage, from the repository root::

    PYTHONPATH=src:experiments/repeated_sampling QCI_HOME=.qci-sweep \
        .venv/Scripts/python.exe experiments/repeated_sampling/transpiler_seed_sweep.py

Why this condition
------------------
Two runs that share a simulator seed are not independent samples: the comparison engine
refuses to compute a sampling floor for them, because the floor's null assumes independent
draws. Holding ``seed_simulator`` fixed and varying ``seed_transpiler`` therefore produces a
dataset in which every pair has a null floor and a stated reason.

That is the useful part. It exercises the path where the honest answer is "this quantity is
not available", and it produces the cross-compilation measurements -- same circuit, different
physical mapping -- for which no significance test exists. Observed TVD and Hellinger distance
are recorded as descriptive quantities with their method versions. No significance claim is
made, no threshold is applied, and no difference is attributed to routing.

Every pair is kept as a row. A dataset that dropped the pairs lacking a floor would be
shorter and would silently hide the condition under study.
"""

import sys
from pathlib import Path

from harness import (
    ExperimentSpec,
    Fixed,
    load_pairs,
    run_experiment,
)

#: Distinct transpiler seeds. Each produces a different physical mapping.
TRANSPILER_SEEDS = tuple(range(20))

#: Fixed across every run, so the simulator draws are not independent and no floor is computed.
SIMULATOR_SEED = 7

SHOTS = 1000
OPTIMIZATION_LEVEL = 2

STORE = Path(".qci-sweep")


def _spread(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    return min(values), max(values)


def main() -> int:
    spec = ExperimentSpec(
        name="transpiler-seed-sweep",
        varied_parameter="seed_transpiler",
        varied_values=TRANSPILER_SEEDS,
        fixed=Fixed(
            optimization_level=OPTIMIZATION_LEVEL,
            seed_transpiler=0,
            shots=SHOTS,
            seed_simulator=SIMULATOR_SEED,
        ),
    )
    out_dir = run_experiment(spec, STORE, reuse="--reuse" in sys.argv)

    rows = load_pairs(out_dir)
    with_floor = [r for r in rows if r["sampling_floor_p_value"]]
    tvds = [float(r["tvd"]) for r in rows if r["tvd"]]
    hellingers = [float(r["hellinger_distance"]) for r in rows if r["hellinger_distance"]]
    identical_resources = [r["footprint_resources_identical"] for r in rows]

    print(f"experiment: {spec.name}")
    print(f"  varied: {spec.varied_parameter} over {len(TRANSPILER_SEEDS)} values")
    print(
        f"  held fixed: shots={SHOTS}, optimization_level={OPTIMIZATION_LEVEL}, "
        f"seed_simulator={SIMULATOR_SEED}"
    )
    print(f"  rows in pairs.csv: {len(rows)}")
    print(f"  rows with a computed sampling floor: {len(with_floor)}")
    print(f"  rows without a floor (kept): {len(rows) - len(with_floor)}")
    reasons = sorted({r["sampling_floor_reason"] for r in rows if r["sampling_floor_reason"]})
    for reason in reasons:
        print(f"    reason: {reason}")
    print()
    print(
        f"  footprint resources identical: {identical_resources.count('true')}"
        f"/{len(identical_resources)} pairs"
    )
    tvd_lo, tvd_hi = _spread(tvds)
    hell_lo, hell_hi = _spread(hellingers)
    print(f"  TVD range: {tvd_lo} .. {tvd_hi}  (descriptive, no floor to compare against)")
    print(f"  Hellinger range: {hell_lo} .. {hell_hi}  (descriptive)")
    print()
    print("These are observed distances between different physical mappings of one circuit.")
    print("No floor exists for this condition, so no significance statement is available.")
    print(f"dataset: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
