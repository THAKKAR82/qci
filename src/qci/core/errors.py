"""Errors shared across QCI layers."""


class QCIError(Exception):
    """Base class for QCI errors."""


class WorkloadLoadError(QCIError):
    """The workload could not be loaded into a circuit."""


class UnknownBackendError(QCIError):
    """The requested backend is not available from the provider adapter."""


class RunNotFoundError(QCIError):
    """No run with the given ID exists."""


class DuplicateRunError(QCIError):
    """A run with the given ID already exists. Runs are immutable."""


class SchemaVersionError(QCIError):
    """The store or record uses a schema version this QCI cannot read."""
