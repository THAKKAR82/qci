"""Selectors for runs and snapshots (ADR 0009, section 5)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import make_run, physical_bell_qasm, physical_run
from qci.adapters.qiskit_ibm import live
from qci.cli.app import app
from qci.core.selectors import (
    Entry,
    SelectorAmbiguousError,
    SelectorNotFoundError,
    SelectorUsageError,
    resolve,
)
from qci.domain.run import RunError, RunStage, RunStatus
from test_cli_golden import FAKE_FEZ_RUN_ID, pinned_fake_fez_run, save_runs, save_snapshots
from test_snapshot_compare import _qubit, derive, fez

# --- the pure function ---------------------------------------------------------------------------

A = "01JA000000AAAAAAAAAAAAAAAA"
B = "01JB000000BBBBBBBBBBBBBBBB"
C = "01JC000000CCCCCCCCCCCCCCCC"
RUNS: list[Entry] = [(A, "fake_fez", A), (C, "fake_fez", C), (B, "fake_kingston", B)]


def stamp(day: int) -> str:
    return (datetime(2026, 10, day, tzinfo=UTC)).strftime("%Y-%m-%dT%H:%M:%S.%f")


SNAPS: list[Entry] = [
    ("S1" + "1" * 24, "ibm_fez", stamp(3)),
    ("S2" + "2" * 24, "ibm_fez", stamp(1)),
    ("S3" + "3" * 24, "ibm_fez", None),
    ("S4" + "4" * 24, "ibm_fez", stamp(2)),
    ("S5" + "5" * 24, "ibm_kingston", stamp(9)),
]


def test_full_id_and_stored_short_id_match_exactly() -> None:
    assert resolve(B, RUNS, "run") == B
    assert resolve("BASE", [("BASE", None, "BASE")], "run") == "BASE"


def test_unique_prefix_of_8_to_25_characters() -> None:
    assert resolve("01JB0000", RUNS, "run") == B
    assert resolve(C[:25], RUNS, "run") == C


def test_prefix_ambiguity_lists_at_most_ten_and_a_count() -> None:
    entries: list[Entry] = [(f"01JX0000{i:02d}" + "Q" * 16, None, None) for i in range(13)]
    with pytest.raises(SelectorAmbiguousError) as info:
        resolve("01JX0000", entries, "run")
    message = str(info.value)
    assert message.startswith("prefix '01JX0000' matches 13 runs:\n")
    assert message.count("\n  01JX0000") == 10
    assert message.endswith("\n  and 3 more")


@pytest.mark.parametrize("selector", ["01JZ0000", "0" * 26])
def test_no_match(selector: str) -> None:
    with pytest.raises(SelectorNotFoundError):
        resolve(selector, RUNS, "run")


@pytest.mark.parametrize(
    "selector",
    [
        "01JB000",
        "NOPE",
        "",
        "0" * 27,
        "latest~0",
        "latest~",
        "latest~x",
        "latest~-1",
        "latest~01",
        "fake_fez:",
        ":latest",
        "fake_fez:latest:1",
        "a:b",
        "latest~1~2",
    ],
)
def test_malformed_selectors_are_usage_errors(selector: str) -> None:
    with pytest.raises(SelectorUsageError):
        resolve(selector, RUNS, "run")


def test_latest_runs_by_id_descending_with_optional_backend() -> None:
    assert resolve("latest", RUNS, "run") == C
    assert resolve("latest~1", RUNS, "run") == B
    assert resolve("latest~2", RUNS, "run") == A
    assert resolve("fake_fez:latest", RUNS, "run") == C
    assert resolve("fake_fez:latest~1", RUNS, "run") == A
    assert resolve("fake_kingston:latest", RUNS, "run") == B
    with pytest.raises(SelectorNotFoundError, match="there are 3 runs"):
        resolve("latest~3", RUNS, "run")
    with pytest.raises(SelectorNotFoundError, match="there are 1 runs on fake_kingston"):
        resolve("fake_kingston:latest~1", RUNS, "run")
    with pytest.raises(SelectorNotFoundError):
        resolve("ibm_fez:latest", RUNS, "run")


def test_runs_in_the_same_millisecond_are_ambiguous() -> None:
    twin = A[:10] + "Z" * 16
    entries = [*RUNS, (twin, "fake_fez", twin)]
    with pytest.raises(SelectorAmbiguousError) as info:
        resolve("latest~2", entries, "run")
    message = str(info.value)
    assert "same millisecond" in message
    assert f"  {A}  fake_fez" in message and f"  {twin}  fake_fez" in message
    assert resolve("latest~1", entries, "run") == B


def test_latest_snapshots_by_calibrated_at_with_required_backend() -> None:
    assert resolve("ibm_fez:latest", SNAPS, "snapshot") == SNAPS[0][0]
    assert resolve("ibm_fez:latest~1", SNAPS, "snapshot") == SNAPS[3][0]
    assert resolve("ibm_fez:latest~2", SNAPS, "snapshot") == SNAPS[1][0]
    with pytest.raises(SelectorNotFoundError, match="with a calibrated_at"):
        resolve("ibm_fez:latest~3", SNAPS, "snapshot")  # S3 has no calibrated_at
    assert resolve("ibm_kingston:latest", SNAPS, "snapshot") == SNAPS[4][0]
    for selector in ("latest", "latest~1"):
        with pytest.raises(SelectorUsageError, match="names its backend"):
            resolve(selector, SNAPS, "snapshot")


def test_snapshots_with_equal_calibrated_at_are_ambiguous() -> None:
    twin = ("S6" + "6" * 24, "ibm_fez", stamp(2))
    with pytest.raises(SelectorAmbiguousError, match="share their calibrated_at"):
        resolve("ibm_fez:latest~1", [*SNAPS, twin], "snapshot")
    assert resolve("ibm_fez:latest", [*SNAPS, twin], "snapshot") == SNAPS[0][0]


# --- every argument of every command -------------------------------------------------------------

BASE_ID = "01JBASE000AAAAAAAAAAAAAAAA"
CAND_ID = "01JCAND000AAAAAAAAAAAAAAAA"
OLD_ID = "01SNAPA000AAAAAAAAAAAAAAAA"
NEW_ID = "01SNAPB000AAAAAAAAAAAAAAAA"
RECALIBRATED = datetime(2026, 10, 20, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Runs: FAKE_FEZ_RUN_ID (newest), CAND_ID, BASE_ID. Snapshots of ibm_fez: OLD_ID (the
    fixture's calibration), and NEW_ID (calibrated later, but captured a day earlier, so
    ``qci snapshots`` lists it second)."""
    monkeypatch.setenv("QCI_HOME", str(tmp_path))
    monkeypatch.setattr(live, "load_account_secrets", lambda name: [])
    monkeypatch.chdir(tmp_path)
    qasm = physical_bell_qasm(1, 0)
    save_runs(
        tmp_path,
        physical_run(BASE_ID, qasm3=qasm, seed_simulator=7),
        physical_run(CAND_ID, qasm3=qasm, seed_simulator=8),
        pinned_fake_fez_run(),
    )
    newer = derive(
        lambda p: _qubit(p, 0, "T1").update(value=1.0),
        snapshot_id=NEW_ID,
        calibrated_at=RECALIBRATED,
        captured_at=fez().captured_at - timedelta(days=1),
    )
    save_snapshots(tmp_path, newer, fez(OLD_ID))
    return tmp_path


