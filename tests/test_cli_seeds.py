"""Independent transpiler/simulator seeds: precedence and backward compatibility."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from qci.cli.app import EffectiveSeeds, app, resolve_seeds

BELL = Path(__file__).resolve().parents[1] / "examples" / "bell.py"


@pytest.mark.parametrize(
    ("seed", "seed_transpiler", "seed_simulator", "expected"),
    [
        (None, None, None, EffectiveSeeds(transpiler=None, simulator=None)),
        (7, None, None, EffectiveSeeds(transpiler=7, simulator=7)),
        (None, 7, None, EffectiveSeeds(transpiler=7, simulator=None)),
        (None, None, 8, EffectiveSeeds(transpiler=None, simulator=8)),
        (7, None, 8, EffectiveSeeds(transpiler=7, simulator=8)),
        (7, 9, None, EffectiveSeeds(transpiler=9, simulator=7)),
        (7, 9, 8, EffectiveSeeds(transpiler=9, simulator=8)),
        (0, None, None, EffectiveSeeds(transpiler=0, simulator=0)),  # 0 is a real seed
        (5, 0, 0, EffectiveSeeds(transpiler=0, simulator=0)),
    ],
)
def test_seed_precedence(
    seed: int | None,
    seed_transpiler: int | None,
    seed_simulator: int | None,
    expected: EffectiveSeeds,
) -> None:
    assert resolve_seeds(seed, seed_transpiler, seed_simulator) == expected


def _run_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> dict[str, object]:
    monkeypatch.setenv("QCI_HOME", str(tmp_path / "store"))
    runner = CliRunner()
    result = runner.invoke(app, ["run", str(BELL), "--backend", "fake_sherbrooke", *args])
    assert result.exit_code == 0, result.output
    run_id = result.stdout.strip().splitlines()[0]
    shown = runner.invoke(app, ["show", run_id, "--json"])
    record: dict[str, object] = json.loads(shown.stdout)
    return record


def _seeds(record: dict[str, object]) -> tuple[object, object]:
    compilation = record["compilation"]
    execution = record["execution"]
    assert isinstance(compilation, dict) and isinstance(execution, dict)
    return compilation["config"]["seed_transpiler"], execution["config"]["seed_simulator"]


def test_seed_shorthand_is_backward_compatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _seeds(_run_record(tmp_path, monkeypatch, "--seed", "7")) == (7, 7)


def test_specific_flags_override_shorthand_and_persist_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _run_record(tmp_path, monkeypatch, "--seed", "7", "--seed-simulator", "8")
    assert _seeds(record) == (7, 8)
    record = _run_record(tmp_path, monkeypatch, "--seed-transpiler", "9")
    assert _seeds(record) == (9, None)


def test_help_documents_the_seed_flags() -> None:
    result = CliRunner().invoke(app, ["run", "--help"], env={"COLUMNS": "200"})
    for flag in ("--seed ", "--seed-transpiler", "--seed-simulator"):
        assert flag in result.stdout
