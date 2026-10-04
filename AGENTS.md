# AGENTS.md

Binding project rules live in **`CLAUDE.md`** (9 non-negotiables) and **`PLAN.md`** (current
milestone: M1, awaiting review). Read both before changing structure. This file records only
environment and workflow facts that are easy to get wrong.

## Commands

```bash
python -m venv .venv && .venv/Scripts/python.exe -m pip install -e '.[dev]'
```

Run gates in this order; all four must pass before claiming done:

```bash
.venv/Scripts/ruff.exe check .
.venv/Scripts/ruff.exe format --check .
.venv/Scripts/python.exe -m mypy --strict src tests
.venv/Scripts/python.exe -m pytest -q
```

- `mypy --strict src tests` passes (54 files). `CLAUDE.md` only documents `src`; `PLAN.md` M1
  criterion 10 requires both, so use both.
- Full suite takes **~2 min** (real transpilation on `FakeSherbrooke`), not instant. Target a
  single test while iterating: `pytest "tests/test_domain.py::test_run_is_frozen" -q`.
- **No CI exists** (`.github/` absent, no pre-commit, no Makefile/justfile, no lockfile). You
  are the only gate — nothing will catch a regression for you.
- **No lockfile; deps are floating ranges** (`qiskit>=2.5,<3`, `qiskit-ibm-runtime>=0.50`). A
  fresh install can pull different versions and change results. Verified working set: Python
  3.13.9, qiskit 2.5.2, qiskit-ibm-runtime 0.50.0, mypy 2.4.0, pytest 9.1.1.

### Gotchas that will waste your time

- **`python -m qci.cli.app` silently does nothing.** `cli/app.py` defines `main()` with no
  `__main__` guard, so the module runs and exits 0 with no output. Use the `qci` console
  script (`.venv/Scripts/qci.exe`).
- **On Windows, `pytest` needs `--basetemp`.** A stale `%TEMP%\pytest-of-<user>` with a broken
  ACL makes 32 tests error with `PermissionError: [WinError 5]` at fixture setup — unrelated to
  the code. Pass `--basetemp=<writable dir>`.
- **`tests/test_architecture.py` scrubs the child env, so it must preserve `SYSTEMROOT`.**
  Windows `asyncio` imports `_overlapped` (Winsock) and dies with `WinError 10106` without it.
  That test is the only runtime proof of the provider boundary — don't "simplify" the env dict
  back to just `PYTHONPATH`.

### CLI exit codes are a documented contract

| Code | Meaning |
|---|---|
| 0 | run succeeded |
| 1 | run failed **and was persisted** as `status=failed` with the failing stage |
| 2 | workload could not load; **nothing persisted** (there is no workload to record) |

The run ID prints to stdout *before* the error, which goes to stderr. Store defaults to
`./.qci/qci.db` (gitignored); override with `QCI_HOME`.

## Architecture facts not visible from filenames

Layering is a strict DAG — `domain` ← `core` ← `compare` ← `services` ← `cli`, plus
`adapters/` and `storage/` implementing `core` ports.

- **There is no noise model, and that is deliberate.** QCI never simulates: no Kraus operators,
  no `NoiseModel`, no error-rate math. It records provider-supplied calibration verbatim and
  compares it across runs. Don't add simulation; `docs/research.md` says it "must not encode
  conclusions before the research supports them."
- **Hardware reaches the domain in exactly two forms:** an opaque `native: object` handle that
  only ever goes back to the adapter that made it, and a frozen JSON payload in
  `provider_raw`. Never as SDK types. (`core/ports.py`, enforced by `tests/test_architecture.py`.)
- **`qci compare` never imports Qiskit.** The calibration reader is deliberately Qiskit-free
  dict parsing, reachable because `adapters/qiskit_ibm/__init__.py` uses a PEP 562
  `__getattr__` behind `TYPE_CHECKING`. Copy that pattern for any new adapter.
- **The physical footprint is the conceptual core.** Calibration is only ever compared for
  resources physically identical on both runs; if mappings differ, `relevant_hardware_changed`
  is `null`. Never compare calibration across different qubits.
- **Ordered gate operands are load-bearing.** IBM calibrates `ecr(104,103)` but not
  `ecr(103,104)`. `compare/footprint.py` keeps operand order; `summarize.py` normalizes edges
  to undirected `min/max`. Don't unify them.
- `index.html`, `styles.css`, `script.js`, `demo-fixtures.js`, and `site-config.js` make up the
  static landing page. It has no build step and is independent of the Python package.

## Extending

- **New provider:** create `adapters/<id>/` and implement the four `Protocol`s in
  `core/ports.py` (`WorkloadLoader`, `BackendCatalog`, `Compiler`, `Executor`) plus a
  `CalibrationReader` — without the last one, hardware comparison returns `UNAVAILABLE`.
  **Known gap (ADR 0004):** the footprint is derived from transpiled **OpenQASM 3**, so an
  adapter whose transpiled form isn't QASM 3 yields `FootprintStatus.UNAVAILABLE`.
- **New comparison rule:** add a field to `ComparisonPolicy` and you *must* bump `version` —
  it's typed `Literal["qci.compare.v1"]`, so the type system enforces it.
- **New metric:** append to `compute_metrics` in `services/run_service.py`; every one needs an
  `EvidenceKind` + `method` + `method_version`. `EvidenceKind.CAUSAL_CLAIM` exists but nothing
  emits it — the slot is reserved, not licensed.
- **Schema change:** bump `schema_version` and write an explicit upcast. Never rewrite old
  records (ADR 0003).

## Canary for dependency bumps

`tests/test_footprint_parity.py` transpiles real circuits (opt levels 0/1/3 plus a scheduled
`delay`) and asserts the QASM3-derived footprint equals the native circuit's gate multiset. It
is the canary for `openqasm3`/`qiskit` upgrades — per ADR 0004, an AST change must be absorbed
in `qci/compare/footprint.py` and pass this test.

## Deliberately closed doors

`CLAUDE.md` rules 7 and 8 forbid, and you should not build: regression verdicts or
pass/fail gating, causal attribution, ML/predictors/routing, web UI, auth, cloud, dataset
export, a "canonical circuit ID", and any mutation or deletion of a stored run. "Do not
suppress a warning without understanding it" is also binding — the deprecated
`qiskit_ibm_runtime.SamplerV2` is avoided deliberately (it silently drops `seed_simulator=0`).
