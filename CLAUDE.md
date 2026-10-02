# CLAUDE.md — working agreement for QCI

QCI is a vendor-neutral reliability and execution-intelligence layer for quantum computing.
V1 is "Quantum CI": instrument quantum runs, persist immutable records, and (next) compare them.
Read `PLAN.md` for the current milestone and `docs/architecture.md` before changing structure.

## Commands

```bash
python3.13 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy --strict src
.venv/bin/pytest -q
.venv/bin/qci run examples/bell.py --backend fake_sherbrooke --seed 7
.venv/bin/qci runs
.venv/bin/qci show <RUN_ID> [--json]
```

The run store defaults to `./.qci/qci.db`; override with `QCI_HOME`.

## Non-negotiable rules

1. **Provider-neutral domain.** `qci.domain` and `qci.core` must never import `qiskit`,
   `qiskit_ibm_runtime`, `qiskit_aer`, or any other provider SDK. `tests/test_architecture.py`
   enforces this. Provider code lives only under `qci/adapters/<provider>/`.
2. **Immutable runs.** Runs are inserted once and never updated or deleted. No update/delete
   methods on repositories. A schema change is a new `schema_version` plus an explicit upcast.
3. **Keep raw data.** Never drop provider-specific information just because the normalized
   model does not use it. Store it raw alongside normalized fields.
4. **Failures are data.** A run that fails after the workload loads is persisted with
   `status=failed`, the failing stage, and the error.
5. **Epistemic labels.** Every metric carries an `EvidenceKind` (measured, calculated,
   heuristic, statistical, model_prediction, causal_claim) plus `method` and `method_version`.
   Never present a heuristic as a causal claim.
6. **No network or credentials in tests.** Use IBM fake backends and seeded local simulation.
7. **Milestone discipline.** Only build what the current milestone in `PLAN.md` lists.
   No ML, routing, attribution, web UI, auth, billing, or cloud infrastructure yet.

## Conventions

- Python >= 3.12, fully typed, `mypy --strict` clean, Ruff for lint and format.
- Pydantic v2 domain models: `frozen=True`, `extra="forbid"`.
- Ports are `typing.Protocol`s in `qci/core/ports.py`; native SDK objects cross the service
  layer only as opaque `object` handles owned by the adapter.
- Circuit/workload identity is **provisional** (see `docs/data-model.md`). Do not introduce a
  "canonical circuit ID" without an ADR.
- Record non-obvious architectural decisions as ADRs in `docs/adr/`.
- Execute on fake backends with `qiskit.primitives.BackendSamplerV2`, not the deprecated
  `qiskit_ibm_runtime.SamplerV2`. Never suppress a warning without understanding it.
- Provider payloads go through `adapters/qiskit_ibm/jsonable.py:to_jsonable`. It uses
  lossless tags for datetimes, complex numbers and non-finite floats, and it raises on unknown
  types.

## Troubleshooting

- **`ModuleNotFoundError: No module named 'qci'` from `.venv/bin/qci`.** On this macOS setup,
  something sets the `hidden` file flag on files inside `.venv`. Python 3.13 skips hidden
  `.pth` files, so the editable install disappears. Tests are unaffected because pytest sets
  `pythonpath = ["src"]`. For the CLI, run `PYTHONPATH=src .venv/bin/qci ...`, or clear the
  flag with `chflags nohidden .venv/lib/python3.13/site-packages/_editable_impl_qci.pth`. The
  flag can come back.
