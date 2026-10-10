"""Offline stand-ins for the IBM runtime client, with sentinel credentials (ADR 0005, section 5).

The stubs mimic only what ``IbmLiveCalibrationSource`` touches: ``service.backend(...)``,
``backend.name``, ``backend.configuration()`` and ``backend.properties(refresh=True)``. Dates
are produced in the process's local timezone, as the real client produces them.
"""

import copy
import logging
import math
from datetime import UTC, datetime
from typing import Any

from qci.core.ports import CapturedCalibration
from qci.domain.backend import SnapshotSource
from qci.domain.snapshot import Measurement

SENTINEL_TOKEN = "SENTINELTOKEN0a1b2c3d"
SENTINEL_CRN = "crn:v1:bluemix:public:quantum-computing:us-east:a/SENTINELACCT::SENTINELINST::"
SENTINEL_ACCOUNT = "sentinel-account-name"
SENTINEL_JWT = "eyJSENTINELJWThdr.eyJSENTINELJWTbody.SENTINELJWTsig"
SENTINELS = (
    SENTINEL_TOKEN,
    SENTINEL_CRN,
    "SENTINELACCT",
    "SENTINELINST",
    SENTINEL_ACCOUNT,
    "SENTINELJWT",
)

CALIBRATED = datetime(2026, 10, 8, 6, 30, tzinfo=UTC)


def local(value: datetime) -> datetime:
    """The same instant in the local timezone, as ``utc_to_local_all`` returns it."""
    return value.astimezone()


def stub_properties(t1: float = 182.4) -> dict[str, Any]:
    d = local(CALIBRATED)
    return {
        "backend_name": "ibm_stub",
        "backend_version": "1.0.0",
        "last_update_date": d,
        "qubits": [
            [
                {"date": d, "name": "T1", "unit": "us", "value": t1},
                {"date": d, "name": "readout_error", "unit": "", "value": 0.01},
                {"date": d, "name": "odd_nan", "unit": "", "value": math.nan},
                {"date": d, "name": "odd_complex", "unit": "", "value": complex(1, 2)},
            ],
            [{"date": d, "name": "T1", "unit": "us", "value": 150.0}],
        ],
        "gates": [
            {
                "gate": "cz",
                "qubits": [0, 1],
                "name": "cz0_1",
                "parameters": [{"date": d, "name": "gate_error", "unit": "", "value": 0.003}],
            },
            {
                "gate": "sx",
                "qubits": [0],
                "name": "sx0",
                "parameters": [
                    {"date": d, "name": "gate_error", "unit": "", "value": 0.0002},
                    {"date": d, "name": "note", "unit": "", "value": f"Bearer {SENTINEL_TOKEN}"},
                ],
            },
        ],
        "general": [{"date": d, "name": "jq_01", "unit": "GHz", "value": 0.002}],
    }


def stub_configuration(name: str = "ibm_stub", simulator: bool = False) -> dict[str, Any]:
    return {
        "backend_name": name,
        "backend_version": "1.0.0",
        "n_qubits": 2,
        "simulator": simulator,
        "basis_gates": ["cz", "sx", "rz", "x", "id"],
        "coupling_map": [[0, 1], [1, 0]],
        "gates": [{"name": "cz", "parameters": [], "coupling_map": [[0, 1], [1, 0]]}],
        "supported_instructions": ["cz", "sx", "measure", "reset", "delay"],
        "url": f"https://user:{SENTINEL_TOKEN}@example.invalid/api",
        "instance": SENTINEL_CRN,
        "online_date": local(datetime(2024, 7, 1, tzinfo=UTC)),
        "links": [f"https://example.invalid/backends?apikey={SENTINEL_TOKEN}"],
        "processor_type": {"family": "Heron", "revision": 2, "owner": SENTINEL_CRN},
        "contact": "ops-SENTINELACCT@example.invalid",
    }


class _Payload:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        for key, value in data.items():
            setattr(self, key, value)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)


class StubBackend:
    def __init__(
        self,
        name: str = "ibm_stub",
        simulator: bool = False,
        properties: dict[str, Any] | None = None,
        no_properties: bool = False,
    ) -> None:
        self.name = name
        self._instance = SENTINEL_CRN
        self._token = SENTINEL_TOKEN
        self._configuration = _Payload(stub_configuration(name, simulator))
        self._properties = None if no_properties else _Payload(properties or stub_properties())
        self.properties_calls: list[dict[str, Any]] = []

    def configuration(self) -> _Payload:
        return self._configuration

    def properties(self, **kwargs: Any) -> _Payload | None:
        self.properties_calls.append(kwargs)
        return self._properties


