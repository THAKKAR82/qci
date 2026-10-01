# ADR 0003: Immutable, versioned run records

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

QCI is a reliability product, and its historical dataset may become its most valuable asset.
Regression analysis and research both depend on knowing exactly what happened, including
failures. Variables that matter later may not be recognized today. Mutable records would make
history untrustworthy and destroy provenance.

## Decision

1. A **Run** is assembled fully in memory, validated as a frozen Pydantic model, and inserted
   in a single transaction.
2. The `RunRepository` port has **no update or delete** operations. Inserting a duplicate
   `run_id` is an error.
3. **Failures are data.** A run that fails after the workload loads is persisted with
   `status=failed`, the failing stage, the error, and everything captured before the failure.
4. **Raw provider data is kept verbatim** next to normalized fields. In M0 it is stored inline
   in the record. M0.5 moves it to a content-addressed blob store.
5. Every record carries a **`schema_version`**. Old records are never rewritten. Readers
   upcast them through explicit, tested functions.
6. `run_id` is a random, time-sortable identifier, not a content hash, because a run is an
   event.
7. Storage is a JSON document of the whole Run plus a few indexed columns for listing.

## Consequences

- **Good:** an auditable and reproducible history that is safe for research datasets.
- **Good:** the document model lets the Run schema evolve without frequent table migrations.
- **Cost:** storage grows monotonically. Inline raw payloads are estimated at 100 to 300 KB per
  run until M0.5.
- **Cost:** mistakes cannot be fixed in place. Corrections require new records, and later
  perhaps an annotation mechanism, which is not designed yet.
- **Open:** deletion for privacy or legal reasons in a future hosted product will need a
  separate, explicit policy.
