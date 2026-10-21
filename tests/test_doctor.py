"""``qci doctor`` (ADR 0009, section 4): every outcome of every check, with injected inputs."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

import qci
from conftest import REAL_ACCOUNT_LIST, make_run
from qci.adapters.qiskit_ibm import live
from qci.adapters.qiskit_ibm.extra import SDK_MODULES
from qci.cli import doctor
from qci.cli.app import app
from qci.storage.location import StoreLocation
from qci.storage.snapshots import SqliteSnapshotRepository
from qci.storage.sqlite import SqliteRunRepository
from test_store_read_only import _save_snapshot

VERSIONS = {
    "bloq-qci": qci.__version__,
    "pydantic": "2.12.0",
    "typer": "0.20.0",
    "sqlalchemy": "2.0.0",
    "numpy": "2.0.0",
    "openqasm3": "1.0.1",
    "qiskit": "2.5.2",
    "qiskit-ibm-runtime": "0.50.0",
    "qiskit-aer": "0.17.2",
}


def inputs(tmp_path: Path, **changes: object) -> doctor.DoctorInputs:
    base = doctor.DoctorInputs(
        python_version=(3, 13, 1),
        version_of=VERSIONS.get,
        missing_sdk_modules=lambda: [],
        account_lister=lambda: [live.DEFAULT_ACCOUNT],
        location=StoreLocation(tmp_path / "store", "QCI_HOME"),
        legacy=None,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def by_name(checks: list[doctor.Check], name: str) -> list[doctor.Check]:
    return [c for c in checks if c.name == name]


def one(checks: list[doctor.Check], name: str) -> doctor.Check:
    (check,) = by_name(checks, name)
    return check


def test_all_ok(tmp_path: Path) -> None:
    checks = doctor.run_checks(inputs(tmp_path))
    assert [c.outcome for c in checks] == ["ok"] * len(checks)
    assert [c.name for c in checks] == [
        "Python",
        "package",
        "core dependencies",
        "ibm extra",
        "saved IBM account",
        "store",
        "store",
    ]


# --- Python --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "outcome"),
    [((3, 12, 0), "ok"), ((3, 13, 9), "ok"), ((3, 14, 0), "note"), ((3, 11, 9), "problem")],
)
def test_python(version: tuple[int, int, int], outcome: str) -> None:
    check = doctor.check_python(version)
    assert check.outcome == outcome
    assert check.detail.startswith(".".join(map(str, version)))


# --- package -------------------------------------------------------------------------------------


def test_package() -> None:
    assert doctor.check_package(VERSIONS.get) == doctor.Check(
        "ok", "package", f"bloq-qci {qci.__version__}"
    )
    stale = doctor.check_package({**VERSIONS, "bloq-qci": "0.0.9"}.get)
    assert stale.outcome == "problem"
    assert "bloq-qci 0.0.9" in stale.detail and qci.__version__ in stale.detail
    absent = doctor.check_package(lambda name: None)
    assert absent.outcome == "problem" and "no bloq-qci distribution" in absent.detail


# --- core dependencies ---------------------------------------------------------------------------


def test_core_dependencies() -> None:
    ok = doctor.check_core(VERSIONS.get)
    assert ok.outcome == "ok" and "numpy 2.0.0" in ok.detail
    missing = doctor.check_core({k: v for k, v in VERSIONS.items() if k != "numpy"}.get)
    assert missing == doctor.Check("problem", "core dependencies", "missing numpy")


# --- ibm extra and saved account -----------------------------------------------------------------


def test_ibm_extra_installed_missing_and_partial(tmp_path: Path) -> None:
    ok = one(doctor.run_checks(inputs(tmp_path)), "ibm extra")
    assert ok.detail == "qiskit 2.5.2, qiskit-ibm-runtime 0.50.0, qiskit-aer 0.17.2"

    none = doctor.run_checks(inputs(tmp_path, missing_sdk_modules=lambda: list(SDK_MODULES)))
    note = one(none, "ibm extra")
    assert note.outcome == "note"
    assert "qci run" in note.detail and "pip install 'bloq-qci[ibm]'" in note.detail
    account = one(none, "saved IBM account")
    assert account == doctor.Check(
        "note", "saved IBM account", "not checked: the ibm extra is not installed"
    )

    partial = doctor.run_checks(inputs(tmp_path, missing_sdk_modules=lambda: ["qiskit_aer"]))
    assert one(partial, "ibm extra").outcome == "problem"
    assert "qiskit_aer missing" in one(partial, "ibm extra").detail
    assert one(partial, "saved IBM account").outcome == "note"


def test_account_outcomes(tmp_path: Path) -> None:
    def account(lister: doctor.AccountLister) -> doctor.Check:
        return one(doctor.run_checks(inputs(tmp_path, account_lister=lister)), "saved IBM account")

    assert account(lambda: [live.DEFAULT_ACCOUNT, "other"]).outcome == "ok"
    named = account(lambda: ["mine", "work"])
    assert named.outcome == "note"
    assert "saved accounts: mine, work" in named.detail
    assert account(lambda: []).outcome == "note"
    assert "no account file" in account(lambda: None).detail

    def broken() -> list[str]:
        raise json.JSONDecodeError("Expecting value: secret-looking-text", "doc", 0)

    problem = account(broken)
    assert problem == doctor.Check(
        "problem", "saved IBM account", "the account file cannot be read (JSONDecodeError)"
    )


SENTINELS = {
    "token": "SENTINEL-TOKEN-7f3a",
    "instance": "crn:SENTINEL-INSTANCE-91bc",
    "url": "https://SENTINEL-URL.example",
}
SENTINEL_CHANNEL = "SENTINEL-CHANNEL"


@pytest.fixture
def account_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The real AccountManager.list, over a temporary account file."""
    from qiskit_ibm_runtime.accounts import AccountManager, management

    path = tmp_path / "qiskit" / "qiskit-ibm.json"
    monkeypatch.setattr(management, "_DEFAULT_ACCOUNT_CONFIG_JSON_FILE", str(path))
    monkeypatch.setattr(AccountManager, "list", REAL_ACCOUNT_LIST[0])
    monkeypatch.setenv("QCI_HOME", str(tmp_path / "store"))
    return path


