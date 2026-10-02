"""Backends and point-in-time backend snapshots."""

from enum import StrEnum

from pydantic import AwareDatetime, JsonValue, NonNegativeInt

from qci.domain.base import DomainModel


class SnapshotSource(StrEnum):
    LIVE_CALIBRATION = "live_calibration"
    """Calibration data read from real hardware at capture time."""
    STATIC_FAKE = "static_fake"
    """Frozen calibration data shipped with a fake backend. Not live hardware state."""
    SIMULATOR_IDEAL = "simulator_ideal"
    """Noiseless simulator with no calibration data."""


class Backend(DomainModel):
    """Backend identity and basic capabilities."""

    provider: str
    name: str
    version: str | None = None
    num_qubits: NonNegativeInt
    is_simulator: bool


class BackendSnapshot(DomainModel):
    """What QCI knew about the backend when the run happened."""

    source: SnapshotSource
    captured_at: AwareDatetime
    """When QCI read this data."""
    calibrated_at: AwareDatetime | None = None
    """When the provider says the calibration was taken."""
    basis_gates: list[str]
    coupling_edges: list[tuple[int, int]]
    """Directed edges as reported by the provider."""
    provider_raw: dict[str, JsonValue]
    """Raw provider payloads, kept verbatim (JSON-converted losslessly)."""
