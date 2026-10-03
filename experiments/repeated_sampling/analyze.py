"""Analyze the M1.1v runs: sampling-floor comparisons, pooled comparison, P5, D1 and D2.

Usage (from the repository root, after run_experiment.py):

    PYTHONPATH=src:experiments/repeated_sampling QCI_HOME=.qci-exp \
        .venv/bin/python experiments/repeated_sampling/analyze.py > .qci-exp/results.md

Writes Markdown tables to stdout and the full numbers to ``$QCI_HOME/results.json``. Pairwise
comparisons go through ``CompareService``. The pooled comparison and the P5 recomputation call
``tvd_sampling_floor`` directly with the fixed seeds in ``common.py``.
"""

import json
import math
import statistics
import sys
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from itertools import combinations
from typing import Any

from common import (
    GROUP_SIMULATOR_SEEDS,
    P5_SEEDS,
    POOLED_SEED,
    RESAMPLES,
    SWEEP_OPTIMIZATION_LEVELS,
    SWEEP_TRANSPILER_SEEDS,
    db_path,
    manifest_path,
    store_dir,
)

from qci.adapters.qiskit_ibm.adapter_ids import PROVIDER_ID
from qci.adapters.qiskit_ibm.calibration import IbmPropertiesCalibrationReader
from qci.compare.distribution import p_value_standard_error
from qci.compare.divergence import hellinger_distance
from qci.compare.sampling import tvd_sampling_floor
from qci.core.hashing import sha256_hex
from qci.domain.run import Run
from qci.services.compare_service import CompareService
from qci.storage.sqlite import SqliteRunRepository

GHZ_OUTCOMES = ("00000", "11111")

Row = dict[str, Any]


def counts_of(run: Run) -> dict[str, int]:
    assert run.result is not None and len(run.result.counts) == 1
    return dict(next(iter(run.result.counts.values())))


def transpiled_hash(run: Run) -> str | None:
    assert run.compilation is not None
    qasm = run.compilation.output.qasm3
    return sha256_hex(qasm.encode("utf-8")) if qasm is not None else None


def metric_value(metric: Any) -> float:
    assert metric is not None
    return float(metric.value)


def compare_pair(service: CompareService, runs: dict[str, Run], b_id: str, c_id: str) -> Row:
    cmp = service.compare(b_id, c_id)
    dist = cmp.distribution
    floor = dist.sampling_floor
    assert floor is not None, f"no sampling floor for {b_id} -> {c_id}: {dist.reasons}"
    tvd = metric_value(dist.tvd)
    p95 = metric_value(floor.null_p95)
    p = metric_value(floor.p_value)
    return {
        "baseline": b_id,
        "candidate": c_id,
        "status": dist.status.value,
        "tvd": tvd,
        "hellinger": metric_value(dist.hellinger_distance),
        "null_p50": metric_value(floor.null_p50),
        "null_p95": p95,
        "null_p99": metric_value(floor.null_p99),
        "p_value": p,
        "p_value_se": floor.p_value.uncertainty,
        "seed": floor.seed,
        "exceeds_p95": tvd > p95,
        "identical_transpiled": transpiled_hash(runs[b_id]) == transpiled_hash(runs[c_id]),
        "resources_identical": cmp.footprint.resources_identical,
    }


def deciles(values: Iterable[float]) -> list[int]:
    bins = [0] * 10
    for v in values:
        bins[min(int(v * 10), 9)] += 1
    return bins


def summary(values: Sequence[float]) -> Row:
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "max": max(values),
    }


