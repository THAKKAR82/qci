"""Read-only capture of published IBM calibration (ADR 0005). Executes nothing.

The client is built only as ``QiskitRuntimeService(name=ACCOUNT)``, so a saved account is used
and environment variables never are. QCI passes no token, URL, instance or filename, and never
reads the account file itself, except through the client's ``AccountManager`` for the fixture
export scan (``load_account_secrets``). ``qiskit_ibm_runtime`` is imported lazily, so tests can
inject a stub ``service_factory`` and never construct the real client.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import metadata
from typing import Any, Protocol

from pydantic import JsonValue

from qci.adapters.qiskit_ibm.adapter_ids import PROVIDER_ID
from qci.adapters.qiskit_ibm.calibration import (
    EXTRACTION_METHOD,
    EXTRACTION_METHOD_VERSION,
    _date,
    extract_measurements,
)
from qci.adapters.qiskit_ibm.jsonable import to_jsonable
from qci.adapters.qiskit_ibm.redact import redact_payload
from qci.core.errors import CaptureRejectedError
from qci.core.ports import CapturedCalibration
from qci.domain.backend import SnapshotSource

DEFAULT_ACCOUNT = "default-ibm-quantum-platform"
ENVIRONMENT_PACKAGES = ("qci", "qiskit", "qiskit-ibm-runtime")


class ServiceFactory(Protocol):
    def __call__(self, *, name: str) -> Any: ...


def create_service(*, name: str) -> Any:
    """The only place QCI constructs ``QiskitRuntimeService``."""
    from qiskit_ibm_runtime import QiskitRuntimeService

    return QiskitRuntimeService(name=name)


@contextmanager
def quiet_client_logs() -> Iterator[None]:
    """Drop every log record while the client runs, then restore the previous setting.

    Some client log messages interpolate instance names and CRNs (for example
    ``Invalid instance %s`` and ``Using instance: %s``). The client attaches its own stderr
    handler to the ``qiskit_ibm_runtime`` logger, and ``QISKIT_IBM_RUNTIME_LOG_FILE`` can add a
    file handler. Records from child loggers reach those handlers even when the parent logger
    is disabled, so this uses ``logging.disable``, which drops records before any handler sees
    them. Capture is a one-shot command, so a process-wide setting is acceptable. No handler is
    added or removed. Python warnings are not affected.
    """
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def utc_datetimes(value: Any) -> Any:
    """Convert every aware ``datetime`` to UTC, recursively. The instant is unchanged.

    The client converts provider dates to the capturing machine's local timezone
    (``utc_to_local_all``). Converting back keeps payloads and content hashes independent of
    the machine.
    """
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo is not None else value
    if isinstance(value, dict):
        return {key: utc_datetimes(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [utc_datetimes(item) for item in value]
    return value


def _version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "not installed"


def capture_environment() -> dict[str, str]:
    return {name: _version(name) for name in ENVIRONMENT_PACKAGES}


def build_captured_calibration(
    *,
    backend_name: str,
    backend_version: str | None,
    source: SnapshotSource,
    properties: dict[str, Any] | None,
    configuration: dict[str, Any] | None,
    capture_options: dict[str, JsonValue],
    captured_at: datetime,
    environment: dict[str, str],
) -> CapturedCalibration:
    """Normalize to UTC, convert losslessly, redact, then extract measurements."""
    raw: JsonValue = {
        "properties": to_jsonable(utc_datetimes(properties)) if properties is not None else None,
        "configuration": (
            to_jsonable(utc_datetimes(configuration)) if configuration is not None else None
        ),
    }
    redacted, redactions = redact_payload(raw)
    if not isinstance(redacted, dict):  # pragma: no cover - redaction keeps the mapping shape
        raise TypeError("redaction changed the payload shape")
    stored_properties = redacted.get("properties")
    calibrated_at = (
        _date(stored_properties.get("last_update_date"))
        if isinstance(stored_properties, dict)
        else None
    )
    return CapturedCalibration(
        provider=PROVIDER_ID,
        backend_name=backend_name,
        backend_version=backend_version,
        source=source,
        captured_at=captured_at.astimezone(UTC),
        calibrated_at=calibrated_at,
        capture_options=capture_options,
        provider_raw=redacted,
        redactions=redactions,
        measurements=extract_measurements(stored_properties),
        extraction_method=EXTRACTION_METHOD,
        extraction_method_version=EXTRACTION_METHOD_VERSION,
        environment=environment,
    )


def _is_fake(backend: Any) -> bool:
    from qiskit_ibm_runtime.fake_provider.fake_backend import FakeBackendV2

    return isinstance(backend, FakeBackendV2)


class IbmLiveCalibrationSource:
    """Captures ``backend.properties(refresh=True)`` and ``backend.configuration()`` once."""

    use_fractional_gates = False

    def __init__(
        self, account: str = DEFAULT_ACCOUNT, service_factory: ServiceFactory | None = None
    ) -> None:
        self._account = account
        self._service_factory = service_factory or create_service

    def capture(self, backend_name: str) -> CapturedCalibration:
        if backend_name.startswith("fake_"):
            raise CaptureRejectedError(
                f"{backend_name!r} is a fake backend with frozen calibration; "
                "only live IBM hardware can be captured"
            )
        with quiet_client_logs():
            service = self._service_factory(name=self._account)
            backend = service.backend(backend_name, use_fractional_gates=self.use_fractional_gates)
            name = backend.name if isinstance(backend.name, str) else backend_name
            if _is_fake(backend) or name.startswith("fake_"):
                raise CaptureRejectedError(f"{name!r} is a fake backend; nothing was captured")
            configuration = backend.configuration()
            if getattr(configuration, "simulator", False):
                raise CaptureRejectedError(f"{name!r} is a simulator; nothing was captured")
            properties = backend.properties(refresh=True)
            captured_at = datetime.now(UTC)
        version = getattr(configuration, "backend_version", None)
        return build_captured_calibration(
            backend_name=name,
            backend_version=str(version) if version else None,
            source=SnapshotSource.LIVE_CALIBRATION,
            properties=properties.to_dict() if properties is not None else None,
            configuration=configuration.to_dict(),
            capture_options={"use_fractional_gates": self.use_fractional_gates},
            captured_at=captured_at,
            environment=capture_environment(),
        )


def load_account_secrets(account: str) -> list[str]:
    """Token, instance and URL of a saved account, for the export scan only. Never printed."""
    from qiskit_ibm_runtime.accounts import AccountManager

    with quiet_client_logs():
        saved = AccountManager.get(name=account)
    values = (saved.token, saved.instance, saved.url) if saved is not None else ()
    return [v for v in values if isinstance(v, str) and v]
