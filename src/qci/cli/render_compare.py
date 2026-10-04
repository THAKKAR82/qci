"""Human-readable rendering of a Comparison (baseline -> candidate)."""

import math

from qci.domain.comparison import (
    CircuitStructureComparison,
    Comparison,
    CounterComparison,
    MappingComparison,
    ObservableComparison,
    PhysicalFootprint,
    SamplingFloor,
    SetComparison,
    ValueComparison,
)

RELEVANT_HARDWARE_NOTE = (
    "  note: relevant hardware = calibration data for the physical resources this workload "
    "actually used; it does not mean a parameter is known to affect workload performance, nor "
    "that a calibration change caused any result change"
)
EMPIRICAL_DISTRIBUTION_NOTE = (
    "  note: the observed empirical (sampled) result distributions differ; this does not "
    "establish that the underlying probability distribution changed, nor that the difference "
    "is statistically significant"
)


def _value_line(name: str, v: ValueComparison | None) -> list[str]:
    if v is None or v.status == "unchanged":
        return []
    delta = f"  (delta {v.delta:+g})" if isinstance(v.delta, int | float) else ""
    return [f"    {name}: {v.baseline!r} -> {v.candidate!r}{delta}"]


def _set_line(name: str, s: SetComparison | None) -> list[str]:
    if s is None or s.status == "unchanged":
        return []
    return [f"    {name}: baseline-only={s.baseline_only} candidate-only={s.candidate_only}"]


def _mapping_lines(name: str, m: MappingComparison) -> list[str]:
    if m.status == "unchanged":
        return []
    lines = [f"    {name}:"]
    lines += [f"      {c.key}: {c.baseline!r} -> {c.candidate!r}" for c in m.changed]
    lines += [f"      {k}: baseline only" for k in m.baseline_only]
    lines += [f"      {k}: candidate only" for k in m.candidate_only]
    return lines


def _counter_lines(name: str, c: CounterComparison) -> list[str]:
    if c.status == "unchanged":
        return []
    items = ", ".join(f"{d.key} {d.baseline}->{d.candidate} ({d.delta:+d})" for d in c.changed)
    return [f"    {name}: {items}"]


def _structure_lines(s: CircuitStructureComparison) -> list[str]:
    lines: list[str] = []
    for name in ("num_qubits", "num_clbits", "depth", "size", "two_qubit_gate_count"):
        lines += _value_line(name, getattr(s, name))
    lines += _counter_lines("op_counts", s.op_counts)
    if s.qasm3_sha256.status == "changed":
        lines.append("    OpenQASM 3 text differs")
    lines += _value_line("qasm3_exporter", s.qasm3_exporter)
    return lines


def _estimate_text(value: float, error: float | None) -> str:
    """``value ± error``: the error rounded to its leading digit, the value to the same place."""
    if not error:
        return f"{value:.3g}" if error is None else f"{value:.3g} ± 0"
    decimals = max(0, -math.floor(math.log10(error)))
    return f"{value:.{decimals}f} ± {error:.{decimals}f}"


def _sampling_floor_text(f: SamplingFloor) -> str:
    p = f.p_value
    label = f"{p.kind.value}; v{p.method_version}"
    return (
        f" | sampling floor under H0 (B={f.resamples}): p50 {f.null_p50.value:.3g}, "
        f"p95 {f.null_p95.value:.3g}, p99 {f.null_p99.value:.3g} "
        f"| Monte Carlo p = {_estimate_text(p.value, p.uncertainty)}  [{label}]"
    )


OBSERVABLE_NOTE = (
    "  note: changed means only that the observed estimates differ; intervals are 95% (Wilson "
    "per run, Newcombe for candidate minus baseline) and describe sampling uncertainty at the "
    "observed shots; they are not verdicts"
)


