"""Directional comparison of two immutable runs: baseline -> candidate.

A Comparison answers "what changed between the baseline run and the candidate run?" It never
answers whether the candidate is better or worse, nor why anything changed. Numeric deltas always
mean candidate minus baseline.
"""

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue, NonNegativeInt, field_validator

from qci.domain.backend import SnapshotSource
from qci.domain.base import DomainModel
from qci.domain.metric import Metric


class ComparisonStatus(StrEnum):
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    PARTIALLY_COMPARABLE = "partially_comparable"
    """Some evidence could be compared, but not all of it (e.g. footprints differ)."""
    NOT_COMPARABLE = "not_comparable"
    """Both sides exist but comparing them would be scientifically invalid."""
    UNAVAILABLE = "unavailable"
    """The evidence needed for this comparison is missing on at least one side."""


FieldStatus = Literal["unchanged", "changed"]


# --- typed comparison helpers --------------------------------------------------------------


class ValueComparison(DomainModel):
    """Exact comparison of one normalized value. ``delta`` = candidate - baseline when numeric."""

    status: FieldStatus
    baseline: JsonValue
    candidate: JsonValue
    delta: float | int | None = None


class SetComparison(DomainModel):
    status: FieldStatus
    common: list[JsonValue]
    baseline_only: list[JsonValue]
    candidate_only: list[JsonValue]


class KeyChange(DomainModel):
    key: str
    baseline: JsonValue
    candidate: JsonValue


class MappingComparison(DomainModel):
    """Keyed values (e.g. package -> version). Only differing keys are listed."""

    status: FieldStatus
    baseline_only: list[str]
    candidate_only: list[str]
    changed: list[KeyChange]


class CounterDelta(DomainModel):
    key: str
    baseline: int
    candidate: int
    delta: int


class CounterComparison(DomainModel):
    """Keyed counts (e.g. op name -> count). Only differing keys are listed (0 = absent)."""

    status: FieldStatus
    changed: list[CounterDelta]


# --- semantic sections -------------------------------------------------------------------


class SourceComparison(DomainModel):
    status: ComparisonStatus
    source_sha256: ValueComparison
    source_path: ValueComparison
    entrypoint: ValueComparison
    workload_name: ValueComparison
    git_commit: ValueComparison
    git_branch: ValueComparison
    git_dirty: ValueComparison
    git_remote: ValueComparison


class EnvironmentComparison(DomainModel):
    status: ComparisonStatus
    python_version: ValueComparison
    python_implementation: ValueComparison
    platform: ValueComparison
    packages: MappingComparison
    environment_hash: ValueComparison


class CircuitStructureComparison(DomainModel):
    """Structural fields shared by logical and transpiled circuit summaries."""

    num_qubits: ValueComparison
    num_clbits: ValueComparison
    depth: ValueComparison
    size: ValueComparison
    two_qubit_gate_count: ValueComparison
    op_counts: CounterComparison
    qasm3_sha256: ValueComparison
    """SHA-256 of the exported OpenQASM 3 text (null if export failed). Not an identity."""
    qasm3_exporter: ValueComparison


class LogicalCircuitComparison(DomainModel):
    status: ComparisonStatus
    structure: CircuitStructureComparison
    two_qubit_edges: SetComparison
    """Undirected logical interaction edges (virtual qubit indices)."""


class CompilationComparison(DomainModel):
    status: ComparisonStatus
    note: str | None = None
    compiler: ValueComparison | None = None
    optimization_level: ValueComparison | None = None
    seed_transpiler: ValueComparison | None = None
    initial_layout: ValueComparison | None = None
    final_layout: ValueComparison | None = None
    transpiled: CircuitStructureComparison | None = None


class ExecutionComparison(DomainModel):
    status: ComparisonStatus
    note: str | None = None
    shots: ValueComparison | None = None
    seed_simulator: ValueComparison | None = None
    primitive: ValueComparison | None = None


