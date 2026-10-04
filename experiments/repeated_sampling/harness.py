"""Reusable harness for repeated-execution experiments over stored Runs.

One question shape: hold the circuit and backend fixed, vary exactly one recorded parameter
over N values, compare every pair, and emit a structured dataset.

What this module deliberately does NOT do, per ``CLAUDE.md``:

* It does not modify ``src/`` or any comparison rule. ``ComparisonPolicy`` is read from the
  comparison itself.
* It does not declare a regression threshold, a pass/fail verdict, or any better/worse
  language. It records numbers and leaves the counting to a reader.
* It does not attribute a difference to a cause. Each row records what was varied and what
  was held fixed, which is an experimental record, not an explanation.

Stored and derived facts are kept in separate tables and never mixed. ``runs.csv`` holds only
values read off a persisted ``Run``; ``pairs.csv`` holds only values produced by
``CompareService`` for one pair, each carrying the method version the engine recorded.

A pair whose sampling floor was not computed is kept as a row with a null floor and a reason.
Rows are never dropped for being inconvenient: a shortened dataset is indistinguishable from
a biased one.
"""

import csv
import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qci.adapters.qiskit_ibm import QiskitIbmAdapter
from qci.adapters.qiskit_ibm.adapter_ids import PROVIDER_ID
from qci.adapters.qiskit_ibm.calibration import IbmPropertiesCalibrationReader
from qci.domain.circuit import CompileConfig
from qci.domain.comparison import Comparison
from qci.domain.execution import ExecutionConfig
from qci.domain.run import Run, RunStatus
from qci.provenance.environment import collect_environment
from qci.services.compare_service import CompareService
from qci.services.run_service import RunRequest, RunService
from qci.storage.sqlite import SqliteRunRepository

SCHEMA_VERSION = "qci.experiment.v1"
"""Bumped when the column set of the emitted CSV files changes."""

#: Parameters this harness knows how to vary, mapped to the field each one is recorded in.
VARIABLE_FIELDS: dict[str, str] = {
    "seed_simulator": "ExecutionConfig.seed_simulator",
    "seed_transpiler": "CompileConfig.seed_transpiler",
    "optimization_level": "CompileConfig.optimization_level",
    "shots": "ExecutionConfig.shots",
}


