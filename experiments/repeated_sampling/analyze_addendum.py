"""Analyze the M1.1v-addendum sweep: P6, P7 and the GHZ population per run.

Usage (from the repository root, after run_addendum.py):

    PYTHONPATH=src:experiments/repeated_sampling QCI_HOME=.qci-exp-addendum \
        .venv/bin/python experiments/repeated_sampling/analyze_addendum.py \
        > .qci-exp-addendum/results.md

Writes Markdown tables to stdout and the full numbers to ``$QCI_HOME/results.json``. Each run
is compared through ``CompareService`` against the transpiler-seed-0 run of its level. The P6
marking rule is the one pre-registered in docs/experiments/2026-10-repeated-sampling.md, and
is applied here mechanically.
"""

import json
import math
import sys
import time
from typing import Any

from analyze import Row, compare_pair, counts_of, deciles, f4, population, table
from common import ADDENDUM_STORE, ADDENDUM_TRANSPILER_SEEDS, db_path, manifest_path, store_dir

from qci.adapters.qiskit_ibm.adapter_ids import PROVIDER_ID
from qci.adapters.qiskit_ibm.calibration import IbmPropertiesCalibrationReader
from qci.domain.run import Run
from qci.services.compare_service import CompareService
from qci.storage.sqlite import SqliteRunRepository

P6_MIN_PAIRS = 5
P6_TAIL = 0.025


def binomial_tail(n: int, q: float, k: int) -> float:
    """P(X >= k) for X ~ Binomial(n, q)."""
    return sum(math.comb(n, i) * q**i * (1 - q) ** (n - i) for i in range(k, n + 1))


def not_matched_threshold(n: int, q: float) -> int:
    """Smallest k with P(Binomial(n, q) >= k) < P6_TAIL."""
    return next(k for k in range(n + 2) if binomial_tail(n, q, k) < P6_TAIL)


def seeds_of(run: Run) -> tuple[int | None, int | None]:
    assert run.compilation is not None and run.execution is not None
    return run.compilation.config.seed_transpiler, run.execution.config.seed_simulator


def mark_p6(p_values: list[float]) -> dict[str, Any]:
    n = len(p_values)
    low = sum(p < 0.05 for p in p_values)
    high = sum(p >= 0.9 for p in p_values)
    if n < P6_MIN_PAIRS:
        return {"n": n, "low": low, "high": high, "marking": "inconclusive"}
    low_t = not_matched_threshold(n, 0.05)
    high_t = not_matched_threshold(n, 0.10)
    marking = "not matched" if low >= low_t or high >= high_t else "matched"
    return {
        "n": n,
        "low": low,
        "high": high,
        "low_threshold": low_t,
        "high_threshold": high_t,
        "marking": marking,
    }


