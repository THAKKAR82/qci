"""The IBM live calibration source against stub clients. No network, no account."""

import logging
import time
from pathlib import Path

import pytest

from conftest import ForbiddenInTestsError
from qci.adapters.qiskit_ibm import live
from qci.adapters.qiskit_ibm.live import IbmLiveCalibrationSource
from qci.core.errors import CaptureRejectedError
from qci.domain.backend import SnapshotSource
from qci.services.snapshot_service import SnapshotService
from qci.storage.snapshots import SqliteSnapshotRepository
from snapshot_stubs import CALIBRATED, SENTINELS, StubBackend, StubFactory, stub_properties


def test_client_is_built_only_from_a_named_saved_account() -> None:
    factory = StubFactory()
    IbmLiveCalibrationSource(account="my-account", service_factory=factory).capture("ibm_stub")
    assert factory.calls == [((), {"name": "my-account"})]
    assert factory.services[0].backend_calls == [(("ibm_stub",), {"use_fractional_gates": False})]
    assert factory.backend.properties_calls == [{"refresh": True}]


def test_default_account_name() -> None:
    factory = StubFactory()
    IbmLiveCalibrationSource(service_factory=factory).capture("ibm_stub")
    assert factory.calls == [((), {"name": "default-ibm-quantum-platform"})]


def test_fake_names_are_rejected_before_any_client_is_built() -> None:
    factory = StubFactory()
    with pytest.raises(CaptureRejectedError):
        IbmLiveCalibrationSource(service_factory=factory).capture("fake_fez")
    assert factory.calls == []


def test_simulators_are_rejected() -> None:
    factory = StubFactory(StubBackend(simulator=True))
    with pytest.raises(CaptureRejectedError, match="simulator"):
        IbmLiveCalibrationSource(service_factory=factory).capture("ibm_stub")


def test_fake_backend_objects_are_rejected_whatever_their_name() -> None:
    from qiskit_ibm_runtime.fake_provider import FakeFez

    factory = StubFactory()
    factory.backend = FakeFez()  # FakeFez is untyped (Any) under mypy
    with pytest.raises(CaptureRejectedError, match="fake"):
        IbmLiveCalibrationSource(service_factory=factory).capture("ibm_fez")


def test_capture_is_redacted_utc_and_labeled_live() -> None:
    result = IbmLiveCalibrationSource(service_factory=StubFactory()).capture("ibm_stub")
    assert result.source is SnapshotSource.LIVE_CALIBRATION
    assert result.calibrated_at == CALIBRATED
    assert result.capture_options == {"use_fractional_gates": False}
    assert result.backend_version == "1.0.0"
    assert set(result.environment) == {"qci", "qiskit", "qiskit-ibm-runtime"}
    text = repr(result)
    for sentinel in SENTINELS:
        assert sentinel not in text
    props = result.provider_raw["properties"]
    assert isinstance(props, dict)
    assert props["last_update_date"] == {"$datetime": "2026-10-08T06:30:00+00:00"}
    assert "$.configuration.instance" in result.redactions
    assert "$.configuration.url" in result.redactions


def test_measurements_null_for_unrepresentable_and_absent_when_unreported() -> None:
    result = IbmLiveCalibrationSource(service_factory=StubFactory()).capture("ibm_stub")
    by_key = {(m.resource, m.parameter): m for m in result.measurements}
    assert by_key[("qubit/0", "T1")].value == 182.4
    assert by_key[("qubit/0", "T1")].unit == "us"
    assert by_key[("qubit/0", "readout_error")].unit is None
    assert by_key[("qubit/0", "odd_nan")].value is None
    assert by_key[("qubit/0", "odd_complex")].value is None
    assert by_key[("gate/sx/0", "note")].value is None  # redacted bearer token
    assert by_key[("gate/cz/0,1", "gate_error")].value == 0.003
    assert by_key[("general", "jq_01")].unit == "GHz"
    assert ("qubit/1", "readout_error") not in by_key
    assert all(m.value != 0 for m in result.measurements)
    assert len(result.measurements) == 9


def test_missing_properties_are_stored_as_null_with_no_measurements() -> None:
    factory = StubFactory(StubBackend(no_properties=True))
    result = IbmLiveCalibrationSource(service_factory=factory).capture("ibm_stub")
    assert result.provider_raw["properties"] is None
    assert result.measurements == []
    assert result.calibrated_at is None


def test_client_log_records_never_reach_handlers(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    previous = logging.root.manager.disable
    IbmLiveCalibrationSource(service_factory=StubFactory()).capture("ibm_stub")
    for sentinel in SENTINELS:
        assert sentinel not in caplog.text
    assert logging.root.manager.disable == previous
    logging.getLogger("qiskit_ibm_runtime.after").warning("logging is restored")
    assert "logging is restored" in caplog.text


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset is POSIX-only")
def test_content_hash_does_not_depend_on_local_timezone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = SqliteSnapshotRepository(tmp_path / "qci.db")
    service = SnapshotService(repo)
    offsets = []
    try:
        for tz in ("AAA+05", "BBB-05:30"):
            monkeypatch.setenv("TZ", tz)
            time.tzset()
            props = stub_properties()
            offsets.append(props["last_update_date"].utcoffset())
            factory = StubFactory(StubBackend(properties=props))
            service.capture(IbmLiveCalibrationSource(service_factory=factory), "ibm_stub")
    finally:
        monkeypatch.undo()
        time.tzset()
    assert offsets[0] != offsets[1], "the two captures must really use different local offsets"
    items = repo.list_snapshots()
    repo.close()
    assert len(items) == 1
    assert items[0].capture_count == 2


def test_guard_blocks_the_real_client_and_saved_accounts() -> None:
    with pytest.raises(ForbiddenInTestsError):
        live.create_service(name="default-ibm-quantum-platform")
    with pytest.raises(ForbiddenInTestsError):
        live.load_account_secrets("default-ibm-quantum-platform")


def test_guard_blocks_network_connections() -> None:
    import socket

    with pytest.raises(ForbiddenInTestsError):
        socket.create_connection(("example.invalid", 443))
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s,
        pytest.raises(ForbiddenInTestsError),
    ):
        s.connect(("127.0.0.1", 9))