class StubAccount:
    token = SENTINEL_TOKEN
    instance = SENTINEL_CRN
    url = "https://example.invalid/sentinel-endpoint"


class StubService:
    def __init__(self, backend: StubBackend, error: Exception | None = None) -> None:
        self._backend = backend
        self._error = error
        self._account = StubAccount()
        self.backend_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def backend(self, *args: Any, **kwargs: Any) -> Any:
        self.backend_calls.append((args, kwargs))
        # The real client logs instance identifiers; these must never reach the user.
        logging.getLogger("qiskit_ibm_runtime.qiskit_runtime_service").warning(
            "Using instance: %s, token %s", SENTINEL_CRN, SENTINEL_TOKEN
        )
        if self._error is not None:
            raise self._error
        return self._backend


class StubFactory:
    """Records how it was called. Tests assert the exact keyword arguments."""

    def __init__(self, backend: StubBackend | None = None, error: Exception | None = None):
        self.backend = backend or StubBackend()
        self.error = error
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.services: list[StubService] = []

    def __call__(self, *args: Any, **kwargs: Any) -> StubService:
        self.calls.append((args, kwargs))
        service = StubService(self.backend, self.error)
        self.services.append(service)
        return service


def captured(
    t1: float = 182.4,
    measurements: list[Measurement] | None = None,
    captured_at: datetime = CALIBRATED,
) -> CapturedCalibration:
    """A minimal CapturedCalibration, for storage and service tests."""
    return CapturedCalibration(
        provider="qiskit_ibm",
        backend_name="ibm_stub",
        backend_version="1.0.0",
        source=SnapshotSource.LIVE_CALIBRATION,
        captured_at=captured_at,
        calibrated_at=CALIBRATED,
        capture_options={"use_fractional_gates": False},
        provider_raw={"properties": {"qubits": [[{"name": "T1", "value": t1}]]}},
        redactions=[],
        measurements=(
            measurements
            if measurements is not None
            else [
                Measurement(
                    resource_kind="qubit", resource="qubit/0", parameter="T1", value=t1, unit="us"
                )
            ]
        ),
        extraction_method="test",
        extraction_method_version="1",
        environment={"qci": "0.0.1"},
    )


SYNTHETIC_CAPTURED_AT = datetime(2026, 10, 9, tzinfo=UTC)


def synthetic_fake_fez_fixture_text() -> str:
    """The SYNTHETIC fixture: FakeFez's frozen configuration and properties, passed through the
    same path as a live capture (UTC normalization, lossless conversion, redaction, measurement
    extraction, storage, export). Its source is ``static_fake`` and its backend ``fake_fez``.
    Generated per test session (about a second); never committed.
    """
    import tempfile
    from pathlib import Path

    from qiskit_ibm_runtime.fake_provider import FakeFez

    from qci.adapters.qiskit_ibm.live import build_captured_calibration, capture_environment
    from qci.adapters.qiskit_ibm.redact import redact_payload
    from qci.services.snapshot_service import SnapshotService
    from qci.storage.snapshots import SqliteSnapshotRepository

    fake = FakeFez()
    configuration = fake.configuration()
    environment = capture_environment()
    result = build_captured_calibration(
        backend_name=fake.name,
        backend_version=str(configuration.backend_version),
        source=SnapshotSource.STATIC_FAKE,
        properties=fake.properties().to_dict(),
        configuration=configuration.to_dict(),
        capture_options={"use_fractional_gates": False},
        captured_at=SYNTHETIC_CAPTURED_AT,
        environment=environment,
    )
    note = (
        "SYNTHETIC: derived from the frozen FakeFez configuration and properties shipped with "
        f"qiskit-ibm-runtime {environment['qiskit-ibm-runtime']}. Not a live capture."
    )
    with tempfile.TemporaryDirectory() as tmp:
        repository = SqliteSnapshotRepository(Path(tmp) / "qci.db")
        try:
            service = SnapshotService(repository)
            outcome = service.record(result)
            return service.export_fixture(
                outcome.snapshot.snapshot_id, redact=redact_payload, secrets=[], note=note
            )
        finally:
            repository.close()
