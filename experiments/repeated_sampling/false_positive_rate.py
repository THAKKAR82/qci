"""Measure how often the TVD sampling floor reports a floor below alpha for pairs that
were drawn from one shared distribution.

Usage, from the repository root::

    PYTHONPATH=src:experiments/repeated_sampling QCI_HOME=.qci-fpr \
        .venv/Scripts/python.exe experiments/repeated_sampling/false_positive_rate.py

What this measures
------------------
Every run uses the same circuit, the same backend and the same compiler settings; only
``seed_simulator`` varies. Under that design every run samples one shared distribution, so
the correct answer for every pair is "no floor below alpha". The observed fraction is the
false-positive rate of the floor at the chosen alpha and shot count.

This is an experiment, not a product feature. It uses a static fake backend with a simulated
noise model, so nothing it produces is evidence about real hardware. It reports a rate. It
does not declare any run acceptable, and it does not attribute any difference to a cause.

Note on pairs: every pair is kept in ``pairs.csv``, but the pairs are not independent, because
runs are shared between them. A run appearing in 9 of 30 pairs links those pairs. Counts
computed over overlapping pairs therefore have an effective sample size below the row count,
and the spread across seeds should be read before any single number is quoted.
"""

import sys
from pathlib import Path

from harness import (
    ExperimentSpec,
    Fixed,
    load_pairs,
    p_values,
    run_experiment,
    summarise,
)

#: Distinct simulator seeds. Each becomes one run; all pairs are compared.
SEEDS = tuple(range(1, 31))

#: Shots per run. The false-positive rate depends on this, so it is fixed and recorded.
SHOTS = 1000

#: Alpha is a reporting threshold for this script only. It is never written into the dataset.
ALPHA = 0.05

STORE = Path(".qci-fpr")


def main() -> int:
    spec = ExperimentSpec(
        name="fpr-seed-simulator",
        varied_parameter="seed_simulator",
        varied_values=SEEDS,
        fixed=Fixed(optimization_level=2, seed_transpiler=7, shots=SHOTS),
    )
    out_dir = run_experiment(spec, STORE, reuse="--reuse" in sys.argv)

    rows = load_pairs(out_dir)
    computed = p_values(out_dir)
    stats = summarise(computed, ALPHA)

    print(f"experiment: {spec.name}")
    print(f"  varied: {spec.varied_parameter} over {len(SEEDS)} values")
    print(f"  held fixed: shots={SHOTS}, optimization_level=2, seed_transpiler=7")
    print(f"  rows in pairs.csv: {len(rows)}")
    print(f"  pairs with a computed floor: {stats['computed_pairs']}")
    skipped = len(rows) - stats["computed_pairs"]
    if skipped:
        reasons = sorted(
            {row["sampling_floor_reason"] for row in rows if not row["sampling_floor_p_value"]}
        )
        print(f"  pairs without a floor (kept as rows): {skipped}")
        for reason in reasons:
            print(f"    reason: {reason}")
    print(f"  floor p-value < {ALPHA}: {stats['below_alpha']}")
    print(f"  fraction: {stats['fraction_below_alpha']}")
    print()
    print("A fraction near alpha is what a correctly calibrated floor looks like here.")
    print("Pairs overlap, so the row count overstates the independent sample size.")
    print(f"dataset: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
