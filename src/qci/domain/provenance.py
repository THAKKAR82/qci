"""Provenance of a run: where the workload came from and what environment ran it."""

from qci.domain.base import DomainModel


class WorkloadSource(DomainModel):
    """The source workload as loaded from disk. Not a canonical workload identity."""

    source_path: str
    source_sha256: str
    entrypoint: str
    name: str


class GitProvenance(DomainModel):
    """Source-control state. Every field is None when unavailable (e.g. not a repo)."""

    commit: str | None = None
    branch: str | None = None
    dirty: bool | None = None
    remote: str | None = None
    """Remote URL with any embedded credentials removed."""


class EnvironmentProvenance(DomainModel):
    """Python runtime and relevant package versions."""

    python_version: str
    python_implementation: str
    platform: str
    packages: dict[str, str | None]
    """Package name -> installed version, or None if not installed."""
    config_hash: str
    """Convenience hash of the fields above. Not an identity."""


class Provenance(DomainModel):
    git: GitProvenance
    environment: EnvironmentProvenance
