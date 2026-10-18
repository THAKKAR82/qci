"""Historical calibration lookups on IBM devices (ADR 0008). Executes nothing.

``backend.properties(datetime=T)`` returns the latest properties document stamped before
``T``. ``configuration()`` has no history, so a lookup stores ``configuration: null`` and the
current configuration is never paired with an older document. The client is built only as
``QiskitRuntimeService(name=ACCOUNT)`` through the same factory as ``qci snapshot capture``.

The client reinterprets a datetime whose offset is not zero as local time (``local_to_utc``),
so a lookup sends only aware UTC datetimes with a zero offset. QCI retries nothing. The
client's own HTTP session retries some 5xx responses (up to 5 times, with backoff); 429 is not
among them and reaches QCI at once.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from qci.adapters.qiskit_ibm import live
from qci.adapters.qiskit_ibm.adapter_ids import PROVIDER_ID
from qci.adapters.qiskit_ibm.live import (
    DEFAULT_ACCOUNT,
    ServiceFactory,
    _is_fake,
    build_captured_calibration,
    capture_environment,
    quiet_client_logs,
)
from qci.core.errors import BackfillRejectedError, TooManyRequestsError
from qci.core.ports import CapturedCalibration
from qci.domain.backend import SnapshotSource

VERIFIED_LOOKUP_DEPTH_DAYS: Mapping[str, int] = {
    "ibm_fez": 365,
    "ibm_kingston": 365,
    "ibm_marrakesh": 365,
}
"""Device -> verified historical lookup depth in days, from the D21 verification (M1.5b,
ADR 0008 Findings, 2026-10-18). Explicit and exact: a device not listed is not backfilled,
and an entry is added only after its own verification."""

USE_FRACTIONAL_GATES = False


def is_too_many_requests(exc: BaseException) -> bool:
    """HTTP 429 or IBM error code 1202 anywhere in the exception chain."""
    seen: BaseException | None = exc
    while seen is not None:
        if getattr(seen, "status_code", None) == 429 or "Error code: 1202" in str(seen):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def _too_many_requests() -> TooManyRequestsError:
    return TooManyRequestsError(
        "the provider answered with too-many-requests (HTTP 429 or IBM error code 1202)"
    )


class IbmHistoricalLookup:
    def __init__(self, backend: Any, backend_name: str) -> None:
        self._backend = backend
        self._backend_name = backend_name

    def lookup(self, requested_before: datetime) -> CapturedCalibration:
        if requested_before.utcoffset() != timedelta(0):
            raise ValueError("requested_before must be an aware UTC datetime with a zero offset")
        at = requested_before.astimezone(UTC)
        with quiet_client_logs():
            try:
                properties = self._backend.properties(datetime=at)
            except Exception as exc:
                if is_too_many_requests(exc):
                    raise _too_many_requests() from exc
                raise
            captured_at = datetime.now(UTC)
        raw = properties.to_dict() if properties is not None else None
        version = raw.get("backend_version") if isinstance(raw, dict) else None
        return build_captured_calibration(
            backend_name=self._backend_name,
            backend_version=str(version) if version else None,
            source=SnapshotSource.HISTORICAL_LOOKUP,
            properties=raw,
            configuration=None,
            capture_options={"use_fractional_gates": USE_FRACTIONAL_GATES},
            captured_at=captured_at,
            environment=capture_environment(),
            requested_before=at,
        )


class IbmHistoricalCalibrationSource:
    provider = PROVIDER_ID

    def __init__(
        self, account: str = DEFAULT_ACCOUNT, service_factory: ServiceFactory | None = None
    ) -> None:
        self._account = account
        # Looked up when constructed, so a test can replace ``live.create_service``.
        self._service_factory = service_factory or live.create_service

    def verified_depth_days(self, backend_name: str) -> int | None:
        if backend_name.startswith("fake_"):
            raise BackfillRejectedError(
                f"{backend_name!r} is a fake backend with frozen calibration; only listed live "
                "IBM devices are backfilled. Nothing was requested."
            )
        return VERIFIED_LOOKUP_DEPTH_DAYS.get(backend_name)

    def open(self, backend_name: str) -> IbmHistoricalLookup:
        self.verified_depth_days(backend_name)
        with quiet_client_logs():
            try:
                service = self._service_factory(name=self._account)
                backend = service.backend(backend_name, use_fractional_gates=USE_FRACTIONAL_GATES)
                name = backend.name if isinstance(backend.name, str) else backend_name
                if _is_fake(backend) or name.startswith("fake_"):
                    raise BackfillRejectedError(
                        f"{name!r} is a fake backend; nothing was requested"
                    )
                # Read only to reject simulators; never stored with a lookup.
                if getattr(backend.configuration(), "simulator", False):
                    raise BackfillRejectedError(f"{name!r} is a simulator; nothing was requested")
            except BackfillRejectedError:
                raise
            except Exception as exc:
                if is_too_many_requests(exc):
                    raise _too_many_requests() from exc
                raise
        if name != backend_name:
            raise BackfillRejectedError(
                f"the client resolved {backend_name!r} as {name!r}; nothing was requested"
            )
        return IbmHistoricalLookup(backend, name)
