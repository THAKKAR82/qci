# ADR 0001: Modular monolith

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

QCI's long-term scope is broad: CI, a system of record, regression detection, attribution,
observability, backend intelligence, routing and validation. V1 is a local CLI used by a small
team. Requirements will change as research results arrive. Distributed infrastructure would add
operational cost and slow iteration without solving any current problem.

## Decision

Build QCI as a single Python package, a modular monolith, with enforced internal boundaries:

- `domain`: pure data models.
- `core`: ports, hashing and IDs.
- `services`: use cases.
- `adapters`: provider implementations.
- `storage`: persistence implementations.
- `provenance`: git and environment collectors.
- `cli`: the command-line interface.

Dependencies point inward toward `domain` and `core`. Boundaries are enforced by tests,
starting with "no provider SDK imports in domain or core", rather than by process separation.

Persistence starts with local SQLite behind a repository interface. There are no servers,
queues, caches or containers.

## Consequences

- **Good:** fast iteration, a single test run, easy local reproduction and no deployment
  overhead.
- **Good:** clean ports mean modules such as storage or a provider adapter can later be moved
  behind a network boundary if a hosted product requires it.
- **Cost:** boundary discipline relies on tests and review, not on the runtime.
- **Revisit when:** a hosted multi-tenant service, concurrent writers, or workloads beyond a
  single machine become real requirements.