def invoke(*args: str) -> tuple[int, str, str]:
    result = CliRunner().invoke(app, list(args))
    return result.exit_code, result.stdout, result.stderr


# Each case: command arguments with {0}, {1}, {2} where the selectors go, the full IDs those
# select, the roles echoed, and selector triples to try.
CASES: list[tuple[str, list[str], list[str], list[str], list[tuple[str, ...]]]] = [
    (
        "show",
        ["show", "{0}"],
        [CAND_ID],
        ["run"],
        [("01JCAND0",), ("latest~1",), ("stub_backend:latest",)],
    ),
    (
        "compare",
        ["compare", "{0}", "{1}", "--observable", "bell=00,11"],
        [BASE_ID, CAND_ID],
        ["baseline", "candidate"],
        [
            ("01JBASE0", "01JCAND000AAA"),
            ("latest~2", "latest~1"),
            ("stub_backend:latest~1", "stub_backend:latest"),
        ],
    ),
    (
        "snapshot show",
        ["snapshot", "show", "{0}"],
        [NEW_ID],
        ["snapshot"],
        [("01SNAPB0",), ("ibm_fez:latest",)],
    ),
    (
        "snapshot compare",
        [
            "snapshot",
            "compare",
            "{0}",
            "{1}",
            "--footprint-run",
            "{2}",
            "--allow-footprint-backend-mismatch",
        ],
        [OLD_ID, NEW_ID, FAKE_FEZ_RUN_ID],
        ["baseline", "candidate", "footprint run"],
        [
            ("01SNAPA0", "01SNAPB0", "01R1B000"),
            ("ibm_fez:latest~1", "ibm_fez:latest", "latest"),
            ("ibm_fez:latest~1", "ibm_fez:latest", "fake_fez:latest"),
        ],
    ),
    (
        "snapshot compare-run",
        ["snapshot", "compare-run", "{0}", "{1}"],
        [FAKE_FEZ_RUN_ID, OLD_ID],
        ["run", "snapshot"],
        [("01R1B00000000FAKE", "01SNAPA000"), ("fake_fez:latest", "ibm_fez:latest~1")],
    ),
]


def _fill(template: list[str], values: tuple[str, ...] | list[str]) -> list[str]:
    return [part.format(*values) for part in template]


