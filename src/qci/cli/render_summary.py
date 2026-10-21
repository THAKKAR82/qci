"""Short summaries of the three comparisons, printed by default (ADR 0009, section 6).

``--verbose`` prints the summary, a blank line, then the full text of ``render_compare``,
``render_snapshot_compare`` or ``render_run_snapshot_compare`` unchanged. The summary names
what differs (field names, not values), the key statistics, and the calibration magnitudes of
``qci.compare.summary``. It says "differs" and "delta", and treats no direction of change as
preferable.
"""

from datetime import datetime

from pydantic import BaseModel

from qci.compare.summary import ParameterMagnitude, magnitudes
from qci.domain.comparison import (
    CircuitStructureComparison,
    Comparison,
    ComparisonStatus,
    CounterComparison,
    FootprintComparison,
    HardwareComparison,
    MappingComparison,
    ObservableComparison,
    ParameterComparison,
    SetComparison,
    ValueComparison,
)
from qci.domain.metric import Metric
from qci.domain.snapshot import RunSnapshotComparison, SnapshotComparison

FOOTER = "Full detail: rerun with --verbose. Machine-readable: --json."
DISTRIBUTION_NOTE = (
    "  note: changed means the observed (sampled) distributions differ; it is not a statement "
    "about the underlying probability distribution"
)
HARDWARE_NOTE = (
    "  note: relevant hardware is the calibration of the physical resources the workload used; "
    "it is not a claim that a parameter affects the result"
)
NOT_RE_MEASURED_NOTE = (
    "  note: a value that was not re-measured is one measurement reported twice, not evidence "
    "that the value held constant"
)
_FIELD_TYPES = (ValueComparison, SetComparison, MappingComparison, CounterComparison)


def _number(value: float | int) -> str:
    return f"{value:.3g}"


def _unit(unit: str | None) -> str:
    return f"[{unit}]" if unit else "[no unit]"


def _date(value: datetime | None) -> str:
    return value.isoformat() if value else "unknown"


def _changed_fields(section: BaseModel, prefix: str = "") -> list[str]:
    """Names of the fields whose comparison is ``changed``, never their values."""
    names: list[str] = []
    for name in type(section).model_fields:
        value = getattr(section, name)
        if isinstance(value, _FIELD_TYPES) and value.status == "changed":
            names.append(prefix + name)
        elif isinstance(value, CircuitStructureComparison):
            names += _changed_fields(value, "" if name == "structure" else f"{name}.")
    return names


def _footprint_fields(fp: FootprintComparison) -> list[str]:
    names = _changed_fields(fp)
    if fp.baseline_only_operations or fp.candidate_only_operations:
        names.append("operations")
    if fp.operation_count_changes:
        names.append("operation counts")
    return names


def _changed_parameters(hw: HardwareComparison) -> list[str]:
    seen: dict[str, None] = {}
    for p in hw.shared_resource_parameters:
        if p.status == "changed":
            kind = "qubit" if p.operation is None else p.operation
            seen[f"{kind} {p.parameter}"] = None
    return list(seen)


def _section(title: str, status: ComparisonStatus, what: list[str], why: str | None) -> str:
    line = f"  {title}: {status.value}"
    if status is ComparisonStatus.UNCHANGED:
        return line
    if what:
        line += f" ({', '.join(what)})"
    if why and status is not ComparisonStatus.CHANGED:
        line += f": {why}"
    return line


def _magnitude_line(m: ParameterMagnitude) -> str:
    unit = "units differ" if m.units_differ else _unit(m.unit)
    counts = [f"{m.compared} compared", f"{m.changed} changed"]
    for count, label in (
        (m.unavailable, "unavailable"),
        (m.not_comparable, "not compared (units differ)"),
        (m.not_numeric, "not numeric"),
        (m.baseline_zero, "baseline 0"),
    ):
        if count:
            counts.append(f"{count} {label}")
    line = f"  {m.resource_type} {m.parameter} {unit}: {', '.join(counts)}"
    if m.largest_absolute is not None and m.largest_absolute.metric.value == 0:
        return line + "; every |delta| is 0"
    if m.median_absolute is not None and m.largest_absolute is not None:
        line += (
            f"; |delta| median {_number(m.median_absolute.value)}, largest "
            f"{_number(m.largest_absolute.metric.value)} ({m.largest_absolute.resource})"
        )
    if m.median_relative is not None and m.largest_relative is not None:
        line += (
            f"; relative median {_number(m.median_relative.value)}, largest "
            f"{_number(m.largest_relative.metric.value)} ({m.largest_relative.resource})"
        )
    return line


