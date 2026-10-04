"""End-to-end `qci compare` on real runs against the local IBM fake backend."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qci.cli.app import app
from qci.domain.comparison import Comparison

ROOT = Path(__file__).resolve().parents[1]
BELL = ROOT / "examples" / "bell.py"


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("QCI_HOME", str(tmp_path / "store"))
    return CliRunner()


def run(runner: CliRunner, *args: str, workload: Path = BELL) -> str:
    result = runner.invoke(app, ["run", str(workload), "--backend", "fake_sherbrooke", *args])
    assert result.exit_code == 0, result.output
    return result.stdout.strip().splitlines()[0]


def compare_json(runner: CliRunner, baseline: str, candidate: str) -> dict[str, Any]:
    result = runner.invoke(app, ["compare", baseline, candidate, "--json"])
    assert result.exit_code == 0, result.output
    Comparison.model_validate_json(result.stdout)
    data: dict[str, Any] = json.loads(result.stdout)
    return data


def test_same_seed_runs_are_unchanged_and_json_is_byte_identical(runner: CliRunner) -> None:
    a, b = run(runner, "--seed", "7"), run(runner, "--seed", "7")
    first = runner.invoke(app, ["compare", a, b, "--json"]).stdout
    second = runner.invoke(app, ["compare", a, b, "--json"]).stdout
    assert first == second
    c = json.loads(first)
    assert c["status"] == "unchanged"
    assert c["baseline_run_id"] == a and c["candidate_run_id"] == b
    assert c["distribution"]["tvd"]["value"] == 0.0
    assert c["hardware"]["relevant_hardware_changed"] is False
    assert c["hardware"]["global_snapshot_changed"] is False
    assert c["footprint"]["status"] == "unchanged"
    # Same simulator seed: the samples are not independent, so no sampling floor is computed.
    assert c["distribution"]["sampling_floor"] is None
    assert "same simulator seed (7)" in c["distribution"]["sampling_floor_unavailable_reason"]

    text = runner.invoke(app, ["compare", a, b])
    assert text.exit_code == 0
    assert "status:    unchanged" in text.stdout and "no causal attribution" in text.stdout
    (tvd_line,) = [line for line in text.stdout.splitlines() if line.startswith("  tvd = ")]
    assert "| sampling floor unavailable: both samples were drawn with the same simulator seed" in (
        tvd_line
    )
    for banned in ("better", "worse", "regression", "improve", "PASS", "FAIL"):
        assert banned not in text.stdout.replace(
            "regression, improvement, better/worse or pass/fail", ""
        )


def test_different_seed_changes_execution_and_counts_only(runner: CliRunner) -> None:
    a, b = run(runner, "--seed", "7"), run(runner, "--seed", "8")
    c = compare_json(runner, a, b)
    assert c["execution"]["status"] == "changed"
    assert c["execution"]["seed_simulator"] == {
        "status": "changed",
        "baseline": 7,
        "candidate": 8,
        "delta": None,
    }
    assert c["compilation"]["seed_transpiler"]["status"] == "changed"
    assert c["logical_circuit"]["status"] == "unchanged"
    # For Bell at optimization level 2 both seeds choose the same physical qubits.
    assert c["footprint"]["status"] == "unchanged"
    assert c["hardware"]["relevant_hardware_changed"] is False
    assert c["distribution"]["status"] == "changed"
    assert c["distribution"]["reasons"] == []
    assert c["distribution"]["tvd"]["value"] > 0
    assert c["distribution"]["tvd"]["kind"] == "calculated"


def test_sampling_floor_json_is_byte_identical_and_shown_beside_tvd(runner: CliRunner) -> None:
    a, b = run(runner, "--seed", "7"), run(runner, "--seed", "8")
    first = runner.invoke(app, ["compare", a, b, "--json"]).stdout
    second = runner.invoke(app, ["compare", a, b, "--json"]).stdout
    assert first == second
    floor = json.loads(first)["distribution"]["sampling_floor"]
    assert floor["resamples"] == 2000
    assert isinstance(floor["seed"], int) and 0 <= floor["seed"] < 2**53
    assert f'"seed": {floor["seed"]},' in first  # a JSON integer, not a float or string
    for name in ("null_p50", "null_p95", "null_p99", "p_value"):
        assert floor[name]["kind"] == "statistical"

    text = runner.invoke(app, ["compare", a, b])
    assert text.exit_code == 0
    (tvd_line,) = [line for line in text.stdout.splitlines() if line.startswith("  tvd = ")]
    assert "| sampling floor under H0 (B=2000): p50 " in tvd_line
    assert ", p95 " in tvd_line and ", p99 " in tvd_line
    assert re.search(r"\| Monte Carlo p = \d\.\d+ ± \d\.\d+  \[statistical; v2\]$", tvd_line)
    (hellinger_line,) = [
        line for line in text.stdout.splitlines() if line.startswith("  hellinger_distance = ")
    ]
    assert "sampling floor" not in hellinger_line
    assert "Hellinger distance still has no sampling floor" in text.stdout


def test_changed_mapping_reports_footprint_and_never_cross_resource_deltas(
    runner: CliRunner,
) -> None:
    a = run(runner, "--seed", "7")  # optimization level 2 maps to physical qubits 103/104
    b = run(runner, "--seed", "7", "--optimization-level", "0")  # trivial layout: 0/1
    c = compare_json(runner, a, b)
    fp = c["footprint"]
    assert fp["resources_identical"] is False
    assert fp["initial_layout"]["status"] == "changed"
    shared = set(fp["qubits"]["common"])
    assert set(fp["qubits"]["baseline_only"]) and set(fp["qubits"]["candidate_only"])
    hw = c["hardware"]
    assert hw["relevant_hardware_changed"] is None
    assert hw["status"] == "partially_comparable"
    for p in hw["shared_resource_parameters"]:
        assert set(p["qubits"]) <= shared
    assert c["distribution"]["status"] == "changed"  # same logical circuit: still comparable


def test_different_workload_is_not_comparable_but_counts_are_shown(
    runner: CliRunner, tmp_path: Path
) -> None:
    ghz = tmp_path / "ghz.py"
    ghz.write_text(
        "from qiskit import QuantumCircuit\n\n\ndef build():\n"
        "    qc = QuantumCircuit(3, 3, name='ghz')\n    qc.h(0)\n    qc.cx(0, 1)\n"
        "    qc.cx(1, 2)\n    qc.measure([0, 1, 2], [0, 1, 2])\n    return qc\n"
    )
    a, b = run(runner, "--seed", "7"), run(runner, "--seed", "7", workload=ghz)
    c = compare_json(runner, a, b)
    assert c["distribution"]["status"] == "not_comparable"
    assert any("logical circuit changed" in r for r in c["distribution"]["reasons"])
    assert c["distribution"]["sampling_floor"] is None
    assert c["baseline_counts"] and c["candidate_counts"]
    assert c["source"]["source_sha256"]["status"] == "changed"


def test_compare_against_failed_run(runner: CliRunner) -> None:
    a = run(runner, "--seed", "7")
    failed = runner.invoke(app, ["run", str(BELL), "--backend", "no_such_backend"])
    assert failed.exit_code == 1
    f = failed.stdout.strip().splitlines()[0]
    c = compare_json(runner, a, f)
    assert c["status"] == "partially_comparable"
    assert c["distribution"]["status"] == "unavailable"
    assert c["distribution"]["sampling_floor"] is None
    assert c["candidate_footprint"]["status"] == "unavailable"


def test_unknown_run_exits_nonzero(runner: CliRunner) -> None:
    assert runner.invoke(app, ["compare", "NOPE", "NOPE2"]).exit_code == 1


def test_observable_json_is_byte_identical_and_rendered(runner: CliRunner) -> None:
    a, b = run(runner, "--seed", "7"), run(runner, "--seed", "8")
    args = ["compare", a, b, "--observable", "bell=11,00", "--observable", "odd=01,10"]
    first = runner.invoke(app, [*args, "--json"])
    second = runner.invoke(app, [*args, "--json"])
    assert first.exit_code == 0, first.output
    assert first.stdout == second.stdout
    c = Comparison.model_validate_json(first.stdout)
    assert [o.spec.name for o in c.observables] == ["bell", "odd"]
    assert c.observables[0].spec.bitstrings == ["00", "11"]
    assert c.observables[0].baseline is not None and c.observables[0].baseline.n == 1000
    assert c.comparison_id != compare_json(runner, a, b)["comparison_id"]

    text = runner.invoke(app, args)
    assert text.exit_code == 0, text.output
    assert "Observables: 2 requested" in text.stdout
    assert "bell = P({00, 11})" in text.stdout
    assert "Wilson [" in text.stdout and "Newcombe [" in text.stdout
    section = text.stdout.split("Observables:")[1].split("Limitations:")[0].lower()
    for word in ("significant", "regression", "improvement", "better", "worse", "pass", "fail"):
        assert word not in section


@pytest.mark.parametrize(
    "value", ["bell", "bell=", "=00", "bell=0a", "bell=00,00", "bell=00,111", "1bell=00"]
)
def test_malformed_observable_exits_with_usage_error(runner: CliRunner, value: str) -> None:
    a = run(runner, "--seed", "7")
    result = runner.invoke(app, ["compare", a, a, "--observable", value])
    assert result.exit_code == 2


def test_observable_of_wrong_width_exits_with_usage_error(runner: CliRunner) -> None:
    a = run(runner, "--seed", "7")
    result = runner.invoke(app, ["compare", a, a, "--observable", "ghz=00000,11111"])
    assert result.exit_code == 2
    assert "wrong width" in result.output
