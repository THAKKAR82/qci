"""Golden run-comparison JSON, written before the M1.3c refactor (ADR 0005, section 7).

Each file is ``CompareService.compare(...).model_dump_json(indent=2)`` for fixed runs, one per
``compare_hardware`` exit. Current output must equal each file byte for byte. The refactor that
extracts ``compare_calibration`` must leave every file unchanged.

Every scenario uses one shared simulator seed, so the TVD sampling floor is withheld. The floor
records the installed numpy version, and pinning that here would tie the files to one
environment. The floor has its own tests.

To regenerate deliberately (never in the refactor commit): ``QCI_REGENERATE_GOLDEN=1 pytest
tests/test_compare_golden.py``.
"""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from conftest import ibm_properties, make_run, physical_bell_qasm, physical_run
from qci.adapters.qiskit_ibm.calibration import IbmPropertiesCalibrationReader
from qci.domain.comparison import ObservableSpec
from qci.domain.run import Run, RunError, RunStage, RunStatus
from qci.services.compare_service import CompareService
from qci.storage.sqlite import SqliteRunRepository

GOLDEN = Path(__file__).resolve().parent / "golden" / "compare"
READERS = {"qiskit_ibm": IbmPropertiesCalibrationReader()}
SEED = 7
DYNAMIC_QASM = "OPENQASM 3.0;\nbit[1] c;\nc[0] = measure $0;\nif (c[0]) {\n  x $1;\n}\n"


def _run(run_id: str, **kwargs: Any) -> Run:
    kwargs.setdefault("qasm3", physical_bell_qasm(1, 0))
    return physical_run(run_id, seed_simulator=SEED, **kwargs)


def _date_only() -> Run:
    props = ibm_properties()
    props["qubits"][1][0]["date"] = {"$datetime": "2025-03-01T00:00:00+00:00"}
    return _run("CAND", properties=props)


def _missing_parameter() -> Run:
    props = ibm_properties()
    props["qubits"][0][0]["value"] = None
    return _run("CAND", properties=props)


def _unit_mismatch() -> Run:
    props = ibm_properties()
    props["qubits"][1][0]["unit"] = "ns"
    return _run("CAND", properties=props)


def _no_snapshot() -> Run:
    """A succeeded run always has a snapshot, so only a failed run reaches this exit."""
    return make_run(
        "CAND",
        status=RunStatus.FAILED,
        error=RunError(stage=RunStage.RESOLVE_BACKEND, error_type="E", message="m"),
        backend=None,
        backend_snapshot=None,
        compilation=None,
        execution=None,
        result=None,
        metrics=[],
    )


Scenario = tuple[Callable[[], Run], Callable[[], Run], list[ObservableSpec]]

SCENARIOS: dict[str, Scenario] = {
    "unchanged": (lambda: _run("BASE"), lambda: _run("CAND"), []),
    "changed_used_qubit": (
        lambda: _run("BASE"),
        lambda: _run("CAND", properties=ibm_properties(t1={1: 80.0})),
        [],
    ),
    "changed_used_gate": (
        lambda: _run("BASE"),
        lambda: _run("CAND", properties=ibm_properties(ecr_error=0.009)),
        [],
    ),
    "unused_qubit_only": (
        lambda: _run("BASE"),
        lambda: _run("CAND", properties=ibm_properties(t1={3: 5.0})),
        [],
    ),
    "date_only": (lambda: _run("BASE"), _date_only, []),
    "different_mapping": (
        lambda: _run("BASE", layout=([1, 0], [1, 0])),
        lambda: _run(
            "CAND",
            qasm3=physical_bell_qasm(2, 1),
            layout=([2, 1], [2, 1]),
            properties=ibm_properties(t1={0: 10.0, 1: 90.0, 2: 20.0}),
        ),
        [],
    ),
    "missing_relevant_parameter": (lambda: _run("BASE"), _missing_parameter, []),
    "unit_mismatch": (lambda: _run("BASE"), _unit_mismatch, []),
    "missing_snapshot": (lambda: _run("BASE"), _no_snapshot, []),
    "dynamic_footprint": (lambda: _run("BASE"), lambda: _run("CAND", qasm3=DYNAMIC_QASM), []),
    "unknown_provider": (
        lambda: _run("BASE", provider="unknown"),
        lambda: _run("CAND", provider="unknown"),
        [],
    ),
    "cross_provider": (lambda: _run("BASE"), lambda: _run("CAND", provider="other"), []),
    "observable": (
        lambda: _run("BASE"),
        lambda: _run(
            "CAND",
            counts={"c": {"00": 40, "11": 55, "01": 5}},
            properties=ibm_properties(t1={1: 80.0}),
        ),
        [ObservableSpec(name="bell", bitstrings=["00", "11"])],
    ),
}


def _output(name: str, repo: SqliteRunRepository) -> str:
    baseline, candidate, observables = SCENARIOS[name]
    repo.save(baseline())
    repo.save(candidate())
    return (
        CompareService(repo, READERS).compare("BASE", "CAND", observables).model_dump_json(indent=2)
    )


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_run_comparison_matches_golden_file(name: str, repo: SqliteRunRepository) -> None:
    path = GOLDEN / f"{name}.json"
    text = _output(name, repo) + "\n"
    if os.environ.get("QCI_REGENERATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == text


def test_every_golden_file_has_a_scenario() -> None:
    assert sorted(p.stem for p in GOLDEN.glob("*.json")) == sorted(SCENARIOS)
