"""Per-user store, ``qci where`` and the ``./.qci`` note (ADR 0009, section 3)."""

import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import make_run
from qci.cli.app import app
from qci.storage.location import (
    StoreLocation,
    legacy_note,
    legacy_store,
    store_location,
    user_data_directory,
)
from qci.storage.sqlite import SqliteRunRepository

HOME = Path("/home/someone")
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("platform", "environ", "expected"),
    [
        ("darwin", {}, HOME / "Library" / "Application Support" / "qci"),
        ("win32", {"LOCALAPPDATA": "/data/local"}, Path("/data/local") / "qci"),
        ("win32", {}, HOME / "AppData" / "Local" / "qci"),
        ("win32", {"LOCALAPPDATA": ""}, HOME / "AppData" / "Local" / "qci"),
        ("linux", {"XDG_DATA_HOME": "/xdg/data"}, Path("/xdg/data") / "qci"),
        ("linux", {"XDG_DATA_HOME": "relative/data"}, HOME / ".local" / "share" / "qci"),
        ("linux", {}, HOME / ".local" / "share" / "qci"),
        ("freebsd14", {}, HOME / ".local" / "share" / "qci"),
    ],
    ids=[
        "darwin",
        "win32-localappdata",
        "win32-no-localappdata",
        "win32-empty-localappdata",
        "other-xdg-absolute",
        "other-xdg-relative",
        "other-xdg-unset",
        "freebsd",
    ],
)
def test_per_user_directory(platform: str, environ: dict[str, str], expected: Path) -> None:
    assert user_data_directory(platform, environ, HOME) == expected
    location = store_location(platform, environ, HOME)
    assert location == StoreLocation(expected.absolute(), "per-user default")
    assert location.db == expected.absolute() / "qci.db"


def test_qci_home_overrides_and_empty_counts_as_unset(tmp_path: Path) -> None:
    for platform in ("darwin", "win32", "linux"):
        chosen = store_location(platform, {"QCI_HOME": str(tmp_path)}, HOME)
        assert chosen == StoreLocation(tmp_path, "QCI_HOME")
        empty = store_location(platform, {"QCI_HOME": ""}, HOME)
        assert empty.source == "per-user default"


def test_relative_qci_home_is_made_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert store_location("linux", {"QCI_HOME": "rel"}, HOME).directory == tmp_path / "rel"


def _default_db() -> Path:
    return store_location().db


READ_ONLY = [
    ["runs"],
    ["show", "01ARZ3NDEKTSV4RRFFQ69G5FAV"],
    ["compare", "01ARZ3NDEKTSV4RRFFQ69G5FAV", "01ARZ3NDEKTSV4RRFFQ69G5FAW"],
    ["snapshots"],
    ["snapshot", "show", "01ARZ3NDEKTSV4RRFFQ69G5FAV"],
    ["where"],
    ["doctor"],
]


@pytest.mark.parametrize("args", READ_ONLY, ids=" ".join)
def test_read_only_commands_on_a_missing_per_user_store_create_nothing(
    args: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("qci.adapters.qiskit_ibm.live.saved_account_names", lambda: None)
    home = Path(os.environ["HOME"])
    result = CliRunner().invoke(app, args)
    assert result.exit_code in (0, 1), result.output
    assert list(home.iterdir()) == []
    assert list(tmp_path.iterdir()) == []
    if args == ["runs"]:
        assert result.stdout == "No runs recorded yet.\n"
    if args == ["snapshots"]:
        assert result.stdout == "No snapshots recorded yet.\n"


def test_first_write_creates_the_per_user_directory_with_mode_0o700(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    directory = _default_db().parent
    assert not directory.parent.exists()
    result = CliRunner().invoke(
        app,
        ["run", str(ROOT / "examples" / "bell.py"), "--backend", "fake_sherbrooke", "--seed", "7"],
    )
    assert result.exit_code == 0, result.output
    assert (directory / "qci.db").is_file()
    if os.name == "posix":
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    listed = CliRunner().invoke(app, ["runs"])
    assert result.stdout.strip() in listed.stdout


def test_an_existing_directory_keeps_its_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = tmp_path / "store"
    store.mkdir(mode=0o755)
    store.chmod(0o755)
    monkeypatch.setenv("QCI_HOME", str(store))
    result = CliRunner().invoke(app, ["run", str(tmp_path / "missing.py"), "--backend", "fake_fez"])
    assert result.exit_code == 2
    assert stat.S_IMODE(store.stat().st_mode) == 0o755


# --- qci where -----------------------------------------------------------------------------------


def test_where_prints_the_default_path_and_opens_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["where"])
    assert result.exit_code == 0
    assert result.stdout == f"{_default_db()}\n"
    assert Path(result.stdout.strip()).is_absolute()
    assert result.stderr == (
        "source: per-user default\n"
        "file: does not exist yet (the first command that writes creates it)\n"
    )
    assert not _default_db().parent.exists()


def test_where_with_qci_home_and_an_existing_damaged_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "qci.db").write_bytes(b"not a database")
    monkeypatch.setenv("QCI_HOME", str(tmp_path))
    result = CliRunner().invoke(app, ["where"])
    assert result.exit_code == 0
    assert result.stdout == f"{tmp_path / 'qci.db'}\n"
    assert result.stderr == "source: QCI_HOME\nfile: exists\n"
    assert (tmp_path / "qci.db").read_bytes() == b"not a database"


