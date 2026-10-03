"""Physical footprint extraction from a stored transpiled OpenQASM 3 circuit.

All ``openqasm3`` AST handling is isolated in this module: the parser API is an external
compatibility boundary (see docs/adr/0004-footprint-from-transpiled-qasm3.md). Extraction is
provisional and should be revisited once QPY / content-addressed artifacts exist.

Semantics (method ``openqasm3.toplevel`` v1), applied to top-level statements only:

- Gate statements yield ``(name, ordered physical qubits)``. Gate definitions are never inlined,
  so a natively executed ``ecr`` stays ``ecr``.
- Measurements, resets and delays are operations and make their qubits relevant.
- Barriers are not hardware operations and are skipped.
- Control flow (if/while/for/switch/box) yields ``unsupported_dynamic``; never flattened.
- Anything unrecognized, any non-physical qubit operand, gate modifiers, durations or
  annotations yield ``unavailable`` (fail closed).
"""

import re
from collections import Counter

import openqasm3
from openqasm3 import ast

from qci.domain.circuit import Layout
from qci.domain.comparison import FootprintStatus, PhysicalFootprint, PhysicalOperation
from qci.domain.run import Run

METHOD = "openqasm3.toplevel"
METHOD_VERSION = "1"

_PHYSICAL = re.compile(r"\$(\d+)")
_CONTROL_FLOW: tuple[type[ast.Statement], ...] = (
    ast.BranchingStatement,
    ast.WhileLoop,
    ast.ForInLoop,
    ast.SwitchStatement,
    ast.Box,
)
_IGNORED: tuple[type[ast.Statement], ...] = (
    ast.Include,
    ast.ClassicalDeclaration,
    ast.QubitDeclaration,
    ast.QuantumGateDefinition,
)


class _UnavailableError(Exception):
    pass


class _DynamicError(Exception):
    pass


def _physical_qubit(operand: object) -> int:
    if isinstance(operand, ast.Identifier):
        match = _PHYSICAL.fullmatch(operand.name)
        if match:
            return int(match.group(1))
        raise _UnavailableError(f"non-physical qubit operand {operand.name!r}")
    raise _UnavailableError(f"non-physical qubit operand of type {type(operand).__name__}")


def _operands(value: object) -> tuple[int, ...]:
    items = value if isinstance(value, list) else [value]
    return tuple(_physical_qubit(item) for item in items)


def _walk(program: ast.Program) -> tuple[Counter[tuple[str, tuple[int, ...]]], set[int]]:
    operations: Counter[tuple[str, tuple[int, ...]]] = Counter()
    measured: set[int] = set()
    for statement in program.statements:
        kind = type(statement).__name__
        if isinstance(statement, _CONTROL_FLOW):
            raise _DynamicError(f"control flow ({kind}) is not supported by this comparison policy")
        if isinstance(statement, _IGNORED):
            continue
        if isinstance(statement, ast.Pragma):
            raise _UnavailableError("pragma statements are not supported")
        if statement.annotations:
            raise _UnavailableError(f"annotated statement ({kind}) is not supported")
        if isinstance(statement, ast.QuantumGate):
            if statement.modifiers or statement.duration is not None:
                raise _UnavailableError(f"gate {statement.name.name!r} has modifiers or a duration")
            operations[(statement.name.name, _operands(statement.qubits))] += 1
        elif isinstance(statement, ast.QuantumMeasurementStatement):
            qubits = _operands(statement.measure.qubit)
            operations[("measure", qubits)] += 1
            measured.update(qubits)
        elif isinstance(statement, ast.QuantumReset):
            operations[("reset", _operands(statement.qubits))] += 1
        elif isinstance(statement, ast.DelayInstruction):
            operations[("delay", _operands(statement.qubits))] += 1
        elif isinstance(statement, ast.QuantumBarrier):
            continue
        elif isinstance(statement, ast.QuantumPhase) and not statement.qubits:
            continue  # global phase: not a hardware operation
        else:
            raise _UnavailableError(f"unrecognized statement ({kind})")
    return operations, measured


def extract_footprint(
    qasm3: str | None, layout: Layout | None, *, missing_reason: str = "no transpiled OpenQASM 3"
) -> PhysicalFootprint:
    initial = layout.initial if layout else None
    final = layout.final if layout else None

    def result(status: FootprintStatus, reason: str | None = None) -> PhysicalFootprint:
        return PhysicalFootprint(
            status=status,
            reason=reason,
            initial_layout=initial,
            final_layout=final,
            method=METHOD,
            method_version=METHOD_VERSION,
        )

    if qasm3 is None:
        return result(FootprintStatus.UNAVAILABLE, missing_reason)
    try:
        program = openqasm3.parse(qasm3)
    except Exception as exc:
        return result(FootprintStatus.UNAVAILABLE, f"OpenQASM 3 parse failed: {exc}")
    try:
        operations, measured = _walk(program)
    except _DynamicError as exc:
        return result(FootprintStatus.UNSUPPORTED_DYNAMIC, str(exc))
    except _UnavailableError as exc:
        return result(FootprintStatus.UNAVAILABLE, str(exc))

    qubits = sorted({q for (_, qargs) in operations for q in qargs})
    return PhysicalFootprint(
        status=FootprintStatus.AVAILABLE,
        qubits=qubits,
        measured_qubits=sorted(measured),
        operations=[
            PhysicalOperation(name=name, qubits=qargs, count=count)
            for (name, qargs), count in sorted(operations.items())
        ],
        initial_layout=initial,
        final_layout=final,
        method=METHOD,
        method_version=METHOD_VERSION,
    )


def footprint_for_run(run: Run) -> PhysicalFootprint:
    """Footprint of the run's final transpiled circuit, or an explicit unavailable status."""
    compilation = run.compilation
    if compilation is None:
        return extract_footprint(None, None, missing_reason="run has no compilation record")
    output = compilation.output
    reason = (
        f"OpenQASM 3 export failed: {output.qasm3_error}"
        if output.qasm3_error
        else "no transpiled OpenQASM 3"
    )
    return extract_footprint(output.qasm3, compilation.layout, missing_reason=reason)