@pytest.mark.parametrize(
    ("template", "ids", "roles", "selectors"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_selectors_select_the_same_output_as_full_ids(
    store: Path,
    template: list[str],
    ids: list[str],
    roles: list[str],
    selectors: list[tuple[str, ...]],
    as_json: bool,
) -> None:
    extra = ["--json"] if as_json else []
    before = (store / "qci.db").read_bytes()
    code, expected, err = invoke(*_fill(template, ids), *extra)
    assert code == 0, err
    assert err == ""
    for chosen in selectors:
        code, out, err = invoke(*_fill(template, chosen), *extra)
        assert code == 0, err
        assert out == expected, chosen
        echoes = [f"{role}: {s} -> {i}" for role, s, i in zip(roles, chosen, ids, strict=True)]
        assert err.splitlines() == echoes
    assert (store / "qci.db").read_bytes() == before


def test_export_accepts_a_selector(store: Path) -> None:
    code, _, err = invoke("snapshot", "export", OLD_ID, "--fixture", "by_id.json")
    assert code == 0, err
    code, _, err = invoke("snapshot", "export", "ibm_fez:latest~1", "--fixture", "selected.json")
    assert code == 0, err
    assert err.splitlines()[0] == f"snapshot: ibm_fez:latest~1 -> {OLD_ID}"
    assert (store / "selected.json").read_bytes() == (store / "by_id.json").read_bytes()


def test_snapshot_latest_ignores_storage_order(store: Path) -> None:
    code, listed, _ = invoke("snapshots")
    assert code == 0
    assert listed.index(OLD_ID) < listed.index(NEW_ID)  # captured later, listed first
    code, _, err = invoke("snapshot", "show", "ibm_fez:latest")
    assert err == f"snapshot: ibm_fez:latest -> {NEW_ID}\n"


def test_a_failed_run_can_be_selected(store: Path) -> None:
    failed_id = "01ZFAILED0AAAAAAAAAAAAAAAA"
    failed = make_run(
        failed_id,
        status=RunStatus.FAILED,
        error=RunError(stage=RunStage.EXECUTE, error_type="E", message="m"),
        execution=None,
        result=None,
    )
    save_runs(store, failed)
    code, out, err = invoke("show", "latest")
    assert code == 0, err
    assert err == f"run: latest -> {failed_id}\n"
    assert "status:     failed" in out


@pytest.mark.parametrize(
    ("args", "code", "message"),
    [
        (["show", "NOPE"], 2, "a prefix needs 8 to 25 characters"),
        (["show", "latest~0"], 2, "'~' must be followed by an integer of 1 or more"),
        (["snapshot", "show", "latest"], 2, "names its backend"),
        (["show", "01JZZZZZ"], 1, "no run ID starts with '01JZZZZZ'"),
        (["show", "latest~3"], 1, "selects nothing: there are 3 runs"),
        (["snapshot", "show", "ibm_torino:latest"], 1, "there are 0 snapshots on ibm_torino"),
        (["compare", "01JBASE0", "nope:latest"], 1, "there are 0 runs on nope"),
    ],
)
def test_errors_select_nothing_and_print_no_stdout(
    store: Path, args: list[str], code: int, message: str
) -> None:
    before = (store / "qci.db").read_bytes()
    exit_code, out, err = invoke(*args)
    assert exit_code == code, err
    assert out == ""
    assert message in err
    assert (store / "qci.db").read_bytes() == before


def test_ambiguous_prefix_through_the_cli(store: Path) -> None:
    code, out, err = invoke("compare", "01JBASE0", "01JCA")
    assert code == 2 and out == ""
    code, out, err = invoke("show", "01JB")
    assert code == 2
    save_runs(store, physical_run("01JBASE0ZZAAAAAAAAAAAAAAAA", qasm3=None))
    code, out, err = invoke("show", "01JBASE0")
    assert code == 1 and out == ""
    assert "prefix '01JBASE0' matches 2 runs:" in err
    assert f"  {BASE_ID}  stub_backend" in err


def test_runs_created_in_one_millisecond_are_not_ordered_by_guess(store: Path) -> None:
    twin = CAND_ID[:10] + "ZZZZZZZZZZZZZZZZ"
    save_runs(store, physical_run(twin, qasm3=None))
    code, out, err = invoke("show", "latest~1")
    assert code == 1 and out == ""
    assert "were created in the same millisecond" in err
    assert CAND_ID in err and twin in err


def test_snapshots_with_one_calibrated_at_are_not_ordered_by_guess(store: Path) -> None:
    twin = derive(
        lambda p: _qubit(p, 1, "T1").update(value=2.0),
        snapshot_id="01SNAPC000AAAAAAAAAAAAAAAA",
        calibrated_at=RECALIBRATED,
        captured_at=RECALIBRATED + timedelta(hours=1),
    )
    save_snapshots(store, twin)
    code, out, err = invoke("snapshot", "show", "ibm_fez:latest")
    assert code == 1 and out == ""
    assert "share their calibrated_at" in err
    assert NEW_ID in err and twin.snapshot_id in err
