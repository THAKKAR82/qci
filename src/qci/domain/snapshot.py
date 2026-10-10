"""Standalone calibration snapshots and their generic measurements (ADR 0005).

A snapshot is not a run. It is calibration a provider published for a backend, captured once
and stored insert-only. ``resource_kind`` and ``resource`` are adapter-defined, opaque strings:
core and storage never parse them (ADR 0006).
"""

from typing import Literal

from pydantic import AwareDatetime, JsonValue, NonNegativeInt

from qci.domain.backend import SnapshotSource
from qci.domain.base import DomainModel

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
