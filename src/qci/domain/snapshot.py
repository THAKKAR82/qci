"""Standalone calibration snapshots and their generic measurements (ADR 0005).

A snapshot is not a run. It is calibration a provider published for a backend, captured once
and stored insert-only. ``resource_kind`` and ``resource`` are adapter-defined, opaque strings:
core and storage never parse them (ADR 0006).
"""

from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue, NonNegativeInt

from qci.domain.backend import SnapshotSource
from qci.domain.base import DomainModel
from qci.domain.comparison import (
    ComparisonStatus,
    HardwareComparison,
    PhysicalFootprint,
    ResourceKind,
)
from qci.domain.metric import Metric

SNAPSHOT_SCHEMA_VERSION = 1


class Measurement(DomainModel):
    """One reported (resource, parameter) value, projected from the raw provider payload."""

    resource_kind: str
    """Adapter-defined label, such as ``qubit`` or ``site``. Not the physical ResourceKind."""
    resource: str
    """Adapter-defined identifier. Core never parses it."""
    parameter: str
    value: float | str | None
    """None means the provider reported the parameter but its value is unavailable. Never 0."""
    unit: str | None = None
    measured_at: AwareDatetime | None = None


class CalibrationSnapshot(DomainModel):
    """One distinct calibration content for one backend, first seen at ``captured_at``."""

    schema_version: Literal[1] = 1
    snapshot_id: str
    content_hash: str
    provider: str
    backend_name: str
    backend_version: str | None
    source: SnapshotSource
    captured_at: AwareDatetime
    """When QCI first read this content."""
    calibrated_at: AwareDatetime | None
    """The provider's last update date, in UTC."""
    capture_options: dict[str, JsonValue]
    extraction_method: str
    extraction_method_version: str
    redactions: list[str]
    """JSON paths the redactor replaced. The replaced values are never kept."""
    environment: dict[str, str]
    """Versions of the packages that captured the data. No host, path or account data."""
    provider_raw: dict[str, JsonValue]


class SnapshotCapture(DomainModel):
    """One successful capture command, which returned an existing or a new snapshot."""

    capture_id: str
    snapshot_id: str
    captured_at: AwareDatetime


class SnapshotListItem(DomainModel):
    snapshot_id: str
    provider: str
    backend_name: str
    calibrated_at: AwareDatetime | None
    first_captured_at: AwareDatetime
    last_captured_at: AwareDatetime
    capture_count: NonNegativeInt


class SnapshotFixture(DomainModel):
    """A sanitized snapshot export for offline tests (ADR 0005, section 5)."""

    fixture_format: Literal[1] = 1
    fixture_origin: Literal["live_capture", "synthetic"]
    """``synthetic`` marks data that was not read from live hardware."""
    fixture_note: str | None = None
    snapshot: CalibrationSnapshot
    measurements: list[Measurement]
    captures: list[SnapshotCapture]


# --- snapshot comparison (M1.3c, ADR 0005 section 7) ---------------------------------------


class SnapshotSide(DomainModel):
    """One of the two compared snapshots."""

    snapshot_id: str
    provider: str
    backend_name: str
    content_hash: str
    source: SnapshotSource
    captured_at: AwareDatetime
    calibrated_at: AwareDatetime | None


MeasurementDates = Literal[
    "re_measured_same_value", "not_re_measured", "measurement_date_unavailable"
]


class UnchangedValue(DomainModel):
    """A footprint parameter whose value is the same in both snapshots, with what its
    measurement dates show.

    - ``re_measured_same_value``: the measurement dates differ, so the candidate snapshot holds
      a newer measurement that gave the same value.
    - ``not_re_measured``: the measurement dates are equal, so both snapshots report one
      measurement. It is not evidence that the parameter held constant between the captures.
    - ``measurement_date_unavailable``: a date is missing on at least one side.
    """

    resource_kind: ResourceKind
    operation: str | None
    qubits: tuple[int, ...]
    parameter: str
    value: float | str
    measurement: MeasurementDates
    baseline_measured_at: AwareDatetime | None
    candidate_measured_at: AwareDatetime | None


class ErrorValueAtOne(DomainModel):
    """A listed error-type parameter of a footprint resource whose provider-reported value is
    exactly 1. Stated as the provider gave it; QCI does not interpret it."""

    side: Literal["baseline", "candidate"]
    resource_kind: ResourceKind
    operation: str | None
    qubits: tuple[int, ...]
    parameter: str
    value: float
    measured_at: AwareDatetime | None


SNAPSHOT_COMPARISON_METHOD_VERSION = "qci.compare.snapshot.1"


class SnapshotComparison(DomainModel):
    """Directional comparison of two calibration snapshots of one backend (baseline ->
    candidate), scoped to the physical footprint of one stored run. Never persisted.

    The run only selects which physical resources are read; it is never compared with either
    snapshot. Deltas are candidate minus baseline.
    """

    schema_version: Literal[1] = 1
    snapshot_comparison_id: str
    """Deterministic: derived from both snapshot IDs, the footprint run ID, the mismatch flag
    and ``method_version``."""
    method_version: Literal["qci.compare.snapshot.1"] = "qci.compare.snapshot.1"
    status: ComparisonStatus
    """Equal to ``hardware.status``."""
    baseline: SnapshotSide
    candidate: SnapshotSide
    elapsed_between_captures: Metric
    """Candidate ``captured_at`` minus baseline ``captured_at``, in seconds (calculated)."""
    footprint_run_id: str
    footprint_backend: str | None
    """The footprint run's backend name."""
    allow_footprint_backend_mismatch: bool
    footprint: PhysicalFootprint
    hardware: HardwareComparison
    unchanged_values: list[UnchangedValue] = Field(default_factory=list)
    """Every compared parameter with ``status="unchanged"``, with its measurement dates."""
    error_parameters: list[str]
    """The provider's explicit list of error-type parameter names that were checked."""
    error_values_at_one: list[ErrorValueAtOne] = Field(default_factory=list)
    limitations: list[str]