def _magnitude_lines(params: list[ParameterComparison], direction: str) -> list[str]:
    found = magnitudes(params)
    if not found:
        return []
    return [
        f"Calibration magnitudes of footprint parameters ({direction}; |delta| in the "
        "parameter's unit, relative = |delta| / |baseline|; calculated):",
        *(_magnitude_line(m) for m in found),
    ]


def _status_counts(params: list[ParameterComparison]) -> str:
    count = {
        s: sum(p.status == s for p in params)
        for s in ("changed", "unchanged", "unavailable", "not_comparable")
    }
    return (
        f"  parameters of footprint resources: {len(params)}: {count['changed']} changed, "
        f"{count['unchanged']} unchanged, {count['unavailable']} unavailable, "
        f"{count['not_comparable']} not compared (units differ)"
    )


def _label(m: Metric) -> str:
    return f"[{m.kind.value}]"


# --- qci compare ----------------------------------------------------------------------------


def _observable_line(o: ObservableComparison) -> str:
    head = f"  {o.spec.name} = P({{{', '.join(o.spec.bitstrings)}}}): {o.status.value}"
    if o.baseline is None or o.candidate is None or o.difference is None:
        return head + (f" ({'; '.join(o.reasons)})" if o.reasons else "")
    b, c, d = o.baseline, o.candidate, o.difference
    line = (
        f"{head}; baseline {b.estimate.value:.4f}, candidate {c.estimate.value:.4f}, "
        f"delta {d.delta.value:+.4f}"
    )
    if d.newcombe_lower is not None and d.newcombe_upper is not None:
        line += (
            f", Newcombe 95% [{d.newcombe_lower.value:+.4f}, {d.newcombe_upper.value:+.4f}] "
            f"{_label(d.newcombe_lower)}"
        )
    elif o.difference_unavailable_reason is not None:
        line += f"; Newcombe interval unavailable: {o.difference_unavailable_reason}"
    return line


def _distribution_lines(c: Comparison) -> list[str]:
    d = c.distribution
    lines: list[str] = []
    for metric in (d.tvd, d.hellinger_distance):
        if metric is not None:
            lines.append(f"  {metric.name} = {metric.value:.4g} {_label(metric)}")
    if d.tvd is not None:
        if d.sampling_floor is not None:
            f = d.sampling_floor
            lines.append(
                f"  sampling floor of tvd: p95 {f.null_p95.value:.3g}, Monte Carlo p = "
                f"{f.p_value.value:.3g} {_label(f.p_value)}"
            )
        elif d.sampling_floor_unavailable_reason is not None:
            lines.append(f"  sampling floor unavailable: {d.sampling_floor_unavailable_reason}")
    lines += [f"  note: {r}" for r in d.reasons]
    if d.status is ComparisonStatus.CHANGED:
        lines.append(DISTRIBUTION_NOTE)
    return lines


def render_comparison_summary(c: Comparison) -> str:
    b_backend = c.backend.name.baseline if c.backend.name else None
    k_backend = c.backend.name.candidate if c.backend.name else None
    out = [
        f"Comparison {c.comparison_id}",
        f"  baseline:  {c.baseline_run_id}  {b_backend or '-'}",
        f"  candidate: {c.candidate_run_id}  {k_backend or '-'}",
        f"  status:    {c.status.value}",
        "Sections (deltas are candidate minus baseline):",
        _section("source", c.source.status, _changed_fields(c.source), None),
        _section("environment", c.environment.status, _changed_fields(c.environment), None),
        _section(
            "logical circuit", c.logical_circuit.status, _changed_fields(c.logical_circuit), None
        ),
        _section(
            "compilation",
            c.compilation.status,
            _changed_fields(c.compilation),
            c.compilation.note,
        ),
        _section("execution", c.execution.status, _changed_fields(c.execution), c.execution.note),
        _section("backend", c.backend.status, _changed_fields(c.backend), c.backend.note),
        _section(
            "physical footprint",
            c.footprint.status,
            _footprint_fields(c.footprint),
            c.footprint.reason,
        ),
        _section(
            "hardware (footprint-scoped)",
            c.hardware.status,
            _changed_parameters(c.hardware),
            c.hardware.reason,
        ),
        _section("result distribution", c.distribution.status, [], None),
    ]
    if (
        c.hardware.status is not ComparisonStatus.UNCHANGED
        and c.hardware.shared_resource_parameters
    ):
        out.append(HARDWARE_NOTE)
    distribution = _distribution_lines(c)
    if distribution:
        out += ["Result distribution:", *distribution]
    if c.observables:
        out += ["Observables:", *(_observable_line(o) for o in c.observables)]
    out += _magnitude_lines(c.hardware.shared_resource_parameters, "candidate minus baseline")
    out.append(FOOTER)
    return "\n".join(out)


