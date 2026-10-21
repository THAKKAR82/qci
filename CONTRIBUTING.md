# Contributing to QCI

## Developer Certificate of Origin

Contributions to QCI are accepted under the Apache License 2.0 (`LICENSE`), using the
Developer Certificate of Origin (DCO) 1.1, below. By adding a `Signed-off-by:` line to a
commit, you certify the DCO for that commit. Every commit must carry one, including commits
made with an AI coding assistant:

```bash
git commit -s
```

`-s` appends `Signed-off-by: Your Name <your@email>` from your git configuration. Use your
real name and an email address you can be reached at.

```
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.

Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```

## IBM data in the test fixtures

**The IBM data under `tests/fixtures/` is not licensed by this project.** It is provided by
IBM under IBM's own terms; see `tests/fixtures/snapshots/README.md`. It is excluded from the
built packages. Never commit backfilled calibration data or a store (D29 in `PLAN.md`).

## Development setup

```bash
python3.13 -m venv .venv
.venv/bin/pip install -e '.[ibm,dev]'
```

The editable install is the developer path. Users install the package from PyPI or a built
wheel, without `-e` (see `README.md`). The `dev` extra adds `pytest`, `ruff`, `mypy`, `build`
and `hatchling`.

## How work is planned and delivered

- `PLAN.md` names the current milestone and step, with acceptance criteria. Only the current
  step is built.
- `CLAUDE.md` is the working agreement: the non-negotiable rules (a provider-neutral domain,
  immutable runs, raw data kept, failures as data, epistemic labels, no network or
  credentials in tests, neutral comparison wording) and the step workflow (branch, design
  first, tests with the code, all gates, a report, review before the next step). It applies
  to human and AI contributors alike. `AGENTS.md` adds Windows notes.
- Design decisions are recorded as ADRs in `docs/adr/`. `docs/architecture.md` describes the
  layers, ports, flows and exit codes, and `docs/data-model.md` the records.
- `CHANGELOG.md` keeps an `Unreleased` section current with each step.

## Gates

Every change passes these, with no test skipped or weakened:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy --strict src tests scripts
MYPYPATH=src:experiments/repeated_sampling:experiments/calibration_history .venv/bin/mypy --strict experiments
.venv/bin/pytest -q
```

Tests are offline: they use IBM fake backends and seeded local simulation, a session guard
blocks the IBM client, saved accounts and network connections, and every test runs with a
fresh empty `HOME`. `tests/test_distribution_contents.py` builds the sdist and the wheel and
checks that they hold exactly the allow-listed files and no IBM data.
`tests/test_readme.py` runs the README quickstart's offline commands.

## Running the CLI from a checkout

`.venv/bin/qci` runs the editable install. On some macOS setups, something sets the `hidden`
file flag on files inside `.venv`, and Python 3.13 skips hidden `.pth` files, so the editable
install disappears and `qci` fails with `ModuleNotFoundError: No module named 'qci'`. Run
`PYTHONPATH=src .venv/bin/qci ...`, or clear the flag with
`chflags nohidden .venv/lib/python3.13/site-packages/_editable_impl_bloq_qci.pth` (it can come
back). Tests are unaffected: pytest puts `src` on the path. A non-editable install has no
`.pth` file for QCI and is not affected.

Set `QCI_HOME` to a scratch directory while developing, so your experiments stay out of your
per-user store. `qci where` shows which store a command will use.

## The website

The landing page in `site/` is outside the Python package and its gates; see
`site/README.md`.