def _observable_lines(o: ObservableComparison) -> list[str]:
    head = f"  {o.spec.name} = P({{{', '.join(o.spec.bitstrings)}}}): {o.status.value}"
    lines = [head] + [f"    reason: {r}" for r in o.reasons]
    if o.baseline is None or o.candidate is None or o.difference is None:
        return lines
    for label, side in (("baseline ", o.baseline), ("candidate", o.candidate)):
        e = side.estimate
        lines.append(
            f"    {label}: {side.k}/{side.n} = {e.value:.4f}  [{e.kind.value}; "
            f"v{e.method_version}]  Wilson [{side.wilson_lower.value:.4f}, "
            f"{side.wilson_upper.value:.4f}]  [{side.wilson_lower.kind.value}]"
        )
    d = o.difference
    line = f"    delta: {d.delta.value:+.4f}  [{d.delta.kind.value}; v{d.delta.method_version}]"
    if d.newcombe_lower is not None and d.newcombe_upper is not None:
        line += (
            f"  Newcombe [{d.newcombe_lower.value:+.4f}, {d.newcombe_upper.value:+.4f}]  "
            f"[{d.newcombe_lower.kind.value}]"
        )
    elif o.difference_unavailable_reason is not None:
        line += f" | Newcombe interval unavailable: {o.difference_unavailable_reason}"
    lines.append(line)
    return lines


def _footprint_line(label: str, fp: PhysicalFootprint) -> str:
    if fp.status.value != "available":
        return f"  {label}: {fp.status.value} ({fp.reason})"
    return (
        f"  {label}: qubits={fp.qubits} measured={fp.measured_qubits} "
        f"operations={len(fp.operations)} initial_layout={fp.initial_layout} "
        f"final_layout={fp.final_layout}"
    )