def _write_accounts(path: Path, accounts: dict[str, dict[str, str]]) -> bytes:
    path.parent.mkdir()
    path.write_text(json.dumps(accounts), encoding="utf-8")
    return path.read_bytes()


def test_a_saved_account_prints_only_its_name(account_file: Path) -> None:
    account = {**SENTINELS, "channel": "ibm_quantum_platform"}
    before = _write_accounts(account_file, {"sentinel-account-name": account})
    assert live.saved_account_names() == ["sentinel-account-name"]
    result = CliRunner().invoke(app, ["doctor"])
    assert (
        "note     saved IBM account: no account named default-ibm-quantum-platform; saved "
        "accounts: sentinel-account-name" in result.stdout
    )
    for value in SENTINELS.values():
        assert value not in result.stdout and value not in result.stderr
    assert account_file.read_bytes() == before


def test_an_account_with_an_unknown_channel_prints_only_the_exception_type(
    account_file: Path,
) -> None:
    """The client's error quotes the channel; doctor prints only the type."""
    account = {**SENTINELS, "channel": SENTINEL_CHANNEL}
    before = _write_accounts(account_file, {"sentinel-account-name": account})
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert (
        "problem  saved IBM account: the account file cannot be read (InvalidAccountError)"
        in result.stdout
    )
    for value in (*SENTINELS.values(), SENTINEL_CHANNEL):
        assert value not in result.stdout and value not in result.stderr
    assert account_file.read_bytes() == before


def test_an_unparseable_account_file_prints_only_the_exception_type(account_file: Path) -> None:
    account_file.parent.mkdir()
    account_file.write_text('{"x": SENTINEL-TOKEN-7f3a', encoding="utf-8")
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "problem  saved IBM account: the account file cannot be read (JSONDecodeError)" in (
        result.stdout
    )
    assert "SENTINEL" not in result.stdout + result.stderr


def test_no_account_file_is_never_created(account_file: Path) -> None:
    assert live.saved_account_names() is None
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert not account_file.parent.exists()


# --- store ---------------------------------------------------------------------------------------


def _store_lines(tmp_path: Path) -> tuple[list[doctor.Check], bytes | None]:
    location = StoreLocation(tmp_path / "store", "QCI_HOME")
    before = location.db.read_bytes() if location.db.exists() else None
    checks = by_name(doctor.run_checks(inputs(tmp_path, location=location)), "store")
    after = location.db.read_bytes() if location.db.exists() else None
    assert after == before
    return checks, before


def test_store_empty_when_absent(tmp_path: Path) -> None:
    checks, before = _store_lines(tmp_path)
    assert before is None and not (tmp_path / "store").exists()
    assert [(c.outcome, c.detail.split(";")[0]) for c in checks] == [
        ("ok", "runs empty"),
        ("ok", "snapshots empty"),
    ]
    assert checks[0].detail.endswith(f"{tmp_path / 'store' / 'qci.db'} (QCI_HOME)")


