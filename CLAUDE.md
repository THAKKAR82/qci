# CLAUDE.md — working agreement for QCI

QCI is a vendor-neutral reliability and execution-intelligence layer for quantum computing.
V1 is "Quantum CI": instrument quantum runs, persist immutable records, and compare them.
Read `PLAN.md` for the current milestone and `docs/architecture.md` before changing structure.

AGENTS.md adds Windows and environment notes for other agents; this file is authoritative. The
website in site/ is outside the product and its gates.

## Commands

```bash
python3.13 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy --strict src tests scripts
MYPYPATH=src:experiments/repeated_sampling .venv/bin/mypy --strict experiments
.venv/bin/pytest -q
.venv/bin/qci run examples/bell.py --backend fake_sherbrooke --seed 7
.venv/bin/qci runs
.venv/bin/qci show <RUN_ID> [--json]
.venv/bin/qci compare <BASELINE_RUN_ID> <CANDIDATE_RUN_ID> [--json] [--observable NAME=BITS,...]
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
8. **Compare reports differences only.** Comparisons are directional, baseline to candidate,
   and deltas are candidate minus baseline. Never use better, worse, regression, improvement,
   PASS or FAIL. Never compare calibration of different physical resources as a change of one
   resource. Missing calibration is null, never zero. Comparisons are never persisted.
   A `changed` result distribution means the observed empirical distributions differ, never
   that the underlying distribution changed or that the difference is significant. "Relevant
   hardware" means calibration of physical resources the workload used, never that a parameter
   is known to affect performance or caused a result change.
9. **Semantic comparison, not JSON diffing.** Each section is compared explicitly over
   normalized fields. Raw provider payloads are evidence inputs, never recursively diffed.

## Step workflow

Work is delivered in small, reviewed steps. For every step:

1. Read CLAUDE.md and PLAN.md first. Implement only the step named in the prompt.
2. Start from a clean tree on up-to-date `main`. Create the branch named in the prompt.
3. Before writing code, print a short design: files to touch, models and functions to add, and
   tests to add. If anything in PLAN.md is ambiguous, contradictory, or wrong given the actual
   code, stop and ask instead of guessing.
4. Write tests alongside code. Tests stay offline: no network and no credentials.
5. Run all gates and paste their real output:
   ```bash
   .venv/bin/ruff check .
   .venv/bin/ruff format --check .
   .venv/bin/mypy --strict src tests scripts
   MYPYPATH=src:experiments/repeated_sampling .venv/bin/mypy --strict experiments
   .venv/bin/pytest -q
   ```
   When a new experiment directory is added, append it to `MYPYPATH`. Scripts in `scripts/` are
   type-checked by the first mypy gate and never run by pytest.
   Also run the neutral-wording check over the lines the branch adds in `src/`, `docs/` and
   `README.md` (rule 8 words plus `significan`, `verdict`, `caus`, `degrad`), paste its output,
   and justify every hit in the report:
   ```bash
   git diff main...HEAD -U0 -- src docs README.md | grep -E '^\+' | grep -v '^+++' | grep -n -i -E 'better|worse|regress|improv|degrad|\bpass|fail|significan|verdict|caus' || echo "neutral-wording check: no hits"
   ```
   Paste this command's raw output verbatim in the report, never a summary of it, then justify
   each hit.
6. Experiment scripts must be committed before they generate runs, so experiment runs record
   git provenance with `dirty=false`.
7. Do not weaken, skip, xfail or delete an existing test to make a gate pass. If an existing
   test must change because a spec changed, say which test and why.
8. Commit on the branch with a conventional commit message. Never push, merge or rebase `main`.
9. Stop and print a report with exactly these headings: Summary / Files changed / Design
   decisions / Deviations from PLAN.md / Gate results / Manual verification commands / Open
   questions.
10. If a step's changes make any doc stale, update it within the step when the step's file
    restrictions allow. Otherwise, list it under Open questions. Prompt file restrictions take
    priority.
11. When a step's acceptance criteria are all met, update the PLAN.md header to name the step
    as done and the next sub-step as current, in the same branch.

Never start the next step without explicit approval.

## Conventions

- Python >= 3.12, fully typed, `mypy --strict` clean, Ruff for lint and format.
- Pydantic v2 domain models: `frozen=True`, `extra="forbid"`.
- Ports are `typing.Protocol`s in `qci/core/ports.py`; native SDK objects cross the service
  layer only as opaque `object` handles owned by the adapter.
- `openqasm3` is the vendor-neutral OpenQASM parser, not a provider SDK. It may be used outside
  adapters, but its AST handling must stay inside `qci/compare/footprint.py` (ADR 0004).
- Changing comparison rules means bumping `ComparisonPolicy.version` (`qci.compare.v3`).
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
