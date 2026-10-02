# ADR 0004: Derive the physical footprint from stored transpiled OpenQASM 3

- **Status:** Accepted (provisional)
- **Date:** 2026-10-01

## Context

M1 compares two runs. It needs each run's **physical footprint**: the physical qubits and the
native operations, with ordered physical qubit arguments, that the final transpiled circuit
actually references. Hardware calibration comparison must be scoped to exactly those resources.

M0's normalized `CircuitSummary` cannot provide this. Its `two_qubit_edges` are undirected and
exclude measure, reset and delay. Its `op_counts` carry no qubit arguments.

M0 does store the transpiled circuit's OpenQASM 3 text. That text names physical qubits as
`$<n>`, in instruction order. During the M1 audit, the operation names and qubit sequences
recovered from it matched the native Qiskit circuit exactly. The test cases were Bell and routed
GHZ-5 circuits at optimization levels 0, 1 and 3, with barriers, resets, measurements and a
scheduled delay.

## Decision

1. **Derive at compare time.** The footprint is derived when two runs are compared, from the
   stored transpiled QASM3. It is not captured at run time. This keeps the Run schema at
   version 1 and makes existing immutable M0 records comparable without migration.
2. **Parse with the reference parser.** The text is parsed with `openqasm3[parser]`, the
   vendor-neutral OpenQASM reference parser, pinned to `>=1.0.1,<2`. It is not a provider SDK,
   so provider-neutral code may use it.
3. **Isolate the parser.** All AST handling lives in `qci/compare/footprint.py`. The parser
   API is an **external compatibility boundary**: an upgrade that changes the AST must be
   absorbed in that one module and pass the parity tests.
4. **Fail closed.** Only top-level statements are read.
   - Control flow is reported as `unsupported_dynamic` and never flattened.
   - Unknown statements, non-physical operands, gate modifiers, durations, annotations and
     pragmas are reported as `unavailable`.
   - Gate definitions are never inlined, so a natively executed `ecr` stays `ecr`.
5. **Prove parity.** `tests/test_footprint_parity.py` compares the extracted footprint with the
   native transpiled circuit across a matrix of circuits.

## Consequences

- **Good:** existing runs are compared exactly where QASM3 export succeeded. No schema change
  and no mutation are needed.
- **Good:** one code path serves old and new runs alike.
- **Cost:** the footprint depends on Qiskit's QASM3 exporter. If export failed, or a future
  exporter emits constructs the walker rejects, the footprint is reported unavailable. It is
  never guessed.
- **Cost:** parsing is Python-ANTLR based and may be slow for very large circuits. This is not a
  concern at current scale.
- **Revisit when:** QPY or content-addressed artifact storage arrives in M0.5. At that point,
  capture the footprint from the native circuit at run time, or re-derive it from archived QPY.
  Also revisit for dynamic-circuit support or a second provider whose transpiled form is not
  OpenQASM 3.