def merge(counts: Iterable[dict[str, int]]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for c in counts:
        total.update(c)
    return dict(total)


def population(counts: dict[str, int]) -> tuple[float, float, int]:
    n = sum(counts.values())
    p = sum(counts.get(k, 0) for k in GHZ_OUTCOMES) / n
    return p, math.sqrt(p * (1 - p) / n), n


def p5_stability(b: dict[str, int], c: dict[str, int]) -> Row:
    ps = [tvd_sampling_floor(b, c, resamples=RESAMPLES, seed=s).p_value for s in P5_SEEDS]
    mean = statistics.fmean(ps)
    sd = statistics.stdev(ps)
    se = p_value_standard_error(mean, RESAMPLES)
    return {
        "seeds": list(P5_SEEDS),
        "p_values": ps,
        "mean": mean,
        "sd": sd,
        "se_at_mean": se,
        "ratio": sd / se if se > 0 else None,
    }


# --- Markdown -------------------------------------------------------------------------------


def f4(x: float | None) -> str:
    return "-" if x is None else f"{x:.4f}"


def table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def main() -> int:
    start = time.perf_counter()
    manifest = json.loads(manifest_path().read_text())
    groups: dict[str, dict[str, str]] = manifest["groups"]
    sweep: dict[str, dict[str, str]] = manifest["sweep"]

    repository = SqliteRunRepository(db_path())
    try:
        all_ids = [i for g in (*groups.values(), *sweep.values()) for i in g.values()]
        runs = {i: repository.get(i) for i in all_ids}
        service = CompareService(repository, {PROVIDER_ID: IbmPropertiesCalibrationReader()})
        seeds = [str(s) for s in GROUP_SIMULATOR_SEEDS]

        within: dict[str, list[Row]] = {}
        for name, by_seed in groups.items():
            within[name] = []
            for i, j in combinations(seeds, 2):
                row = compare_pair(service, runs, by_seed[i], by_seed[j])
                row |= {"baseline_sim_seed": int(i), "candidate_sim_seed": int(j)}
                within[name].append(row)

        between: list[Row] = []
        for i in seeds:
            for j in seeds:
                row = compare_pair(service, runs, groups["A"][i], groups["B"][j])
                row |= {"baseline_sim_seed": int(i), "candidate_sim_seed": int(j)}
                between.append(row)

        sweep_rows: dict[str, list[Row]] = {}
        for opt in (str(o) for o in SWEEP_OPTIMIZATION_LEVELS):
            ref = sweep[opt]["0"]
            sweep_rows[opt] = []
            for s in (str(t) for t in SWEEP_TRANSPILER_SEEDS if t != 0):
                row = compare_pair(service, runs, ref, sweep[opt][s])
                row |= {"candidate_seed_transpiler": int(s)}
                sweep_rows[opt].append(row)
    finally:
        repository.close()

    group_counts = {n: {s: counts_of(runs[g[s]]) for s in seeds} for n, g in groups.items()}
    pooled_a = merge(group_counts["A"].values())
    pooled_b = merge(group_counts["B"].values())
    pf = tvd_sampling_floor(pooled_a, pooled_b, resamples=RESAMPLES, seed=POOLED_SEED)
    pooled_hellinger = hellinger_distance(
        {k: v / pf.baseline_shots for k, v in pooled_a.items()},
        {k: v / pf.candidate_shots for k, v in pooled_b.items()},
    )
    pooled: Row = {
        "observed_tvd": pf.observed_tvd,
        "hellinger": pooled_hellinger,
        "null_p50": pf.null_p50,
        "null_p95": pf.null_p95,
        "null_p99": pf.null_p99,
        "p_value": pf.p_value,
        "p_value_se": p_value_standard_error(pf.p_value, pf.resamples),
        "seed": pf.seed,
        "resamples": pf.resamples,
        "shots": [pf.baseline_shots, pf.candidate_shots],
        "outcomes": pf.outcomes,
    }

    p5 = {
        "pooled_A_vs_B": p5_stability(pooled_a, pooled_b),
        "groupA_sim1_vs_sim2": p5_stability(group_counts["A"]["1"], group_counts["A"]["2"]),
    }

    d1_runs = {n: {s: population(group_counts[n][s]) for s in seeds} for n in group_counts}
    pa, sea, _ = population(pooled_a)
    pb, seb, _ = population(pooled_b)
    d1_pooled = {
        "A": [pa, sea],
        "B": [pb, seb],
        "diff_B_minus_A": [pb - pa, math.sqrt(sea**2 + seb**2)],
    }

    d2 = {
        "within_A": summary([r["hellinger"] for r in within["A"]]),
        "within_B": summary([r["hellinger"] for r in within["B"]]),
        "between": summary([r["hellinger"] for r in between]),
        "pooled": pooled_hellinger,
    }

    group_hashes = {
        n: sorted({transpiled_hash(runs[i]) or "-" for i in g.values()}) for n, g in groups.items()
    }
    analysis_seconds = time.perf_counter() - start

    results = {
        "within": within,
        "between": between,
        "pooled": pooled,
        "sweep": sweep_rows,
        "p5": p5,
        "d1_runs": d1_runs,
        "d1_pooled": d1_pooled,
        "d2": d2,
        "group_transpiled_hashes": group_hashes,
        "run_seconds": manifest.get("run_seconds"),
        "analysis_seconds": round(analysis_seconds, 1),
    }
    (store_dir() / "results.json").write_text(json.dumps(results, indent=2) + "\n")

    out: list[str] = []
    emit = out.append
    emit("### Transpiled circuits per group\n")
    for n, hashes in group_hashes.items():
        emit(
            f"- Group {n}: {len(hashes)} distinct transpiled qasm3 hash(es): "
            + ", ".join(f"`{h[:12]}`" for h in hashes)
        )
    emit("")

    for n, rows in within.items():
        exceed = sum(r["exceeds_p95"] for r in rows)
        low = sum(r["p_value"] < 0.1 for r in rows)
        emit(f"### Within Group {n} (45 pairs)\n")
        emit(
            f"Exceedances of null p95: **{exceed}/45**. p-values below 0.1: **{low}/45**. "
            f"p < 0.05: {sum(r['p_value'] < 0.05 for r in rows)}/45.\n"
        )
        emit("p-value deciles [0,0.1) ... [0.9,1.0]: " + str(deciles(r["p_value"] for r in rows)))
        emit("")
        emit(
            table(
                [
                    "b sim",
                    "c sim",
                    "TVD",
                    "null p50",
                    "null p95",
                    "null p99",
                    "p",
                    "p SE",
                    "> p95",
                    "Hellinger",
                    "seed",
                ],
                [
                    [
                        r["baseline_sim_seed"],
                        r["candidate_sim_seed"],
                        f4(r["tvd"]),
                        f4(r["null_p50"]),
                        f4(r["null_p95"]),
                        f4(r["null_p99"]),
                        f4(r["p_value"]),
                        f4(r["p_value_se"]),
                        "yes" if r["exceeds_p95"] else "no",
                        f4(r["hellinger"]),
                        r["seed"],
                    ]
                    for r in rows
                ],
            )
        )
        emit("")

    emit("### Between groups, A (baseline) vs B (candidate), 100 pairs\n")
    exceed_b = sum(r["exceeds_p95"] for r in between)
    emit(
        f"Exceedances of null p95: **{exceed_b}/100**. p < 0.05: "
        f"{sum(r['p_value'] < 0.05 for r in between)}/100. p < 0.1: "
        f"{sum(r['p_value'] < 0.1 for r in between)}/100. Identical transpiled circuits: "
        f"{sum(r['identical_transpiled'] for r in between)}/100. Footprint resources identical: "
        f"{sum(bool(r['resources_identical']) for r in between)}/100.\n"
    )
    emit("p-value deciles [0,0.1) ... [0.9,1.0]: " + str(deciles(r["p_value"] for r in between)))
    p_summary = {k: round(v, 4) for k, v in summary([r["p_value"] for r in between]).items()}
    emit(f"\np-value summary: {json.dumps(p_summary)}\n")
    for label, key in (("TVD", "tvd"), ("p-value", "p_value")):
        emit(f"{label} matrix (rows: A simulator seed, columns: B simulator seed):\n")
        emit(
            table(
                ["A \\ B", *seeds],
                [
                    [i, *(f4(r[key]) for r in between[k * 10 : (k + 1) * 10])]
                    for k, i in enumerate(seeds)
                ],
            )
        )
        emit("")

    emit("### Pooled A vs B (10 runs merged per group)\n")
    emit(
        table(
            [
                "shots (A, B)",
                "outcomes",
                "TVD",
                "null p50",
                "null p95",
                "null p99",
                "p",
                "p SE",
                "B",
                "seed",
            ],
            [
                [
                    f"{pooled['shots'][0]}, {pooled['shots'][1]}",
                    pooled["outcomes"],
                    f4(pooled["observed_tvd"]),
                    f4(pooled["null_p50"]),
                    f4(pooled["null_p95"]),
                    f4(pooled["null_p99"]),
                    f4(pooled["p_value"]),
                    f4(pooled["p_value_se"]),
                    pooled["resamples"],
                    pooled["seed"],
                ]
            ],
        )
    )
    emit("")

    for opt, rows in sweep_rows.items():
        ident = [r for r in rows if r["identical_transpiled"]]
        diff_fp = [r for r in rows if r["resources_identical"] is False]
        emit(f"### Compilation sweep, optimization level {opt} (baseline transpiler seed 0)\n")
        emit(
            f"Identical transpiled circuits: {len(ident)}/29 "
            f"(p-values: {sorted({f4(r['p_value']) for r in ident}) or '-'}). "
            f"Different physical footprints: {len(diff_fp)}/29, of which exceed null p95: "
            f"{sum(r['exceeds_p95'] for r in diff_fp)}.\n"
        )
        emit(
            table(
                [
                    "c seed_t",
                    "identical qasm3",
                    "resources identical",
                    "TVD",
                    "null p95",
                    "p",
                    "p SE",
                    "> p95",
                    "Hellinger",
                ],
                [
                    [
                        r["candidate_seed_transpiler"],
                        "yes" if r["identical_transpiled"] else "no",
                        r["resources_identical"],
                        f4(r["tvd"]),
                        f4(r["null_p95"]),
                        f4(r["p_value"]),
                        f4(r["p_value_se"]),
                        "yes" if r["exceeds_p95"] else "no",
                        f4(r["hellinger"]),
                    ]
                    for r in rows
                ],
            )
        )
        emit("")

    emit(
        f"### P5: Monte Carlo stability (B={RESAMPLES}, seeds "
        f"{P5_SEEDS.start}-{P5_SEEDS.stop - 1})\n"
    )
    emit(
        table(
            ["counts", "mean p", "SD of p", "SE at mean p", "SD / SE"],
            [
                [k, f4(v["mean"]), f4(v["sd"]), f4(v["se_at_mean"]), f4(v["ratio"])]
                for k, v in p5.items()
            ],
        )
    )
    emit("")
    for k, v in p5.items():
        emit(
            f"- {k} p-values by seed: "
            + ", ".join(f"{s}: {p:.4f}" for s, p in zip(v["seeds"], v["p_values"], strict=True))
        )
    emit("")

    emit("### D1: GHZ population P(00000) + P(11111) (descriptive)\n")
    emit(
        table(
            ["sim seed", "A population", "A SE", "B population", "B SE"],
            [
                [
                    s,
                    f4(d1_runs["A"][s][0]),
                    f4(d1_runs["A"][s][1]),
                    f4(d1_runs["B"][s][0]),
                    f4(d1_runs["B"][s][1]),
                ]
                for s in seeds
            ],
        )
    )
    emit("")
    emit(
        table(
            ["quantity", "value", "SE"],
            [
                ["pooled A (10000 shots)", f4(pa), f4(sea)],
                ["pooled B (10000 shots)", f4(pb), f4(seb)],
                ["B minus A", f4(pb - pa), f4(d1_pooled["diff_B_minus_A"][1])],
            ],
        )
    )
    emit("")

    emit("### D2: Hellinger distance (descriptive, no sampling floor)\n")
    emit(
        table(
            ["set", "n", "min", "median", "mean", "max"],
            [
                [k, v["n"], f4(v["min"]), f4(v["median"]), f4(v["mean"]), f4(v["max"])]
                for k, v in d2.items()
                if isinstance(v, dict)
            ],
        )
    )
    emit(f"\nPooled A vs B Hellinger distance: {f4(pooled_hellinger)}\n")

    emit(
        f"Runtime: run creation {manifest.get('run_seconds')} s, analysis {analysis_seconds:.1f} s."
    )
    print("\n".join(out))
    print(f"analysis finished in {analysis_seconds:.1f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