def main() -> int:
    start = time.perf_counter()
    manifest = json.loads(manifest_path(ADDENDUM_STORE).read_text())
    sweep: dict[str, dict[str, str]] = manifest["sweep"]

    repository = SqliteRunRepository(db_path(ADDENDUM_STORE))
    try:
        all_ids = [i for level in sweep.values() for i in level.values()]
        runs = {i: repository.get(i) for i in all_ids}
        service = CompareService(repository, {PROVIDER_ID: IbmPropertiesCalibrationReader()})
        rows: dict[str, list[Row]] = {}
        for opt, by_seed in sweep.items():
            ref = by_seed["0"]
            rows[opt] = []
            for s in (str(t) for t in ADDENDUM_TRANSPILER_SEEDS if t != 0):
                rows[opt].append(compare_pair(service, runs, ref, by_seed[s]))
    finally:
        repository.close()

    sim_seeds = [seeds_of(r)[1] for r in runs.values()]
    assert len(set(sim_seeds)) == len(sim_seeds), "simulator seeds are not distinct"
    git = [r.provenance.git for r in runs.values()]
    provenance: Row = {
        "runs": len(git),
        "dirty_false": sum(g.dirty is False for g in git),
        "commits": sorted({g.commit or "-" for g in git}),
        "branches": sorted({g.branch or "-" for g in git}),
    }

    pops = {i: population(counts_of(r)) for i, r in runs.items()}
    for opt, level_rows in rows.items():
        pb, seb, _ = pops[sweep[opt]["0"]]
        for row in level_rows:
            run = runs[row["candidate"]]
            pc, sec, _ = pops[row["candidate"]]
            row |= {
                "candidate_seed_transpiler": seeds_of(run)[0],
                "candidate_seed_simulator": seeds_of(run)[1],
                "ghz_population": pc,
                "ghz_population_se": sec,
                "ghz_diff": pc - pb,
                "ghz_diff_se": math.sqrt(seb**2 + sec**2),
            }

    identical = [
        (opt, r)
        for opt, level_rows in rows.items()
        for r in level_rows
        if r["identical_transpiled"]
    ]
    p6 = mark_p6([r["p_value"] for _, r in identical])
    p7: dict[str, Row] = {}
    for opt, level_rows in rows.items():
        different = [r for r in level_rows if not r["identical_transpiled"]]
        low = sum(r["p_value"] < 0.05 for r in different)
        p7[opt] = {
            "different_pairs": len(different),
            "p_below_0_05": low,
            "fraction": low / len(different) if different else None,
            "deciles": deciles(r["p_value"] for r in different),
            "exceeds_p95": sum(r["exceeds_p95"] for r in different),
        }
    analysis_seconds = time.perf_counter() - start

    results = {
        "provenance": provenance,
        "baselines": {
            opt: {"run_id": sweep[opt]["0"], "ghz": pops[sweep[opt]["0"]]} for opt in sweep
        },
        "sweep": rows,
        "p6": p6,
        "p7": p7,
        "run_seconds": manifest.get("run_seconds"),
        "analysis_seconds": round(analysis_seconds, 1),
    }
    (store_dir(ADDENDUM_STORE) / "results.json").write_text(json.dumps(results, indent=2) + "\n")

    out: list[str] = []
    emit = out.append
    emit("### Provenance\n")
    emit(
        f"Runs: {provenance['runs']}. Runs with git `dirty=false`: {provenance['dirty_false']}. "
        f"Recorded commits: {', '.join(f'`{c}`' for c in provenance['commits'])}. "
        f"Branches: {', '.join(provenance['branches'])}. Distinct simulator seeds: "
        f"{len(set(sim_seeds))}/{len(sim_seeds)}.\n"
    )

    emit("### P6: pairs with identical transpiled circuits\n")
    thresholds = (
        f"not-matched thresholds: p < 0.05 count >= {p6['low_threshold']}, "
        f"p >= 0.9 count >= {p6['high_threshold']}"
        if "low_threshold" in p6
        else f"fewer than {P6_MIN_PAIRS} pairs"
    )
    emit(
        f"Identical-circuit pairs: **{p6['n']}**. p < 0.05: **{p6['low']}**. p >= 0.9: "
        f"**{p6['high']}**. Rule ({thresholds}): **{p6['marking']}**.\n"
    )
    emit(
        table(
            ["level", "c seed_t", "b seed_s", "c seed_s", "TVD", "null p95", "p", "p SE", "> p95"],
            [
                [
                    opt,
                    r["candidate_seed_transpiler"],
                    seeds_of(runs[r["baseline"]])[1],
                    r["candidate_seed_simulator"],
                    f4(r["tvd"]),
                    f4(r["null_p95"]),
                    f4(r["p_value"]),
                    f4(r["p_value_se"]),
                    "yes" if r["exceeds_p95"] else "no",
                ]
                for opt, r in identical
            ],
        )
    )
    emit("")

    emit("### P7: pairs with different transpiled circuits, per optimization level\n")
    emit(
        table(
            [
                "level",
                "pairs",
                "p < 0.05",
                "fraction",
                "> null p95",
                "p deciles [0,0.1) ... [0.9,1.0]",
            ],
            [
                [
                    opt,
                    v["different_pairs"],
                    v["p_below_0_05"],
                    f4(v["fraction"]),
                    v["exceeds_p95"],
                    v["deciles"],
                ]
                for opt, v in p7.items()
            ],
        )
    )
    emit("")

    for opt, level_rows in rows.items():
        pb, seb, _ = pops[sweep[opt]["0"]]
        emit(f"### Sweep, optimization level {opt} (baseline transpiler seed 0)\n")
        emit(
            f"Baseline simulator seed {seeds_of(runs[sweep[opt]['0']])[1]}, GHZ population "
            f"{f4(pb)} (SE {f4(seb)}). GHZ diff is candidate minus baseline.\n"
        )
        emit(
            table(
                [
                    "c seed_t",
                    "c seed_s",
                    "identical qasm3",
                    "resources identical",
                    "TVD",
                    "null p95",
                    "p",
                    "p SE",
                    "> p95",
                    "Hellinger",
                    "GHZ pop",
                    "GHZ SE",
                    "GHZ diff",
                    "diff SE",
                ],
                [
                    [
                        r["candidate_seed_transpiler"],
                        r["candidate_seed_simulator"],
                        "yes" if r["identical_transpiled"] else "no",
                        r["resources_identical"],
                        f4(r["tvd"]),
                        f4(r["null_p95"]),
                        f4(r["p_value"]),
                        f4(r["p_value_se"]),
                        "yes" if r["exceeds_p95"] else "no",
                        f4(r["hellinger"]),
                        f4(r["ghz_population"]),
                        f4(r["ghz_population_se"]),
                        f"{r['ghz_diff']:+.4f}",
                        f4(r["ghz_diff_se"]),
                    ]
                    for r in level_rows
                ],
            )
        )
        emit("")

    emit(
        f"Runtime: run creation {manifest.get('run_seconds')} s, analysis {analysis_seconds:.1f} s."
    )
    print("\n".join(out))
    print(f"analysis finished in {analysis_seconds:.1f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