def test_store_healthy_runs_and_empty_snapshots(tmp_path: Path) -> None:
    repository = SqliteRunRepository(tmp_path / "store" / "qci.db")
    repository.save(make_run("A"))
    repository.save(make_run("B"))
    repository.close()
    checks, _ = _store_lines(tmp_path)
    assert [(c.outcome, c.detail.split(";")[0]) for c in checks] == [
        ("ok", "runs healthy, schema version 1, 2 runs"),
        ("ok", "snapshots empty"),
    ]


def test_store_healthy_snapshots_and_empty_runs(tmp_path: Path) -> None:
    _save_snapshot(tmp_path / "store" / "qci.db")
    checks, _ = _store_lines(tmp_path)
    assert [(c.outcome, c.detail.split(";")[0]) for c in checks] == [
        ("ok", "runs empty"),
        ("ok", "snapshots healthy, schema version 2, 1 snapshots"),
    ]


def _sql(db: Path, *statements: str) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as conn:
        for statement in statements:
            conn.execute(statement)
    conn.close()


def test_store_damaged_runs(tmp_path: Path) -> None:
    _sql(tmp_path / "store" / "qci.db", "create table runs (run_id text)")
    checks, _ = _store_lines(tmp_path)
    assert checks[0].outcome == "problem"
    assert checks[0].detail.startswith("runs damaged: ") and "schema_meta" in checks[0].detail
    assert (checks[1].outcome, checks[1].detail.split(";")[0]) == ("ok", "snapshots empty")


def test_store_damaged_snapshots(tmp_path: Path) -> None:
    _sql(tmp_path / "store" / "qci.db", "create table calibration_snapshots (snapshot_id text)")
    checks, _ = _store_lines(tmp_path)
    assert (checks[0].outcome, checks[0].detail.split(";")[0]) == ("ok", "runs empty")
    assert checks[1].outcome == "problem"
    assert checks[1].detail.startswith("snapshots damaged: ")


def test_store_other_schema_version_runs(tmp_path: Path) -> None:
    db = tmp_path / "store" / "qci.db"
    SqliteRunRepository(db).close()
    _sql(db, "update schema_meta set value = '99' where key = 'db_schema'")
    checks, _ = _store_lines(tmp_path)
    assert checks[0].outcome == "problem"
    assert checks[0].detail.startswith("runs other schema version: ")
    assert "db_schema 99; this QCI supports 1" in checks[0].detail


def test_store_other_schema_version_snapshots(tmp_path: Path) -> None:
    db = tmp_path / "store" / "qci.db"
    SqliteSnapshotRepository(db).close()
    _sql(db, "update schema_meta set value = '7' where key = 'snapshot_db_schema'")
    checks, _ = _store_lines(tmp_path)
    assert checks[1].outcome == "problem"
    assert "snapshot_db_schema 7; this QCI supports 1 and 2" in checks[1].detail


def test_legacy_store_is_a_note_with_its_health(tmp_path: Path) -> None:
    legacy = tmp_path / "work" / ".qci"
    repository = SqliteRunRepository(legacy / "qci.db")
    repository.save(make_run("A"))
    repository.close()
    before = (legacy / "qci.db").read_bytes()
    check = one(doctor.run_checks(inputs(tmp_path, legacy=legacy)), "legacy store")
    assert check.outcome == "note"
    assert "runs healthy, schema version 1, 1 runs; snapshots empty" in check.detail
    assert (legacy / "qci.db").read_bytes() == before


# --- exit codes and the command ------------------------------------------------------------------


def _cli(monkeypatch: pytest.MonkeyPatch, checks: list[doctor.Check]) -> tuple[int, str]:
    monkeypatch.setattr(doctor, "run_checks", lambda _: checks)
    result = CliRunner().invoke(app, ["doctor"])
    return result.exit_code, result.stdout


def test_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    ok = doctor.Check("ok", "a", "x")
    note = doctor.Check("note", "b", "y")
    problem = doctor.Check("problem", "c", "z")
    assert _cli(monkeypatch, [ok, note]) == (0, "ok       a: x\nnote     b: y\n")
    assert _cli(monkeypatch, [ok, note, problem])[0] == 1
    assert CliRunner().invoke(app, ["doctor", "--json"]).exit_code == 2


def test_doctor_on_the_store_leaves_its_bytes_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QCI_HOME", str(tmp_path))
    monkeypatch.setattr(live, "saved_account_names", lambda: [live.DEFAULT_ACCOUNT])
    repository = SqliteRunRepository(tmp_path / "qci.db")
    repository.save(make_run("A"))
    repository.close()
    snapshots = SqliteSnapshotRepository(tmp_path / "qci.db")
    snapshots.close()
    before = (tmp_path / "qci.db").read_bytes()
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0, result.stdout
    assert "ok       store: runs healthy, schema version 1, 1 runs" in result.stdout
    assert (tmp_path / "qci.db").read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["qci.db"]
