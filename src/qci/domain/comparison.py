"""Directional comparison of two immutable runs: baseline -> candidate.

A Comparison answers "what changed between the baseline run and the candidate run?" It never
answers whether the candidate is better or worse, nor why anything changed. Numeric deltas always
mean candidate minus baseline.
"""

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue, NonNegativeInt

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


# --- top level -----------------------------------------------------------------------------


class ComparisonPolicy(DomainModel):
    """Rules the comparison engine applied. Changing any rule must change ``version``."""

    version: Literal["qci.compare.v2"] = "qci.compare.v2"
    distribution_requires_identical_logical_qasm3: bool = True
    distribution_requires_same_provider: bool = True
    distribution_max_classical_registers: int = 1
    dynamic_circuits_supported: bool = False
    distribution_null_resamples: int = Field(default=2000, ge=MIN_DISTRIBUTION_NULL_RESAMPLES)
    """Resamples B used for the TVD sampling floor."""
    hardware_delta_scope: Literal["identical_physical_resources_only"] = (
        "identical_physical_resources_only"
    )


class Comparison(DomainModel):
    schema_version: Literal[1] = 1
    comparison_id: str
    """Deterministic: derived from both run IDs, the engine version and the policy hash."""
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
    limitations: list[str]