# --- qci snapshot compare -------------------------------------------------------------------


def render_snapshot_comparison_summary(c: SnapshotComparison) -> str:
    hw = c.hardware
    params = hw.shared_resource_parameters
    fp = c.footprint
    footprint = (
        f"qubits={len(fp.qubits)} operations={len(fp.operations)}"
        if fp.status.value == "available"
        else fp.status.value
    )
    out = [
        f"Snapshot comparison {c.snapshot_comparison_id}",
        f"  baseline:  {c.baseline.snapshot_id}  {c.baseline.provider}/{c.baseline.backend_name}"
        f"  calibrated {_date(c.baseline.calibrated_at)}",
        f"  candidate: {c.candidate.snapshot_id}  {c.candidate.provider}/"
        f"{c.candidate.backend_name}  calibrated {_date(c.candidate.calibrated_at)}",
        f"  footprint run: {c.footprint_run_id} on {c.footprint_backend or 'unknown backend'}"
        f"  {footprint}",
        f"  status:    {c.status.value}",
        _section(
            "Calibration (footprint-scoped)", hw.status, _changed_parameters(hw), hw.reason
        ).lstrip(),
    ]
    if params:
        measured = {
            key: sum(u.measurement == key for u in c.unchanged_values)
            for key in ("re_measured_same_value", "not_re_measured", "measurement_date_unavailable")
        }
        out += [
            _status_counts(params),
            f"  unchanged values: {measured['re_measured_same_value']} re-measured with the same "
            f"value, {measured['not_re_measured']} not re-measured, "
            f"{measured['measurement_date_unavailable']} without a measurement date",
            NOT_RE_MEASURED_NOTE,
        ]
    if c.error_parameters:
        out.append(
            f"  error-type parameters equal to 1 ({', '.join(c.error_parameters)}): "
            f"{len(c.error_values_at_one)}"
        )
    out += _magnitude_lines(params, "candidate minus baseline")
    out.append(FOOTER)
    return "\n".join(out)


# --- qci snapshot compare-run ---------------------------------------------------------------


def _seconds(m: Metric | None) -> str:
    if m is None:
        return "unavailable"
    return f"{m.value:.6g} s ({m.value / 86400:.1f} days)"


def render_run_snapshot_comparison_summary(c: RunSnapshotComparison) -> str:
    b, k, hw = c.baseline, c.candidate, c.hardware
    params = hw.shared_resource_parameters
    mapping = (
        f"{c.device_mapping.fake} -> {c.device_mapping.device}" if c.device_mapping else "none"
    )
    out = [
        f"Run-to-snapshot calibration comparison {c.run_snapshot_comparison_id}",
        f"  baseline:  run {b.run_id}  {b.provider or '-'}/{b.backend_name or '-'}  "
        f"calibrated {_date(b.calibrated_at)}",
        f"  candidate: snapshot {k.snapshot_id}  {k.provider}/{k.backend_name}  "
        f"calibrated {_date(k.calibrated_at)}",
        f"  device mapping: {mapping}",
        f"  status:    {c.status.value}",
        _section(
            "Calibration (footprint-scoped)", hw.status, _changed_parameters(hw), hw.reason
        ).lstrip(),
    ]
    if params:
        out.append(_status_counts(params))
    out.append(
        f"  parameters reported by one side only: {len(c.parameters_on_one_side)}; unit "
        f"differences: {len(c.unit_differences)}; error-type parameters equal to 1: "
        f"{len(c.error_values_at_one)}"
    )
    if c.measurement_dates:
        out.append(
            f"  measurement dates, live minus fake, over {len(c.measurement_dates)} parameters: "
            f"min {_seconds(c.live_minus_fake_min)}, max "
            f"{_seconds(c.live_minus_fake_max)} [calculated]"
        )
    out += _magnitude_lines(params, "live minus fake")
    out.append(FOOTER)
    return "\n".join(out)