# --- the ./.qci note -----------------------------------------------------------------------------

RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
NOTED = [
    ["runs"],
    ["show", RUN_ID],
    ["compare", RUN_ID, RUN_ID],
    ["snapshots"],
    ["snapshot", "show", RUN_ID],
    ["snapshot", "compare", RUN_ID, RUN_ID, "--footprint-run", RUN_ID],
    ["snapshot", "compare-run", RUN_ID, RUN_ID],
    ["snapshot", "export", RUN_ID, "--fixture", "out.json"],
    ["snapshot", "capture", "--backend", "ibm_fez"],
    ["snapshot", "backfill", "--backend", "ibm_fez", "--days", "1"],
    ["run", "missing.py", "--backend", "fake_fez"],
    ["where"],
    ["doctor"],
]


@pytest.fixture
def legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A ./.qci/qci.db with one run, in a working directory of its own."""
    work = tmp_path / "work"
    (work / ".qci").mkdir(parents=True)
    repository = SqliteRunRepository(work / ".qci" / "qci.db")
    repository.save(make_run(RUN_ID))
    repository.close()
    monkeypatch.setattr("qci.adapters.qiskit_ibm.live.saved_account_names", lambda: None)
    return work


def _expected_note(work: Path) -> str:
    return legacy_note(work / ".qci", store_location()) + "\n"


def test_note_text(legacy: Path) -> None:
    assert _expected_note(legacy) == (
        f"note: ./.qci/qci.db exists, but QCI now uses {_default_db()} by default.\n"
        "To keep using that store, set QCI_HOME to its directory:\n"
        f'  export QCI_HOME="{legacy / ".qci"}"\n'
    )


@pytest.mark.parametrize("args", NOTED, ids=" ".join)
def test_every_command_prints_the_note_and_changes_nothing_else(
    legacy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    db = legacy / ".qci" / "qci.db"
    before = (db.read_bytes(), db.stat().st_mtime_ns)
    plain = tmp_path / "plain"
    plain.mkdir()

    monkeypatch.chdir(plain)
    without = CliRunner().invoke(app, args)
    monkeypatch.chdir(legacy)
    with_note = CliRunner().invoke(app, args)

    assert with_note.stderr.startswith(_expected_note(legacy))
    assert with_note.stderr.count("note: ./.qci/qci.db exists") == 1
    assert "./.qci/qci.db exists" not in without.stderr
    assert with_note.exit_code == without.exit_code
    if args == ["doctor"]:
        # doctor reports the legacy store as one of its checks, on stdout (section 4).
        (extra,) = [x for x in with_note.stdout.splitlines() if x not in without.stdout]
        assert extra.startswith("note     legacy store: ./.qci/qci.db exists")
        assert with_note.stdout.replace(extra + "\n", "") == without.stdout
    else:
        assert with_note.stdout == without.stdout
    assert (db.read_bytes(), db.stat().st_mtime_ns) == before


def test_no_note_when_qci_home_is_set(legacy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(legacy)
    monkeypatch.setenv("QCI_HOME", str(legacy / ".qci"))
    result = CliRunner().invoke(app, ["runs"])
    assert result.exit_code == 0
    assert result.stderr == ""
    assert RUN_ID in result.stdout


def test_no_note_from_a_subdirectory(legacy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    child = legacy / "child"
    child.mkdir()
    monkeypatch.chdir(child)
    assert legacy_store(child) is None
    assert CliRunner().invoke(app, ["runs"]).stderr == ""


def test_no_note_for_a_directory_named_qci_db(tmp_path: Path) -> None:
    (tmp_path / ".qci" / "qci.db").mkdir(parents=True)
    assert legacy_store(tmp_path, {}) is None
    assert legacy_store(tmp_path, {"QCI_HOME": ""}) is None
