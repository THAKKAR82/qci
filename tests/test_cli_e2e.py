"""End-to-end M0 workflow through the CLI on the local IBM fake backend (no network)."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from conftest import StubAdapter
from qci.cli.app import app
from qci.domain.circuit import CompileConfig
from qci.domain.execution import ExecutionConfig
from qci.services.run_service import RunRequest, RunService
from qci.storage.sqlite import SqliteRunRepository

ROOT = Path(__file__).resolve().parents[1]
BELL = ROOT / "examples" / "bell.py"

# Fields expected to differ between two otherwise identical runs.
VOLATILE = {
    ("run_id",),
    ("created_at",),
    ("backend_snapshot", "captured_at"),
    ("compilation", "duration_ms"),
    ("execution", "started_at"),
    ("execution", "finished_at"),
    ("execution", "provider_job_id"),
}


def _mask(record: dict[str, Any]) -> dict[str, Any]:
    masked: dict[str, Any] = json.loads(json.dumps(record))
    for path in VOLATILE:
        target = masked
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = "<volatile>"
    return masked


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("QCI_HOME", str(tmp_path / "store"))
    return CliRunner()


def _run_bell(runner: CliRunner) -> str:
    result = runner.invoke(app, ["run", str(BELL), "--backend", "fake_sherbrooke", "--seed", "7"])
    assert result.exit_code == 0, result.output
    run_id = result.stdout.strip().splitlines()[0]
    assert len(run_id) == 26
    return run_id


def _show_json(runner: CliRunner, run_id: str) -> dict[str, Any]:
    result = runner.invoke(app, ["show", run_id, "--json"])
    assert result.exit_code == 0, result.output
    data: dict[str, Any] = json.loads(result.stdout)
    return data


def test_bell_workflow_is_captured_persisted_and_deterministic(runner: CliRunner) -> None:
    first, second = _run_bell(runner), _run_bell(runner)
    assert first != second

    # AC2: runs lists both runs, newest first.
    listing = runner.invoke(app, ["runs"])
    assert listing.exit_code == 0
    lines = listing.stdout.strip().splitlines()
    assert lines[1].startswith(second) and lines[2].startswith(first)
    assert "succeeded" in lines[1] and "bell" in lines[1] and "fake_sherbrooke" in lines[1]

    # AC3: human-readable show covers every section.
    shown = runner.invoke(app, ["show", first])
    assert shown.exit_code == 0
    for expected in (
        "Provenance:",
        "source sha256:",
        "Logical circuit:",
        "Transpiled circuit:",
        "optimization_level=2 seed_transpiler=7",
        "source: static_fake",
        "calibrated at: 2025-02-26",
        "shots=1000 seed_simulator=7",
        "Result (measured",
        "[measured;",
        "[calculated;",
    ):
        assert expected in shown.stdout, expected

    a, b = _show_json(runner, first), _show_json(runner, second)

    # AC4: identical except for volatile identifiers and timestamps.
    assert _mask(a) == _mask(b)
    assert a["result"]["counts"] == b["result"]["counts"]
    assert a["compilation"]["output"]["qasm3"] == b["compilation"]["output"]["qasm3"]
    assert a["compilation"]["config_hash"] == b["compilation"]["config_hash"]
    assert a["execution"]["config_hash"] == b["execution"]["config_hash"]

    # Data distinctions are preserved.
    assert a["status"] == "succeeded"
    assert a["workload"]["entrypoint"] == "build"
    assert a["logical_circuit"]["num_qubits"] == 2
    assert a["compilation"]["output"]["num_qubits"] == 127
    assert a["backend"] == {
        "provider": "qiskit_ibm",
        "name": "fake_sherbrooke",
        "version": "1.6.58",
        "num_qubits": 127,
        "is_simulator": True,
    }
    assert a["backend_snapshot"]["source"] == "static_fake"
    assert a["result"]["total_shots"] == 1000
    assert sum(a["result"]["counts"]["c"].values()) == 1000


def test_raw_backend_payloads_are_preserved_verbatim(runner: CliRunner) -> None:
    from qiskit_ibm_runtime.fake_provider import FakeSherbrooke

    from qci.adapters.qiskit_ibm.jsonable import to_jsonable

    record = _show_json(runner, _run_bell(runner))
    raw = record["backend_snapshot"]["provider_raw"]
    fresh = FakeSherbrooke()
    assert raw["properties"] == to_jsonable(fresh.properties().to_dict())
    assert raw["configuration"] == to_jsonable(fresh.configuration().to_dict())
    assert len(raw["properties"]["qubits"]) == 127


def test_unknown_backend_is_recorded_as_failed_run(runner: CliRunner) -> None:
    result = runner.invoke(app, ["run", str(BELL), "--backend", "no_such_backend", "--seed", "7"])
    assert result.exit_code == 1
    run_id = result.stdout.strip().splitlines()[0]
    record = _show_json(runner, run_id)
    assert record["status"] == "failed"
    assert record["error"]["stage"] == "resolve_backend"
    assert record["error"]["error_type"] == "qci.core.errors.UnknownBackendError"


def test_failed_execution_run_is_displayed_by_show(runner: CliRunner, tmp_path: Path) -> None:
    repo = SqliteRunRepository(tmp_path / "store" / "qci.db")
    failed = RunService(StubAdapter(executor_error=RuntimeError("boom")), repo).run(
        RunRequest(
            workload_path=BELL,
            backend_name="stub_backend",
            compile_config=CompileConfig(optimization_level=1),
            execution_config=ExecutionConfig(shots=10),
        )
    )
    repo.close()
    shown = runner.invoke(app, ["show", failed.run_id])
    assert shown.exit_code == 0
    assert "status:     failed" in shown.stdout
    assert "stage: execute" in shown.stdout
    assert "builtins.RuntimeError" in shown.stdout


def test_missing_workload_records_nothing(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["run", str(tmp_path / "missing.py"), "--backend", "fake_sherbrooke"]
    )
    assert result.exit_code == 2
    assert "No run was recorded" in result.output
    assert "No runs recorded yet." in runner.invoke(app, ["runs"]).stdout


def test_show_unknown_run_fails(runner: CliRunner) -> None:
    result = runner.invoke(app, ["show", "NOPE"])
    assert result.exit_code == 1
