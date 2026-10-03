# ADR 0006: Execution levels

- **Status:** Accepted
- **Date:** 2026-10-03

This ADR sets constraints only. It requires no implementation.

## Context

Fault-tolerant machines add a logical layer above physical qubits. Logical qubits are encoded
in many physical qubits by an error-correcting code, and a decoder interprets syndrome
measurements in real time.

Physical drift still matters at the logical level, and it is amplified there. For the surface
code, the logical error rate scales approximately as

```
p_L ≈ A · (p / p_th)^((d + 1) / 2)
```

where p is the physical error rate, p_th the threshold, d the code distance and A a constant.
A small change in p therefore changes p_L by a large factor.

Users of such machines observe logical metrics, not physical calibration. Examples are logical
error per round, decoder health and rejection rates. Operators, who must connect logical
behavior back to physical drift, become the main audience.

QCI today models only the physical level. Several current types encode physical-level
assumptions:
- `PhysicalOperation.qubits` identifies resources by integer qubit index.
- `ResourceKind` distinguishes only qubits and operations.
- Statistics are designed around bitstring counts.
- The calibration reader parses IBM's payload format.

## Decision

1. **A stack of levels.** Execution is modeled as a stack of levels. Exactly one level exists
   today: the physical level.
2. **Constraints on new code.** New code must not assume that:
   - (a) a resource is identified by an integer qubit index;
   - (b) statistics operate only on bitstrings;
   - (c) calibration data is IBM-shaped.
3. **Encoding as provenance.** When an encoding layer exists, its configuration (code,
   distance, decoder and decoder version) will become a provenance layer analogous to
   compilation.

## Consequences

- **No code change now.**
- **Existing types stay as they are.** `PhysicalOperation.qubits` and `ResourceKind` are
  physical-level types. Generalizing them happens through a future schema bump, not an
  in-place change.
- **Near-term steps apply the constraints.**
  - M1.2 keeps the Wilson and Newcombe statistics on integer (k, n) arguments, separate from
    bitstring handling, so a logical-error-rate observable can reuse them.
  - M1.3a designs snapshot storage as generic time-stamped measurements with an
    adapter-defined resource identifier, so non-qubit resources fit without a schema change.