def render_comparison(c: Comparison) -> str:
    out = [
        f"Comparison {c.comparison_id}",
        f"  baseline:  {c.baseline_run_id}",
        f"  candidate: {c.candidate_run_id}",
        f"  status:    {c.status.value}",
        f"  policy:    {c.policy.version}  engine: {c.engine_version}",
        "  (deltas are candidate minus baseline)",
    ]

    def section(title: str, status: str, lines: list[str], note: str | None = None) -> None:
        out.append(f"{title}: {status}" + (f"  ({note})" if note else ""))
        out.extend(lines)

    s = c.source
    section(
        "Source",
        s.status.value,
        [
            line
            for name in (
                "source_sha256",
                "source_path",
                "entrypoint",
                "workload_name",
                "git_commit",
                "git_branch",
                "git_dirty",
                "git_remote",
            )
            for line in _value_line(name, getattr(s, name))
        ],
    )
    e = c.environment
    section(
        "Environment",
        e.status.value,
        _value_line("python_version", e.python_version)
        + _value_line("python_implementation", e.python_implementation)
        + _value_line("platform", e.platform)
        + _mapping_lines("packages", e.packages),
    )
    lc = c.logical_circuit
    section(
        "Logical circuit",
        lc.status.value,
        _structure_lines(lc.structure) + _set_line("two_qubit_edges", lc.two_qubit_edges),
    )
    cp = c.compilation
    cp_lines: list[str] = []
    for name in (
        "compiler",
        "optimization_level",
        "seed_transpiler",
        "initial_layout",
        "final_layout",
    ):
        cp_lines += _value_line(name, getattr(cp, name))
    if cp.transpiled is not None:
        cp_lines += [f"  transpiled:{line[3:]}" for line in _structure_lines(cp.transpiled)]
    section("Compilation", cp.status.value, cp_lines, cp.note)
    ex = c.execution
    section(
        "Execution",
        ex.status.value,
        _value_line("shots", ex.shots)
        + _value_line("seed_simulator", ex.seed_simulator)
        + _value_line("primitive", ex.primitive),
        ex.note,
    )
    b = c.backend
    b_lines: list[str] = []
    for name in (
        "provider",
        "name",
        "version",
        "num_qubits",
        "is_simulator",
        "snapshot_source",
        "calibrated_at",
    ):
        b_lines += _value_line(name, getattr(b, name))
    b_lines += _set_line("basis_gates", b.basis_gates) + _set_line(
        "coupling_edges", b.coupling_edges
    )
    section("Backend", b.status.value, b_lines, b.note)

    fp = c.footprint
    fp_lines = [
        _footprint_line("baseline ", c.baseline_footprint),
        _footprint_line("candidate", c.candidate_footprint),
    ]
    if fp.qubits is not None:
        fp_lines.append(
            f"  qubits: common={fp.qubits.common} baseline-only={fp.qubits.baseline_only} "
            f"candidate-only={fp.qubits.candidate_only}"
        )
        fp_lines.append(
            f"  operations: common={len(fp.common_operations)} "
            f"baseline-only={len(fp.baseline_only_operations)} "
            f"candidate-only={len(fp.candidate_only_operations)}"
        )
        for op in fp.baseline_only_operations:
            fp_lines.append(f"    baseline only: {op.name}{list(op.qubits)}")
        for op in fp.candidate_only_operations:
            fp_lines.append(f"    candidate only: {op.name}{list(op.qubits)}")
        for ch in fp.operation_count_changes:
            fp_lines.append(
                f"    count {ch.name}{list(ch.qubits)}: {ch.baseline} -> {ch.candidate}"
            )
        fp_lines += _value_line("initial_layout", fp.initial_layout)
        fp_lines += _value_line("final_layout", fp.final_layout)
    section("Physical footprint", fp.status.value, fp_lines, fp.reason)

    hw = c.hardware
    hw_lines = [
        RELEVANT_HARDWARE_NOTE,
        f"  global_snapshot_changed:   {hw.global_snapshot_changed}",
        f"  relevant_hardware_changed: {hw.relevant_hardware_changed}",
    ]
    shared = hw.shared_resource_parameters
    changed = [p for p in shared if p.status == "changed"]
    if shared:
        hw_lines.append(
            f"  shared-resource parameters: {len(shared)} compared, {len(changed)} changed, "
            f"{sum(p.status == 'unavailable' for p in shared)} unavailable"
        )
    for p in changed:
        resource = (
            f"qubit {p.qubits[0]}"
            if p.resource_kind.value == "qubit"
            else (f"{p.operation}{list(p.qubits)}")
        )
        delta = f" (delta {p.delta:+g})" if p.delta is not None else ""
        unit = f" {p.unit}" if p.unit else ""
        hw_lines.append(f"    {resource} {p.parameter}: {p.baseline} -> {p.candidate}{unit}{delta}")
    hw_lines += [f"  unavailable: {u}" for u in hw.unavailable]
    hw_lines += [f"  excluded: {x}" for x in hw.excluded]
    section("Hardware (footprint-scoped)", hw.status.value, hw_lines, hw.reason)

    d = c.distribution
    d_lines = [
        f"  baseline counts:  {c.baseline_counts}",
        f"  candidate counts: {c.candidate_counts}",
    ]
    for metric in (d.tvd, d.hellinger_distance):
        if metric is not None:
            label = f"{metric.kind.value}; v{metric.method_version}"
            line = f"  {metric.name} = {metric.value:.6g}  [{label}]"
            if metric is d.tvd and d.sampling_floor is not None:
                line += _sampling_floor_text(d.sampling_floor)
            elif metric is d.tvd and d.sampling_floor_unavailable_reason is not None:
                line += f" | sampling floor unavailable: {d.sampling_floor_unavailable_reason}"
            d_lines.append(line)
    d_lines += [f"  note: {r}" for r in d.reasons]
    if d.status.value == "changed":
        d_lines.append(EMPIRICAL_DISTRIBUTION_NOTE)
    section("Result distribution", d.status.value, d_lines)

    if c.observables:
        o_lines = [line for o in c.observables for line in _observable_lines(o)]
        o_lines.append(OBSERVABLE_NOTE)
        section("Observables", f"{len(c.observables)} requested", o_lines)

    out.append("Limitations:")
    out += [f"  - {line}" for line in c.limitations]
    return "\n".join(out)
