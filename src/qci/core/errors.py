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


class InvalidObservableError(QCIError):
    """A requested observable does not fit the runs being compared."""


class SnapshotNotFoundError(QCIError):
    """No calibration snapshot with the given ID exists."""


class CaptureRejectedError(QCIError):
    """The backend cannot be captured as live calibration, e.g. a fake or a simulator."""


class FixtureExportError(QCIError):
    """A fixture could not be exported safely. Nothing was written."""