@dataclass(frozen=True, slots=True)
class Fixed:
    """Every parameter held constant across an experiment.

    ``seed_simulator`` defaults to ``None`` (unseeded) because leaving it unset is a different
    experimental condition from setting it to any particular value. Set it explicitly when the
    varied parameter is not ``seed_simulator``.
    """

    optimization_level: int = 2
    seed_transpiler: int = 7
    shots: int = 1000
    seed_simulator: int | None = None


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    """One experiment definition: what varies, what does not, and over what values."""

    name: str
    varied_parameter: str
    """A key of ``VARIABLE_FIELDS``. The single parameter that changes between runs."""
    varied_values: tuple[int, ...]
    fixed: Fixed = field(default_factory=Fixed)
    backend_name: str = "fake_sherbrooke"
    workload_path: Path | None = None
    """Defaults to ``examples/ghz_star.py``."""
    entrypoint: str = "build"

    def __post_init__(self) -> None:
        if self.varied_parameter not in VARIABLE_FIELDS:
            raise ValueError(
                f"varied_parameter must be one of {sorted(VARIABLE_FIELDS)}, "
                f"got {self.varied_parameter!r}"
            )
        if len(self.varied_values) < 2:
            raise ValueError("an experiment needs at least two values to compare")
        if len(set(self.varied_values)) != len(self.varied_values):
            raise ValueError("varied_values must be distinct")

    def resolved_workload(self) -> Path:
        if self.workload_path is not None:
            return self.workload_path
        return Path(__file__).resolve().parents[2] / "examples" / "ghz_star.py"

    def describe(self) -> dict[str, Any]:
        """The experiment definition, as recorded in ``experiment.json``."""
        return {
            "name": self.name,
            "varied_parameter": self.varied_parameter,
            "varied_parameter_field": VARIABLE_FIELDS[self.varied_parameter],
            "varied_values": list(self.varied_values),
            "fixed": {
                "optimization_level": self.fixed.optimization_level,
                "seed_transpiler": self.fixed.seed_transpiler,
                "shots": self.fixed.shots,
                "seed_simulator": self.fixed.seed_simulator,
                "backend_name": self.backend_name,
                "entrypoint": self.entrypoint,
            },
            "workload_path": str(self.resolved_workload()),
        }

    def configs_for(self, value: int) -> tuple[CompileConfig, ExecutionConfig]:
        """Compile and execution configs for one varied value.

        Only the varied field differs between values; every other field comes from ``fixed``,
        so the recorded definition cannot drift from the runs that were actually made.
        """
        optimization_level = self.fixed.optimization_level
        seed_transpiler = self.fixed.seed_transpiler
        shots = self.fixed.shots
        seed_simulator = self.fixed.seed_simulator
        if self.varied_parameter == "optimization_level":
            optimization_level = value
        elif self.varied_parameter == "seed_transpiler":
            seed_transpiler = value
        elif self.varied_parameter == "shots":
            shots = value
        else:
            seed_simulator = value
        return (
            CompileConfig(optimization_level=optimization_level, seed_transpiler=seed_transpiler),
            ExecutionConfig(shots=shots, seed_simulator=seed_simulator),
        )


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def _cell(value: Any) -> str:
    """Render one CSV cell. ``None`` becomes an empty cell, never ``0`` and never ``None``."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list | tuple):
        return " ".join(str(item) for item in value)
    return str(value)


RUN_COLUMNS = [
    "run_id",
    "varied_value",
    "status",
    "optimization_level",
    "seed_transpiler",
    "shots",
    "seed_simulator",
    "transpiled_depth",
    "transpiled_size",
    "transpiled_two_qubit_gates",
    "layout_initial",
    "layout_final",
    "snapshot_source",
    "backend_name",
]


def _run_row(run: Run, varied_value: int) -> dict[str, Any]:
    """One row of ``runs.csv``. Every value is read off the persisted Run; none is derived."""
    compilation = run.compilation
    layout = compilation.layout if compilation else None
    output = compilation.output if compilation else None
    execution = run.execution
    snapshot = run.backend_snapshot
    return {
        "run_id": run.run_id,
        "varied_value": varied_value,
        "status": run.status.value,
        "optimization_level": compilation.config.optimization_level if compilation else None,
        "seed_transpiler": compilation.config.seed_transpiler if compilation else None,
        "shots": execution.config.shots if execution else None,
        "seed_simulator": execution.config.seed_simulator if execution else None,
        "transpiled_depth": output.depth if output else None,
        "transpiled_size": output.size if output else None,
        "transpiled_two_qubit_gates": output.two_qubit_gate_count if output else None,
        "layout_initial": layout.initial if layout else None,
        "layout_final": layout.final if layout else None,
        "snapshot_source": snapshot.source.value if snapshot else None,
        "backend_name": run.backend.name if run.backend else None,
    }


PAIR_COLUMNS = [
    "baseline_run_id",
    "candidate_run_id",
    "baseline_varied_value",
    "candidate_varied_value",
    "varied_delta",
    "comparison_id",
    "overall_status",
    "distribution_status",
    "distribution_reasons",
    "tvd",
    "tvd_method_version",
    "hellinger_distance",
    "hellinger_method_version",
    "sampling_floor_p_value",
    "sampling_floor_null_p95",
    "sampling_floor_resamples",
    "sampling_floor_seed",
    "sampling_floor_reason",
    "footprint_resources_identical",
    "footprint_baseline_status",
    "footprint_method_version",
    "hardware_relevant_changed",
    "logical_circuit_status",
    "compilation_status",
    "execution_status",
]


def _pair_row(comparison: Comparison) -> dict[str, Any]:
    """One row of ``pairs.csv``. Every value is produced by ``CompareService`` for this pair."""
    distribution = comparison.distribution
    floor = distribution.sampling_floor
    tvd = distribution.tvd
    hellinger = distribution.hellinger_distance
    return {
        "baseline_run_id": comparison.baseline_run_id,
        "candidate_run_id": comparison.candidate_run_id,
        "comparison_id": comparison.comparison_id,
        "overall_status": comparison.status.value,
        "distribution_status": distribution.status.value,
        "distribution_reasons": distribution.reasons,
        "tvd": tvd.value if tvd else None,
        "tvd_method_version": tvd.method_version if tvd else None,
        "hellinger_distance": hellinger.value if hellinger else None,
        "hellinger_method_version": hellinger.method_version if hellinger else None,
        "sampling_floor_p_value": floor.p_value.value if floor else None,
        "sampling_floor_null_p95": floor.null_p95.value if floor else None,
        "sampling_floor_resamples": floor.resamples if floor else None,
        "sampling_floor_seed": floor.seed if floor else None,
        "sampling_floor_reason": distribution.sampling_floor_unavailable_reason,
        "footprint_resources_identical": comparison.footprint.resources_identical,
        "footprint_baseline_status": comparison.baseline_footprint.status.value,
        "footprint_method_version": comparison.baseline_footprint.method_version,
        "hardware_relevant_changed": comparison.hardware.relevant_hardware_changed,
        "logical_circuit_status": comparison.logical_circuit.status.value,
        "compilation_status": comparison.compilation.status.value,
        "execution_status": comparison.execution.status.value,
    }


def create_runs(spec: ExperimentSpec, store_dir: Path) -> dict[int, Run]:
    """Run the workload once per varied value and return the Runs keyed by that value."""
    store_dir.mkdir(parents=True, exist_ok=True)
    repository = SqliteRunRepository(store_dir / "qci.db")
    service = RunService(QiskitIbmAdapter(), repository)
    runs: dict[int, Run] = {}
    try:
        for value in spec.varied_values:
            compile_config, execution_config = spec.configs_for(value)
            run = service.run(
                RunRequest(
                    workload_path=spec.resolved_workload(),
                    backend_name=spec.backend_name,
                    compile_config=compile_config,
                    execution_config=execution_config,
                    entrypoint=spec.entrypoint,
                    tags={"experiment": spec.name, "varied": spec.varied_parameter},
                )
            )
            if run.status is not RunStatus.SUCCEEDED:
                raise RuntimeError(f"run for {spec.varied_parameter}={value} failed: {run.error}")
            runs[value] = run
    finally:
        repository.close()
    return runs


def write_dataset(spec: ExperimentSpec, runs: dict[int, Run], store_dir: Path) -> tuple[Path, int]:
    """Write ``experiment.json``, ``runs.csv`` and ``pairs.csv`` into ``store_dir/spec.name``.

    ``runs.csv`` is written first and holds only stored facts. ``pairs.csv`` then holds only
    facts derived by ``CompareService``, one row per unordered pair of runs. Returns the output
    directory and the pair count.

    The runs were created against ``store_dir/qci.db``, so comparisons must be read from that
    same file rather than from the per-experiment output directory.
    """
    out_dir = store_dir / spec.name
    out_dir.mkdir(parents=True, exist_ok=True)
    values = sorted(runs)
    with (out_dir / "runs.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUN_COLUMNS)
        writer.writeheader()
        for value in values:
            row = _run_row(runs[value], value)
            writer.writerow({column: _cell(row.get(column)) for column in RUN_COLUMNS})

    repository = SqliteRunRepository(store_dir / "qci.db")
    compare_service = CompareService(repository, {PROVIDER_ID: IbmPropertiesCalibrationReader()})
    pair_count = 0
    try:
        rows: list[dict[str, Any]] = []
        for index, baseline_value in enumerate(values):
            for candidate_value in values[index + 1 :]:
                comparison = compare_service.compare(
                    runs[baseline_value].run_id, runs[candidate_value].run_id
                )
                row = _pair_row(comparison)
                row["baseline_varied_value"] = baseline_value
                row["candidate_varied_value"] = candidate_value
                row["varied_delta"] = candidate_value - baseline_value
                rows.append(row)
        with (out_dir / "pairs.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=PAIR_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({column: _cell(row.get(column)) for column in PAIR_COLUMNS})
        pair_count = len(rows)
    finally:
        repository.close()

    definition: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "git_commit": _git_commit(),
        "environment": collect_environment(QiskitIbmAdapter().relevant_packages).model_dump(
            mode="json"
        ),
        "experiment": spec.describe(),
        "run_count": len(runs),
        "pair_count": pair_count,
    }
    (out_dir / "experiment.json").write_text(json.dumps(definition, indent=2) + "\n")
    return out_dir, pair_count


def run_experiment(spec: ExperimentSpec, store_dir: Path, *, reuse: bool = False) -> Path:
    """Create every run for ``spec``, compare all pairs, and write the dataset.

    Returns the output directory. Refuses to overwrite an existing dataset unless ``reuse`` is
    set, so a store is never silently mixed across experiments.
    """
    out_dir = store_dir / spec.name
    if (out_dir / "experiment.json").exists() and not reuse:
        raise FileExistsError(
            f"{out_dir / 'experiment.json'} exists; pass reuse=True to recompute, "
            f"or choose a fresh store directory"
        )
    runs = create_runs(spec, store_dir)
    written, _ = write_dataset(spec, runs, store_dir)
    return written


def load_pairs(out_dir: Path) -> list[dict[str, str]]:
    """Read ``pairs.csv`` back. Values are strings; convert explicitly where a number is meant."""
    with (out_dir / "pairs.csv").open(newline="") as handle:
        return list(csv.DictReader(handle))


def p_values(out_dir: Path) -> list[float]:
    """The computed sampling-floor p-values, in file order. Pairs without a floor are skipped.

    Use :func:`load_pairs` when the count of skipped pairs matters; skipping here is only for
    the common case of counting how many computed floors fall below a threshold.
    """
    values: list[float] = []
    for row in load_pairs(out_dir):
        raw = row.get("sampling_floor_p_value", "")
        if raw:
            values.append(float(raw))
    return values


def summarise(p_values_found: Sequence[float], alpha: float = 0.05) -> dict[str, Any]:
    """Count how many computed p-values fall below ``alpha``.

    This reports a rate; it does not declare that any run is acceptable or unacceptable. The
    threshold is an argument to this function and is never written into the dataset.
    """
    total = len(p_values_found)
    below = sum(1 for value in p_values_found if value < alpha)
    return {
        "alpha": alpha,
        "computed_pairs": total,
        "below_alpha": below,
        "fraction_below_alpha": below / total if total else None,
    }
