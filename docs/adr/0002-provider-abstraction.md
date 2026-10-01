# ADR 0002: Provider abstraction with opaque native handles

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

V1 targets IBM through Qiskit, but QCI must stay vendor-neutral. Future adapters might cover
other hardware vendors, cloud aggregators, simulators or technologies not yet anticipated.
Qiskit objects such as `QuantumCircuit`, `BackendV2` and primitive results must not spread
through the domain.

There is also no stable, universal circuit intermediate representation (IR) that QCI could
adopt today without loss. OpenQASM 3 is the closest candidate, but export can be lossy or
version-dependent.

## Decision

1. Define provider capabilities as `typing.Protocol` ports in `qci/core/ports.py`:
   `WorkloadLoader`, `Compiler`, `BackendCatalog`, `Executor`, and a `ProviderAdapter` bundle.
2. Each provider lives in `qci/adapters/<provider_id>/`. The IBM/Qiskit adapter is
   `qiskit_ibm`. Only adapter code imports provider SDKs.
3. Ports return **normalized domain summaries**: `CircuitSummary`, `CompilationRecord`,
   `BackendSnapshot` and `ExecutionResult`. They also return **raw provider payloads** as JSON,
   so no information is lost.
4. Native objects needed between steps, such as the compiled circuit or the backend object,
   pass through the service as **opaque `object` handles**. They are only ever handed back to
   ports of the same adapter.
5. QCI does **not** define its own circuit IR yet.

## Consequences

- **Good:** the domain stays SDK-free, which a test enforces.
- **Good:** adding a provider means implementing four small ports. No domain change is
  required unless the provider exposes a genuinely new concept.
- **Cost:** opaque handles weaken static typing at the seams. Adapters must validate the
  handles they receive.
- **Cost:** the port shapes are inferred from one provider. M0.5 adds a contract suite run
  against an in-memory adapter to check that the ports are not IBM-shaped.
- **Revisit when:** a second real provider is added, or a portable circuit IR becomes necessary
  for cross-provider compilation.
