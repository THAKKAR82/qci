"""Boundary rules from docs/architecture.md and ADR 0002."""

import ast
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "qci"
PROVIDER_SDKS = ("qiskit", "qiskit_ibm_runtime", "qiskit_aer")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _violations(paths: list[Path]) -> list[str]:
    bad = []
    for path in paths:
        for module in _imported_modules(path):
            if module.split(".")[0] in PROVIDER_SDKS:
                bad.append(f"{path.relative_to(SRC)} imports {module}")
    return bad


def test_domain_and_core_never_import_provider_sdks() -> None:
    paths = sorted((SRC / "domain").rglob("*.py")) + sorted((SRC / "core").rglob("*.py"))
    assert paths, "expected domain/core sources"
    assert _violations(paths) == []


def test_only_adapters_import_provider_sdks() -> None:
    paths = [p for p in SRC.rglob("*.py") if "adapters" not in p.relative_to(SRC).parts]
    assert _violations(paths) == []


def test_importing_neutral_layers_does_not_load_qiskit() -> None:
    code = (
        "import sys; import qci.domain.run, qci.domain.comparison, qci.core.ports, "
        "qci.services.run_service, qci.services.compare_service, qci.compare.footprint, "
        "qci.compare.hardware, qci.compare.distribution, qci.compare.sampling, "
        "qci.compare.sections, "
        "qci.adapters.qiskit_ibm.calibration, qci.cli.app, qci.cli.render_compare; "
        "print(sorted(m for m in sys.modules if m.split('.')[0] in "
        f"{PROVIDER_SDKS!r}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": str(SRC.parent)},
    )
    assert out.stdout.strip() == "[]"