class BackendComparison(DomainModel):
    status: ComparisonStatus
    note: str | None = None
    provider: ValueComparison | None = None
    name: ValueComparison | None = None
    version: ValueComparison | None = None
    num_qubits: ValueComparison | None = None
    is_simulator: ValueComparison | None = None
    snapshot_source: ValueComparison | None = None
    calibrated_at: ValueComparison | None = None
    basis_gates: SetComparison | None = None
    coupling_edges: SetComparison | None = None


# --- physical footprint --------------------------------------------------------------------


class FootprintStatus(StrEnum):
    AVAILABLE = "available"
    UNSUPPORTED_DYNAMIC = "unsupported_dynamic"
    UNAVAILABLE = "unavailable"


class PhysicalOperation(DomainModel):
    """One native operation on ordered physical qubits, with its multiplicity."""

    name: str
    qubits: tuple[int, ...]
    count: NonNegativeInt


class PhysicalFootprint(DomainModel):
    """Physical resources referenced by the final transpiled circuit."""

    status: FootprintStatus
    reason: str | None = None
    qubits: list[int] = Field(default_factory=list)
    """Every physical qubit referenced by a non-barrier instruction."""
    measured_qubits: list[int] = Field(default_factory=list)
    operations: list[PhysicalOperation] = Field(default_factory=list)
    """Sorted by (name, qubits). Barriers are excluded."""
    initial_layout: list[int] | None = None
    """Logical qubit index -> physical qubit before routing."""
    final_layout: list[int] | None = None
    """Logical qubit index -> physical qubit holding its state at the end."""
    method: str
    method_version: str


class OperationRef(DomainModel):
    name: str
    qubits: tuple[int, ...]


class OperationCountChange(DomainModel):
    name: str
    qubits: tuple[int, ...]
    baseline: int
    candidate: int
    delta: int


class FootprintComparison(DomainModel):
    status: ComparisonStatus
    reason: str | None = None
    resources_identical: bool | None = None
    """Same physical qubits and same (name, ordered qubits) operations on both sides."""
    qubits: SetComparison | None = None
    measured_qubits: SetComparison | None = None
    common_operations: list[OperationRef] = Field(default_factory=list)
    baseline_only_operations: list[OperationRef] = Field(default_factory=list)
    candidate_only_operations: list[OperationRef] = Field(default_factory=list)
    operation_count_changes: list[OperationCountChange] = Field(default_factory=list)
    initial_layout: ValueComparison | None = None
    final_layout: ValueComparison | None = None


# --- calibration and hardware --------------------------------------------------------------


class CalibrationValue(DomainModel):
    """A provider-reported parameter. ``value`` None means unavailable, never zero."""

    name: str
    value: float | str | None
    unit: str | None = None
    calibrated_at: AwareDatetime | None = None


class QubitCalibration(DomainModel):
    qubit: int
    available: bool
    parameters: list[CalibrationValue] = Field(default_factory=list)


class OperationCalibration(DomainModel):
    name: str
    qubits: tuple[int, ...]
    available: bool
    parameters: list[CalibrationValue] = Field(default_factory=list)
    note: str | None = None


class FootprintCalibration(DomainModel):
    """Provider calibration selected for specific physical resources only."""

    qubits: list[QubitCalibration] = Field(default_factory=list)
    operations: list[OperationCalibration] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    """Provider data deliberately not scoped to resources, with the reason."""


class ResourceKind(StrEnum):
    QUBIT = "qubit"
    OPERATION = "operation"


class ParameterComparison(DomainModel):
    """One parameter of one physical resource that is identical on both sides."""

    resource_kind: ResourceKind
    operation: str | None
    qubits: tuple[int, ...]
    parameter: str
    unit: str | None
    status: Literal["unchanged", "changed", "unavailable"]
    baseline: float | str | None
    candidate: float | str | None
    delta: float | None = None
    baseline_calibrated_at: AwareDatetime | None = None
    candidate_calibrated_at: AwareDatetime | None = None


