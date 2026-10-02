"""Metrics and their epistemic labels."""

from enum import StrEnum

from qci.domain.base import DomainModel


class EvidenceKind(StrEnum):
    """How a value was obtained. Never present one kind as another."""

    MEASURED = "measured"
    """Directly observed, e.g. counts, shots, timings."""
    CALCULATED = "calculated"
    """Deterministically derived from measured or recorded data."""
    HEURISTIC = "heuristic"
    """Rule of thumb without statistical guarantees."""
    STATISTICAL = "statistical"
    """Estimate with stated uncertainty from a named test or estimator."""
    MODEL_PREDICTION = "model_prediction"
    """Output of a learned or analytical predictive model."""
    CAUSAL_CLAIM = "causal_claim"
    """Claim that X caused Y; requires explicit evidence and method."""


class Metric(DomainModel):
    """A single labeled value."""

    name: str
    value: float | int
    unit: str | None = None
    kind: EvidenceKind
    method: str
    method_version: str
    uncertainty: float | None = None
