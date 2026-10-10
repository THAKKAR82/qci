"""``qci snapshot ...`` and ``qci snapshots`` through the CLI, with stub clients only."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from qci.adapters.qiskit_ibm import live
from qci.cli.app import app
from qci.domain.snapshot import CalibrationSnapshot, SnapshotFixture
from qci.services.snapshot_service import FIXTURE_SNAPSHOT_ID
from snapshot_stubs import (
    SENTINEL_ACCOUNT,
    SENTINEL_CRN,
    SENTINEL_TOKEN,
    SENTINELS,
    StubAccount,
    StubBackend,
    StubFactory,
    stub_properties,
)


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("QCI_HOME", str(tmp_path / "store"))
    return tmp_path / "store"


@pytest.fixture
def factory(monkeypatch: pytest.MonkeyPatch) -> StubFactory:
    stub = StubFactory()
    monkeypatch.setattr(live, "create_service", stub)
    return stub


def _capture(runner: CliRunner, *extra: str) -> tuple[int, str, str]:
    result = runner.invoke(app, ["snapshot", "capture", "--backend", "ibm_stub", *extra])
    return result.exit_code, result.stdout, result.stderr


def test_capture_persists_no_credentials(
    store: Path, factory: StubFactory, caplog: pytest.LogCaptureFixture
) -> None:
    code, out, err = _capture(CliRunner(), "--account", SENTINEL_ACCOUNT)
    assert code == 0, err
    assert factory.calls == [((), {"name": SENTINEL_ACCOUNT})]
    db_bytes = (store / "qci.db").read_bytes()
    for sentinel in SENTINELS:
        assert sentinel.encode() not in db_bytes
        assert sentinel not in out
        assert sentinel not in err
        assert sentinel not in caplog.text
    snapshot_id = out.strip()
    assert len(snapshot_id) == 26
    assert "New snapshot." in err
    assert "measurements: 9" in err


def test_second_identical_capture_reports_existing_snapshot(
    store: Path, factory: StubFactory
) -> None:
    runner = CliRunner()
    first = _capture(runner)
    second = _capture(runner)
    assert first[1] == second[1]
    assert "identical to this existing snapshot" in second[2]
    listing = runner.invoke(app, ["snapshots"])
    assert listing.exit_code == 0
    assert first[1].strip() in listing.stdout
    assert listing.stdout.strip().splitlines()[-1].endswith("  2")


def test_capture_rejects_fake_names_with_exit_2(store: Path, factory: StubFactory) -> None:
    result = CliRunner().invoke(app, ["snapshot", "capture", "--backend", "fake_fez"])
    assert result.exit_code == 2
    assert factory.calls == []
    assert not (store / "qci.db").exists()


def test_capture_rejects_simulators_with_exit_2(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live, "create_service", StubFactory(StubBackend(simulator=True)))
    code, _, err = _capture(CliRunner())
    assert code == 2
    assert "simulator" in err
    assert not (store / "qci.db").exists()


def test_capture_error_exits_1_sanitized_and_persists_nothing(
    store: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    error = RuntimeError(
        f"Account with the name {SENTINEL_ACCOUNT} failed for {SENTINEL_CRN} "
        f"(Authorization: Bearer {SENTINEL_TOKEN})"
    )
    monkeypatch.setattr(live, "create_service", StubFactory(error=error))
    code, out, err = _capture(CliRunner(), "--account", SENTINEL_ACCOUNT)
    assert code == 1
    assert out == ""
    assert "RuntimeError" in err and "Nothing was recorded." in err
    for sentinel in SENTINELS:
        assert sentinel not in err
        assert sentinel not in caplog.text
    assert not (store / "qci.db").exists()


def test_show_json_validates_as_calibration_snapshot(store: Path, factory: StubFactory) -> None:
    runner = CliRunner()
    snapshot_id = _capture(runner)[1].strip()
    shown = runner.invoke(app, ["snapshot", "show", snapshot_id, "--json"])
    assert shown.exit_code == 0
    snap = CalibrationSnapshot.model_validate_json(shown.stdout)
    assert snap.snapshot_id == snapshot_id
    assert snap.backend_name == "ibm_stub"
    text = runner.invoke(app, ["snapshot", "show", snapshot_id])
    assert text.exit_code == 0
    assert "source:         live_calibration" in text.stdout
    assert "captures:       1" in text.stdout
    missing = runner.invoke(app, ["snapshot", "show", "NOPE"])
    assert missing.exit_code == 1


def test_snapshots_on_an_empty_store(store: Path) -> None:
    result = CliRunner().invoke(app, ["snapshots"])
    assert result.exit_code == 0
    assert "No snapshots recorded yet." in result.stdout


def test_export_writes_a_sanitized_plain_fixture(
    tmp_path: Path, store: Path, factory: StubFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live, "load_account_secrets", lambda name: [StubAccount.token])
    runner = CliRunner()
    snapshot_id = _capture(runner)[1].strip()
    path = tmp_path / "out" / "ibm_stub.json"
    result = runner.invoke(app, ["snapshot", "export", snapshot_id, "--fixture", str(path)])
    assert result.exit_code == 0, result.stderr
    text = path.read_text(encoding="utf-8")
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    fixture = SnapshotFixture.model_validate_json(text)
    assert fixture.fixture_origin == "live_capture"
    assert fixture.snapshot.snapshot_id == FIXTURE_SNAPSHOT_ID
    assert [c.capture_id for c in fixture.captures] == ["FIXTURE-CAPTURE-1"]
    assert snapshot_id not in text
    for sentinel in SENTINELS:
        assert sentinel not in text


def test_fixture_export_aborts_on_account_match(
    tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planted = "planted-value-no-rule-covers-7d1e"
    props = stub_properties()
    props["qubits"][0].append({"name": "harmless_looking", "unit": "", "value": planted})
    monkeypatch.setattr(live, "create_service", StubFactory(StubBackend(properties=props)))
    monkeypatch.setattr(live, "load_account_secrets", lambda name: [planted])
    runner = CliRunner()
    snapshot_id = _capture(runner)[1].strip()
    path = tmp_path / "fixture.json"
    result = runner.invoke(app, ["snapshot", "export", snapshot_id, "--fixture", str(path)])
    assert result.exit_code != 0
    assert not path.exists()
    assert planted not in result.stderr and planted not in result.stdout


def test_export_aborts_when_the_saved_account_cannot_be_read(
    tmp_path: Path, store: Path, factory: StubFactory
) -> None:
    # The session guard makes AccountManager.get raise, as a missing account would.
    runner = CliRunner()
    snapshot_id = _capture(runner)[1].strip()
    path = tmp_path / "fixture.json"
    result = runner.invoke(app, ["snapshot", "export", snapshot_id, "--fixture", str(path)])
    assert result.exit_code == 1
    assert "Nothing was written." in result.stderr
    assert not path.exists()
