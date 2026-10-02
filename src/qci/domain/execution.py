"""Execution configuration, record and result."""

from pydantic import AwareDatetime, JsonValue, NonNegativeInt, PositiveInt

from qci.domain.base import DomainModel


class ExecutionConfig(DomainModel):
    """Requested execution settings."""

    shots: PositiveInt
    seed_simulator: int | None = None


class ExecutionRecord(DomainModel):
    """What was actually executed, and when."""

    config: ExecutionConfig
    config_hash: str
    primitive: str
    """Fully qualified name of the primitive/API that executed the circuit."""
    started_at: AwareDatetime
    finished_at: AwareDatetime
    provider_job_id: str | None = None


class ExecutionResult(DomainModel):
    """Raw measured outcome."""

    counts: dict[str, dict[str, NonNegativeInt]]
    """Classical register name -> bitstring -> count."""
    total_shots: NonNegativeInt
    provider_metadata: dict[str, JsonValue]