class HardwareComparison(DomainModel):
    status: ComparisonStatus
    reason: str | None = None
    global_snapshot_changed: bool | None = None
    """Whether the raw provider snapshot differs anywhere, including unused hardware."""
    baseline_snapshot_source: SnapshotSource | None = None
    candidate_snapshot_source: SnapshotSource | None = None
    relevant_hardware_changed: bool | None = None
    """Whether calibration data changed for physical resources the workload actually used.
    "Relevant" means used by the workload, not known to affect workload performance, and a
    change here is not a claim that it caused any result change. Null when the footprints
    differ or relevant data is unavailable."""
    shared_resource_parameters: list[ParameterComparison] = Field(default_factory=list)
    """Only resources physically identical on both sides; never across different resources."""
    calibration_date_changes: list[str] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)


# --- results -------------------------------------------------------------------------------


MIN_DISTRIBUTION_NULL_RESAMPLES = 100
SEED_UPPER_BOUND = 2**53
"""Seeds are below 2**53, so they are exact JSON integers even for float64 readers."""


class SamplingFloor(DomainModel):
    """How large TVD is expected to be from multinomial sampling alone, at the observed shots.

    H0: both runs sampled one shared distribution, estimated by the pooled plug-in estimate.
    This is evidence about the observed samples. It is not a verdict and makes no causal claim.
    """

    method: str
    method_version: str
    rng: str
    """Generator, bit generator and the installed numpy version that produced the resamples."""
    seed: int = Field(ge=0, lt=SEED_UPPER_BOUND)
    """Derived from ``comparison_id`` by ``qci.compare.sampling.seed_from_comparison_id``."""
    resamples: int = Field(ge=MIN_DISTRIBUTION_NULL_RESAMPLES)
    null_p50: Metric
    null_p95: Metric
    null_p99: Metric
    p_value: Metric
    """Monte Carlo p-value: (1 + #{null_tvd >= observed_tvd - 1e-12}) / (resamples + 1)."""
    caveats: list[str]


class DistributionComparison(DomainModel):
    """Comparison of observed (sampled) result distributions.

    ``changed`` means the empirical distributions differ (nonzero TVD/Hellinger distance). It
    does not establish that the underlying probability distribution changed, nor that the
    difference is statistically significant.
    """

    status: ComparisonStatus
    reasons: list[str] = Field(default_factory=list)
    classical_register: str | None = None
    baseline_shots: int | None = None
    candidate_shots: int | None = None
    tvd: Metric | None = None
    hellinger_distance: Metric | None = None
    sampling_floor: SamplingFloor | None = None
    """TVD sampling floor. Null unless the comparability gate passed."""
    sampling_floor_unavailable_reason: str | None = None
    """Why the floor was not computed although the gate passed. Null whenever the floor is
    computed, and when the gate failed (those reasons are in ``reasons``)."""


# --- observables ---------------------------------------------------------------------------


class ObservableSpec(DomainModel):
    """A workload-specific figure of merit requested at compare time.

    ``bitstring_set_probability`` is the fraction of shots whose outcome is in ``bitstrings``.
    Bitstrings must match provider counts keys verbatim (``bit_order="provider_counts_key"``).
    For Qiskit, classical bit 0 is the rightmost character.
    """

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    kind: Literal["bitstring_set_probability"] = "bitstring_set_probability"
    bitstrings: list[str] = Field(min_length=1)
    """Unique and sorted; only the characters 0 and 1."""
    classical_register: str | None = None
    """Classical register; null means the single register of the runs."""
    bit_order: Literal["provider_counts_key"] = "provider_counts_key"

    @field_validator("bitstrings")
    @classmethod
    def _sorted_unique_binary(cls, value: list[str]) -> list[str]:
        for bits in value:
            if not bits or set(bits) - {"0", "1"}:
                raise ValueError(f"bitstring {bits!r} must be non-empty and contain only 0 and 1")
        if len(set(value)) != len(value):
            raise ValueError(f"bitstrings must be unique, got {value}")
        if len({len(b) for b in value}) > 1:
            raise ValueError(f"bitstrings must all have the same width, got {value}")
        return sorted(value)


class ObservableSide(DomainModel):
    """One run's estimate: k of n shots fell in the bitstring set."""

    k: NonNegativeInt
    n: NonNegativeInt
    estimate: Metric
    """k / n (calculated)."""
    wilson_lower: Metric
    wilson_upper: Metric
    """Wilson 95% score interval bounds (statistical)."""


class ObservableDifference(DomainModel):
    """Candidate minus baseline estimate, with a Newcombe hybrid score interval."""

    delta: Metric
    """p_candidate - p_baseline (calculated). Reported even when the interval is withheld."""
    newcombe_lower: Metric | None = None
    newcombe_upper: Metric | None = None
    """Newcombe 95% hybrid score interval bounds (statistical). Null when withheld; the reason
    is ``ObservableComparison.difference_unavailable_reason``."""


class ObservableComparison(DomainModel):
    """``changed`` means the observed estimates differ, never that the difference is
    significant or that the underlying probability changed."""

    spec: ObservableSpec
    status: ComparisonStatus
    reasons: list[str] = Field(default_factory=list)
    classical_register: str | None = None
    baseline: ObservableSide | None = None
    candidate: ObservableSide | None = None
    difference: ObservableDifference | None = None
    difference_unavailable_reason: str | None = None
    """Why the Newcombe interval was not computed, for example a shared simulator seed. Null
    when the interval is computed, and when the gate failed (those reasons are in
    ``reasons``)."""


# --- top level -----------------------------------------------------------------------------


class ComparisonPolicy(DomainModel):
    """Rules the comparison engine applied. Changing any rule must change ``version``."""

    version: Literal["qci.compare.v3"] = "qci.compare.v3"
    distribution_requires_identical_logical_qasm3: bool = True
    distribution_requires_same_provider: bool = True
    distribution_max_classical_registers: int = 1
    dynamic_circuits_supported: bool = False
    distribution_null_resamples: int = Field(default=2000, ge=MIN_DISTRIBUTION_NULL_RESAMPLES)
    """Resamples B used for the TVD sampling floor."""
    sampling_floor_requires_distinct_simulator_seeds: bool = True
    """When both runs used simulators with the same non-null simulator seed, skip the TVD
    sampling floor and withhold every observable's Newcombe difference interval. Both assume
    independent samples. The name predates observables (rename at the next policy bump)."""
    hardware_delta_scope: Literal["identical_physical_resources_only"] = (
        "identical_physical_resources_only"
    )


class Comparison(DomainModel):
    schema_version: Literal[1] = 1
    comparison_id: str
    """Deterministic: derived from both run IDs, the engine version, the policy hash and the
    canonical hash of the requested observables."""
    engine_version: str
    policy: ComparisonPolicy
    policy_hash: str
    baseline_run_id: str
    candidate_run_id: str
    status: ComparisonStatus
    source: SourceComparison
    environment: EnvironmentComparison
    logical_circuit: LogicalCircuitComparison
    compilation: CompilationComparison
    execution: ExecutionComparison
    backend: BackendComparison
    baseline_footprint: PhysicalFootprint
    candidate_footprint: PhysicalFootprint
    footprint: FootprintComparison
    hardware: HardwareComparison
    baseline_counts: dict[str, dict[str, int]] | None
    candidate_counts: dict[str, dict[str, int]] | None
    distribution: DistributionComparison
    observables: list[ObservableComparison] = Field(default_factory=list)
    """One entry per requested observable, sorted by name. The request is part of
    ``comparison_id``."""
    limitations: list[str]
