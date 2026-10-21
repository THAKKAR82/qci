# ADR 0009: Packaging and first-run usability

- **Status:** Accepted (2026-10-20), with the user's answers to six review questions: the
  copyright holder is "The QCI Authors" (section 1); license agreements are recorded as pull
  request comments and future contributions use the Developer Certificate of Origin
  (section 1); the repository is private until D29 is resolved (sections 8 and 9); the README
  is self-contained for PyPI (section 7); the `qiskit-ibm-runtime` cap stands for 0.1.0
  (section 2); and stale docs are updated in R1b. Acceptance criteria are in section 10.
- **Date:** 2026-10-20 (proposed), 2026-10-20 (accepted), 2026-10-20 (`LICENSE` and `NOTICE`
  merged in PR #5 with both license agreements, recorded in Findings; R1c split into a local
  test and the TestPyPI upload, section 8), 2026-10-20 (R1b: the IBM-data statement moved out
  of the README and the README written for users, by user decision, sections 1, 7 and 10;
  clarifications from implementation in sections 1, 4, 5 and 10, recorded in Findings)
- **Milestone:** R1, release 1 (`PLAN.md`). This ADR is R1a. R1b implements it, R1c is the
  clean-machine install test and the TestPyPI release, and R1d is the PyPI release.
- **Resolves:** D5 in `PLAN.md` (project-local or user-global store), once R1b ships it.

## Context

QCI is installable today only from a checkout, with `pip install -e '.[dev]'`. Four things
stand between that and a first release that a new user can install and use in a few minutes:

- **Distribution.** The distribution is named `qci`, at version `0.0.1`, with no license, and
  the source distribution (sdist) would be built with hatchling's defaults, which include every
  file git does not ignore. That would ship `tests/fixtures/snapshots/ibm_fez.json`, a real
  IBM calibration document, plus `experiments/`, `docs/` and `site/`. D29 keeps IBM data out of
  anything QCI redistributes.
- **Install weight.** Every install pulls Qiskit, `qiskit-ibm-runtime` and `qiskit-aer`, even
  for a user who only reads and compares stored records.
- **Store location.** The default store is `./.qci/qci.db` in the current directory, so the
  same user sees different histories from different directories (D5).
- **First-run friction.** Every command that reads a record needs a 26-character ID pasted
  from an earlier command, and the comparison text is long, with counts first and magnitudes
  absent (backlog item "summarize footprint differences by magnitude", from M1.4c).

There is also a local problem: on this macOS setup, something sets the `hidden` file flag on
files inside `.venv`, and Python 3.13 skips hidden `.pth` files, so the editable install
disappears (`CLAUDE.md`, Troubleshooting). A non-editable install has no `.pth` file for
QCI.

R1 changes packaging, store location and presentation only. Comparison rules, record schemas
and JSON output stay as they are.

## Findings from the code

Checked on 2026-10-20 against `main` at `842bc4f`, with the installed Python 3.13.9,
`qiskit` 2.5.2, `qiskit-ibm-runtime` 0.50.0 and `qiskit-aer` 0.17.2. No network call was
made, and no package was built (`hatchling` and `build` are not installed in `.venv`).

- **Provider SDK imports.** Only `adapters/qiskit_ibm/adapter.py` and `summarize.py` import
  Qiskit at module level. `adapters/qiskit_ibm/live.py` imports `qiskit_ibm_runtime` inside
  functions. With an import hook that raises `ImportError` for `qiskit`, `qiskit_ibm_runtime`
  and `qiskit_aer`, these all import, and both support constructors run:
  `qci.cli.app`, `qci.adapters.qiskit_ibm.calibration` (`snapshot_comparison_support()` and
  `run_snapshot_comparison_support()`), `qci.adapters.qiskit_ibm.historical`,
  `qci.adapters.qiskit_ibm.redact`, and the compare, snapshot-compare and run-snapshot-compare
  services. The architecture therefore allows a core install without the provider SDKs.
- **Version lookup.** `provenance/environment.py` records `metadata.version("qci")` under the
  package key `qci`. Renaming the distribution makes that lookup return `None`. Run records
  also store `qci.__version__` (`run_service.py`), which is a second, hand-kept copy of the
  version in `pyproject.toml`.
- **Store path.** `cli/app.py:store_dir()` returns `$QCI_HOME` if set and non-empty, else
  `Path.cwd() / ".qci"`. Every CLI test sets `QCI_HOME`.
- **Listing order.** `qci runs` orders by `run_id` descending. Run IDs are ULIDs: 48 bits of
  millisecond time, then 80 random bits, strictly increasing within one process. Two
  processes can create runs in the same millisecond, and their relative order is then random.
  `qci snapshots` orders by `first_captured_at` descending, then `snapshot_id`; a backfill
  stores its oldest grid time last, so the first listed snapshot can be the oldest document.
- **Saved accounts.** In `qiskit-ibm-runtime` 0.50.0, `AccountManager.list(name=...)`
  (`accounts/management.py:94`) reads only the account file, filters out legacy `ibm_quantum`
  accounts, and reads no environment variable. `QiskitRuntimeService.saved_accounts()` returns
  the saved format, which includes the token, so QCI must not use it. `AccountManager.get`
  falls back to environment variables (line 164), so it is unsuitable for a presence check.
- **Payload markers.** `src/` and `README.md` contain no `"last_update_date": "<date>"` text,
  no `{"$datetime": "<date>"}` tag with a date, and no `SQLite format 3` header.
- **Contributors.** Git history has three authors. `site/` has commits by Mit Thakkar and
  `toorha`. `dhruvhptl` authored one commit (`cdf8f90`) touching `site/` files, `README.md`,
  `AGENTS.md` and `tests/test_architecture.py`.

## Decision

### 1. Distribution, license and build contents

**Names.** The PyPI distribution is `bloq-qci`. The import package stays `qci`, and the
console command stays `qci`. Nothing under `src/qci/` is renamed.

**Version.** `0.1.0`, single-sourced: `src/qci/__init__.py` keeps `__version__`, and
`pyproject.toml` declares `dynamic = ["version"]` with
`[tool.hatch.version] path = "src/qci/__init__.py"`. `provenance/environment.py` looks up the
distribution `bloq-qci` and still records it under the package key `qci`, so the record shape
is unchanged. Older runs record `0.0.1` under the same key, and `qci compare` reports the
version difference as an environment change, as for any version change.

**License.** Apache-2.0, declared with PEP 639 metadata: `license = "Apache-2.0"` and
`license-files = ["LICENSE", "NOTICE"]`, which needs `hatchling>=1.27`. `LICENSE` and
`NOTICE` are on `main` since PR #5 (2026-10-20). `LICENSE` is the unmodified Apache License
2.0 text, and `NOTICE` is exactly:

```
QCI
Copyright 2026 The QCI Authors
```

The NOTICE needs no `site/` exclusion: both agreements are recorded (below). The statement
that the IBM data under `tests/fixtures/` is not licensed by this project, and is provided by
IBM under IBM's own terms, is not in the NOTICE. R1b puts it next to the data, in
`tests/fixtures/snapshots/README.md`, and in `CONTRIBUTING.md`, not in the user-facing
`README.md` (user decision, 2026-10-20).

`AUTHORS` (R1b) is a short file saying that the QCI Authors are the commit authors in the
git history, which `git shortlog -sne` lists. It names no one itself, so it never goes out of
date.

Licensing needs the agreement of every contributor whose work the license covers: the
`site/` authors (Mit Thakkar and `toorha`) for `site/`, and `dhruvhptl` for the parts of
`README.md`, `AGENTS.md` and `tests/test_architecture.py` they wrote. **Recorded
2026-10-20:** `toorha` and `dhruvhptl` each commented on PR #5, which adds `LICENSE`, with
the sentence "I agree to license my contributions to this repository under the Apache
License 2.0." (Findings). The licensing gate on the TestPyPI upload and on R1d is met.
`site/` is outside every built package regardless.

**Future contributions** use the Developer Certificate of Origin 1.1: every commit carries a
`Signed-off-by: Name <email>` line (`git commit -s`). `CONTRIBUTING.md` states this, with the
DCO text, and `CLAUDE.md`'s step workflow requires it, including for commits made through
Claude Code. Both land in R1b, and R1b's own commits carry the line from its first commit
on. (PR #5's commit already carries one.)

**Python versions.** `requires-python = ">=3.12"`, unchanged, with no upper bound. The tested
versions are 3.12 and 3.13: classifiers name exactly these, R1c installs on both, and
`qci doctor` reports any other version as untested, not as unsupported.

**Wheel contents.** Exactly:

- `qci/**/*.py` and `qci/py.typed` (new, empty, PEP 561: the package is typed);
- `bloq_qci-0.1.0.dist-info/` with `METADATA`, `WHEEL`, `RECORD`, `entry_points.txt`,
  `licenses/LICENSE` and `licenses/NOTICE`.

**Project URLs.** None in 0.1.0: the repository is private until D29 is resolved, so the
metadata has no `[project.urls]` until its visibility is settled.

**sdist contents.** Exactly `pyproject.toml`, `README.md`, `CHANGELOG.md`, `LICENSE`,
`NOTICE`, `AUTHORS`, `PKG-INFO`, `src/qci/**/*.py` and `src/qci/py.typed`, set with hatchling's
`[tool.hatch.build.targets.sdist] only-include`, plus `.gitignore` (clarified 2026-10-20 in
R1b: hatchling always adds the VCS ignore file to an sdist, whatever `only-include` says, and
it holds no data; Findings). An allow-list, not an exclude list: a new top-level file or
directory stays out unless it is added on purpose.

**Excluded from both:** `tests/` (including `tests/fixtures/snapshots/ibm_fez.json` and
`tests/golden/`), `experiments/`, `docs/` (including the M1.5d manifest), `site/`,
`examples/`, `scripts/`, `PLAN.md`, `CLAUDE.md`, `AGENTS.md`, and any store or backup
(`*.db`, `.qci*/`). The sdist cannot run the test suite; the repository is where tests run.

**Archive test.** R1b adds `tests/test_distribution_contents.py`. It builds both archives
offline into a temporary directory with `python -m build --no-isolation` (the sdist, then
the wheel built from that sdist, as a user installing from source would get it), with
`build` and `hatchling` added to the `dev` extra. It reports a finding, and the test exits
with an assertion error, when any of these holds for either archive:

1. a member path, after the sdist's `bloq_qci-0.1.0/` prefix, starts with `tests/`,
   `experiments/`, `docs/`, `site/`, `examples/` or `scripts/`;
2. a member is not on the allow-list above;
3. a member is byte-identical (SHA-256) to any file under `tests/fixtures/`;
4. a member's bytes match `"last_update_date"\s*:\s*"\d{4}-\d{2}-\d{2}`,
   `\{"\$datetime"\s*:\s*"\d{4}-`, or contain `SQLite format 3\x00`;
5. a member contains the committed fixture's own `last_update_date` value.

Checks 1 and 2 keep data files out by path; checks 3 to 5 catch a payload pasted into a
Python file or into `README.md`, which becomes the wheel's `METADATA`. A second test runs the
same scanner on a synthetic archive that holds a copy of `ibm_fez.json` under
`tests/fixtures/`, and on one that holds the fixture's text inside a `.py` file, and asserts
that both are reported, so the scanner is shown to detect what it looks for.

### 2. Install and extras

The architecture allows a core install (Findings), so:

| Extra | Adds | Install |
|---|---|---|
| core | `pydantic`, `typer`, `sqlalchemy`, `numpy`, `openqasm3[parser]` | `pip install bloq-qci` |
| `ibm` | `qiskit>=2.5,<3`, `qiskit-ibm-runtime>=0.50,<0.51`, `qiskit-aer>=0.17` | `pip install 'bloq-qci[ibm]'` |
| `dev` | `pytest`, `ruff`, `mypy`, `build`, `hatchling>=1.27` | `pip install -e '.[ibm,dev]'` |

`qiskit-ibm-runtime` gets an upper bound at the verified minor version: the snapshot,
backfill, account and fake-backend code relies on behavior read from the 0.50.0 source
(ADR 0005, ADR 0008), which a minor release can change. Accepted for 0.1.0. Raising the bound
is a reviewed step that checks each new version against that behavior: historical requests,
account handling, logging and redaction (backlog in `PLAN.md`). `numpy` and `openqasm3`
stay in core: the comparisons need them.

**Without the `ibm` extra**, these work: `qci runs`, `qci show`, `qci compare`,
`qci snapshots`, `qci snapshot show`, `qci snapshot compare`, `qci snapshot compare-run`,
`qci where` and `qci doctor`. These need it: `qci run` (workloads are Qiskit circuits run on
IBM fake backends), `qci snapshot capture`, `qci snapshot backfill`, and
`qci snapshot export` (its scan reads the saved account). Each of these checks for the extra
first, before opening the store or loading a workload, and exits 2 with nothing persisted
and the message `this command needs the ibm extra: pip install 'bloq-qci[ibm]'`. The check
is `importlib.util.find_spec` on `qiskit`, `qiskit_ibm_runtime` and `qiskit_aer`, and it
lives in `adapters/qiskit_ibm/`. The exit code tables in `docs/architecture.md` gain this row.

R1b adds a test that runs each command in a subprocess with an import hook that blocks the
three SDKs, over a store prepared in the test session: the first group behaves as with the
SDKs installed (same stdout and exit code), and each command in the second group exits 2 with
the message and leaves the store bytes unchanged.

**The macOS hidden `.pth` problem.** The documented install for users is non-editable, from
PyPI or from a built wheel, into a virtual environment. A non-editable install puts QCI's
files in `site-packages` and writes no `.pth` file for it, so the hidden flag on `.pth` files
does not affect it. The editable install stays the developer path, with the existing
`CLAUDE.md` troubleshooting note. R1c records whether the clean-machine install shows the
problem.

### 3. Default store location

The store becomes per user. `QCI_HOME` still overrides it, with the same meaning: a
directory holding `qci.db`. An empty `QCI_HOME` counts as unset, as now. The per-user
directory is chosen with the standard library only (no `platformdirs` dependency):

| Platform (`sys.platform`) | Store directory |
|---|---|
| `darwin` | `~/Library/Application Support/qci` |
| `win32` | `%LOCALAPPDATA%\qci`; if `LOCALAPPDATA` is unset, `~\AppData\Local\qci` |
| anything else | `$XDG_DATA_HOME/qci` if `XDG_DATA_HOME` is set and absolute, else `~/.local/share/qci` |

This is data, not cache or configuration: the store holds immutable records that must not be
cleared by cache cleaners. On Windows it is local, not roaming, as stores are large (about
560 KB per run, about 2.1 MB per snapshot). Write commands create the directory, on POSIX
with mode `0o700`. Read-only commands never create it, and a missing store reads as empty,
as now.

**`qci where`.** Prints the absolute path of the `qci.db` file that commands will use, alone
on stdout, so that `shasum -a 256 "$(qci where)"` works. On stderr it says where the path
came from (`QCI_HOME` or the per-user default) and whether the file exists. It opens nothing
and exits 0.

**Existing `./.qci` stores.** When `QCI_HOME` is unset and `./.qci/qci.db` exists in the
current directory, every command that opens a store, plus `qci where` and `qci doctor`,
prints to stderr:

```
note: ./.qci/qci.db exists, but QCI now uses <per-user path> by default.
To keep using that store, set QCI_HOME to its directory:
  export QCI_HOME="<absolute path of ./.qci>"
```

The check looks only at the current directory, never its parents. Existence is checked with
`Path.is_file()`; nothing else touches that file, except `qci doctor`, which inspects it
read-only (section 4). QCI never moves, copies, links or merges a store. Exit codes and
stdout are unchanged by the note, so `--json` output stays parseable. When `QCI_HOME` is set,
no note is printed.

Runs can be compared only within one store, so a user who keeps writing to the per-user
store while older runs sit in `./.qci` cannot compare across them. The note is shown on every
command for that reason, and it gives the exact command to keep the old store.

### 4. `qci doctor`

`qci doctor` reads local state and reports one line per check, each `ok`, `note` or
`problem`. It makes no network call, constructs no IBM client, and writes nothing.

| Check | `ok` | `note` | `problem` |
|---|---|---|---|
| Python | 3.12 or 3.13 | another version 3.12 or later (untested) | below 3.12 (only from a source checkout) |
| Package | `bloq-qci` version, from `importlib.metadata`, equal to `qci.__version__` | | the two differ (a stale or mixed install) |
| Core dependencies | each installed, with its version | | one is missing |
| `ibm` extra | all three of `qiskit`, `qiskit-ibm-runtime`, `qiskit-aer` installed, with versions | none installed: lists the commands that need it | only some installed |
| Saved IBM account | an account named `default-ibm-quantum-platform` (the `--account` default) exists | the extra is missing, or no account by that name, or the account file is absent; lists the names of the saved accounts | the account file cannot be parsed |
| Store | for the store `qci where` names, separately for runs and snapshots: `empty` (no file, or none of that store's tables) or `healthy` (its schema version, and the number of runs or snapshots) | `./.qci/qci.db` exists and `QCI_HOME` is unset: its path and its health | `damaged` (`DamagedStoreError`, with what is missing) or `other schema version` (the version found and the one supported) |

**Accounts.** The check calls `AccountManager.list()` from `adapters/qiskit_ibm/live.py`,
inside the existing quiet-logging context, and uses only the returned keys. It calls it only
when the account file exists: `list()` creates an empty account file when there is none
(clarified 2026-10-20 in R1b; Findings), and `qci doctor` writes nothing. A missing file is
the `note` "no account file". It never reads
an `Account`'s fields and never prints a token, instance, CRN, URL, channel or any other
account detail beyond its name. It reads no environment variable for credentials. If the
file cannot be parsed, it prints only the exception type, not its message, which could quote
the file. Tests inject the account lister, as the capture tests inject the client factory;
the session guard keeps blocking `AccountManager.get` and `QiskitRuntimeService`.

**Store.** Both repositories are opened with `read_only=True` (SQLite `mode=ro`), so the
check creates no file, table or row, and a test asserts the store bytes are unchanged.

**Exit codes.** 0 when no check reports `problem` (notes allowed), 1 when at least one does,
and 2 for a usage error. `qci doctor` takes no options in R1.

### 5. Selecting runs and snapshots without pasting IDs

Every argument that takes a run ID (`qci show`, both arguments of `qci compare`,
`qci snapshot compare --footprint-run`, the first argument of `qci snapshot compare-run`) and
every argument that takes a snapshot ID (`qci snapshot show`, `qci snapshot export`, both
arguments of `qci snapshot compare`, the second argument of `qci snapshot compare-run`)
accepts a selector:

```
SELECTOR := ID | PREFIX | [BACKEND ":"] "latest" ["~" N]
```

- **`ID`**: a full 26-character ID. Exact match, as today. An argument equal to a stored ID
  selects it whatever its length (clarified 2026-10-20 in R1b: real IDs are 26-character
  ULIDs, but test stores use shorter IDs such as `BASE`; a selector form is matched first).
- **`PREFIX`**: 8 to 25 characters of an ID, matched case-sensitively against the start of
  every stored ID. Exactly one match selects it.
- **`latest`, `latest~N`** (N an integer, 1 or more; `latest` is `latest~0`): the entry at
  position N, counting from 0, in a fixed order over the entries the backend filter keeps.
  - **Runs:** ordered as `qci runs` lists them, by `run_id` descending, which is creation
    order. Every status counts: a run with `status=failed` can be selected.
  - **Snapshots:** ordered by `calibrated_at` (the provider's stamp on the document)
    descending. A snapshot with no `calibrated_at` is never selected by `latest`. This is not
    the `qci snapshots` order: after a backfill, the most recently stored snapshot can be
    the oldest document, and `latest` is meant to name the newest calibration.
- **`BACKEND:`** keeps only entries whose backend name equals `BACKEND` exactly. It is
  optional for runs and required for snapshots, so that a snapshot selector never mixes
  devices.

No other form exists: no ranges, no dates, no status filters, no fuzzy matching. An ID can
never be confused with a selector: IDs use Crockford base32 and contain no `:` or `~`, and no
ID equals `latest`.

**Ambiguity is reported, never guessed.** Exit 1, nothing selected, with every candidate
listed (at most 10, then a count of the rest):

- a prefix that matches two or more IDs;
- a run at position N whose ID shares its 10-character time part (the same millisecond) with
  the run before or after it in the order, since their creation order is not known;
- a snapshot at position N whose `calibrated_at` equals that of the snapshot before or after
  it in the order.

**Other outcomes.** No match (an unknown ID or prefix, or fewer than N + 1 entries) exits 1,
as an unknown ID does today. A malformed selector (a prefix shorter than 8 characters, `~`
without a positive integer, a snapshot `latest` without `BACKEND:`, or any other text that
fits no form) is a usage error and exits 2.

**Echo.** When an argument was a selector and not a full ID, the command prints to stderr
`<role>: <selector> -> <ID>` (for example `baseline: latest~1 -> 01M4K9G8...`, with the full
ID) before its output. stdout, and so `--json`, is unchanged.

**Where it lives.** Resolution is a pure function in `qci/core/selectors.py` over lists of
`(id, backend, sort_key)` that the repositories already return, with no SQL of its own and no
provider import. The CLI calls it before any service. Selectors read the store read-only and
are never stored.

### 6. Summary-first text output

`qci compare`, `qci snapshot compare` and `qci snapshot compare-run` print a short summary by
default. `--verbose` prints the summary and then today's full text, byte for byte.
`qci show`, `qci snapshot show` and the listings are unchanged in R1.

**The summary**, in this order, at most about 25 lines for a typical comparison:

1. The two inputs (role, ID, backend) and the overall status.
2. One line per section with its status. Only sections whose status is not `unchanged`
   list what differs: the field names, not their values.
3. Key statistics, where present: TVD and Hellinger distance with the sampling floor's p95
   and p-value (or the reason it is unavailable), and each observable's per-run estimates and
   its difference with the Newcombe interval.
4. Calibration magnitudes for the footprint (below).
5. One line: `Full detail: rerun with --verbose. Machine-readable: --json.`

**Magnitudes, not counts.** This is where the backlog item "summarize footprint differences
by magnitude, not counts" lands. Under exact comparison, nearly every re-measured continuous
value counts as changed (M1.4c), so a count of changed parameters says little. For each
calibration parameter name and unit in the comparison (for example `T1` in `us`,
`readout_error` dimensionless, `cz` `gate_error`), the summary shows: the number of footprint
resources compared, the number with status `changed`, the median and the largest absolute
delta with its unit, and the median and the largest relative delta,
`|candidate - baseline| / |baseline|`, each largest one naming its resource. A baseline of
exactly 0 has no relative delta: it is left out of the relative figures and counted as
"baseline 0", never given an infinite value. A parameter that is `unavailable` or
`not_comparable` is counted as such and never enters a figure as 0. `snapshot compare-run`
adds the earliest and latest live-minus-fake date difference, which it already computes.

These figures are summary statistics of deltas the comparison already holds. They are built
by a pure function in `qci/compare/summary.py` from the existing `Comparison`,
`SnapshotComparison` and `RunSnapshotComparison` models, and each figure is a `Metric` with
`EvidenceKind.CALCULATED`, method `qci.summary.magnitude` and method version `1`; the text
labels them `(calculated)`. A delta's direction is candidate minus baseline (for
`compare-run`, live minus fake), and the summary states the direction once in its heading.
The wording follows rule 8 and the M1.4b word list: it says "differs" and "delta", and names
no direction of change as preferable.

**Why `ComparisonPolicy` and `ENGINE_VERSION` do not change.** The comparison models, the
rules and the IDs are untouched. The summary is a view of an existing model, computed only on
the text path, and it is neither persisted nor part of `--json`.

**How unchanged JSON is guaranteed**, in R1b's commit order:

1. The first commit changes no file under `src/`. The 13 files in `tests/golden/compare/`
   pin `CompareService.compare(...).model_dump_json(indent=2)`, the service output, not the
   CLI's. The commit adds CLI-level golden files, generated through the Typer runner, of
   today's `--json` and today's text output of all three commands: `qci compare` over the
   runs of those 13 cases, and `qci snapshot compare` and `qci snapshot compare-run` over
   their existing test cases on the committed fixture. They go in `tests/golden/cli/`, and the
   tests compare bytes.
2. Later commits leave every golden JSON file, the 13 service-level ones and the new
   CLI-level ones, unchanged; `git diff` of the first commit against the last over them is
   empty, and the R1b report shows it.
3. The goldens of today's text become the `--verbose` goldens: `--verbose` output must be
   the summary followed by exactly that text.
4. A test asserts that `--json` and `--json --verbose` print identical bytes for every
   golden case: `--verbose` has no effect on JSON.
5. The existing neutral-wording tests of the three commands' output
   (`tests/test_cli_compare.py`, `tests/test_snapshot_compare.py`,
   `tests/test_run_snapshot_compare.py`) are extended to the default summary output, with the
   M1.4b word list for all three.

### 7. Quickstart for the README

R1b replaces the README's "Quick start" with this. The offline part needs no IBM account and
no network after the install.

**A README for users (user decision, 2026-10-20).** The README is written for users of the
package, in this order: what QCI is; install (core and the `ibm` extra); this quickstart;
core ideas in plain language (runs, comparisons, the sampling floor, observables, footprints,
snapshots, re-measured versus carried over); a command reference; what QCI deliberately does
not do; data and privacy; license and contributing. Developer material (the editable install,
milestones, the step workflow, internal troubleshooting) moves to `CONTRIBUTING.md` and
`docs/`, and the landing-page section to `site/README.md`. A test extracts the quickstart's
offline commands from `README.md` and runs them in a temporary store, so the README cannot
drift from the code.

**Self-contained for PyPI (accepted 2026-10-20).** The README is the package's long
description, so it must read completely on PyPI, where links into the repository do not
resolve. It carries inline: the quickstart below; what `qci compare` reports and the two
terms that need care (a changed result distribution, relevant hardware); observables and the
bit order; the extras and what works without `ibm`; the store location, `QCI_HOME`,
`qci where` and the `./.qci` note; selectors; the saved-account prerequisite and what
`capture`, `backfill` and `compare-run` do; and the D29 note that backfilled data stays
local. It has no relative link. Whether it gains absolute links to the repository is decided
when the repository's visibility is settled; until then it names `PLAN.md`, `docs/` and the
ADRs as files in the source repository, without links.

````markdown
## Quickstart (about five minutes)

Install into a fresh virtual environment (Python 3.12 or 3.13):

```bash
python3 -m venv qci-env
source qci-env/bin/activate
python -m pip install 'bloq-qci[ibm]'
qci doctor
qci where
```

Write a two-qubit workload:

```bash
cat > bell.py <<'EOF'
from qiskit import QuantumCircuit


def build() -> QuantumCircuit:
    qc = QuantumCircuit(2, 2, name="bell")
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])
    return qc
EOF
```

Run it twice on a local simulator of the `ibm_fez` device, with different sampling seeds,
then compare the two runs (baseline first):

```bash
qci run bell.py --backend fake_fez --seed 7
qci run bell.py --backend fake_fez --seed 7 --seed-simulator 8
qci runs
qci compare latest~1 latest
qci compare latest~1 latest --observable bell=00,11
qci compare latest~1 latest --verbose
```

`fake_fez` runs on your machine with a frozen copy of IBM's calibration as its noise model.

### Optional: compare with live calibration (needs an IBM Quantum account)

Save your account once, in an interactive Python session so the token stays out of your
shell history:

```python
from qiskit_ibm_runtime import QiskitRuntimeService
QiskitRuntimeService.save_account(token="...", instance="...", name="default-ibm-quantum-platform")
```

Then read the calibration `ibm_fez` publishes now (read-only: nothing runs on the device)
and compare it with the calibration frozen into `fake_fez`, for the qubits your run used:

```bash
qci doctor
qci snapshot capture --backend ibm_fez
qci snapshot compare-run latest ibm_fez:latest
```
````

### 8. Release process

- **Versioning.** `0.1.0` first. Before 1.0: a minor version for any change to the command
  surface, an exit code, a JSON shape, or a store schema; a patch version otherwise.
  `ComparisonPolicy.version`, `ENGINE_VERSION` and the store schema versions are independent
  of the package version, and the changelog names any of them that change.
- **Changelog.** `CHANGELOG.md` at the root, in the Keep a Changelog format, with an
  `Unreleased` section that each step keeps current. The `0.1.0` entry describes R1 and
  links ADR 0009.
- **Build once.** From a clean checkout of the release commit (`git status` clean), run
  `python -m build`, run the archive test (section 1) over those exact files, and record the
  SHA-256 of both. The same two files are tested locally, then go to TestPyPI and then to
  PyPI; each stage checks the hashes.
- **Credentials.** The user uploads, with `twine` or PyPI trusted publishing. API tokens live
  in the user's keyring or PyPI settings, never in the repository, a command line or a log.
  No agent uploads, tags or pushes.
- **R1c is two parts with different gates.**
  - *Part 1, the local clean-machine test (steps 1 to 3 below),* installs the locally built
    wheel and sdist. Nothing is published, so it has no gate.
  - *Part 2, the TestPyPI upload (step 4),* publishes the package. It was gated on the two
    license agreements, and that gate is met (section 1, Findings). D29 does not gate it: the
    archive test (section 1) checks that neither file holds IBM data, and the metadata has
    no project URLs.
- **Clean-machine test (R1c part 1).** In a directory outside the repository, with `PYTHONPATH`
  unset and `HOME` set to a new empty temporary directory (so the per-user default resolves
  inside it and no real store or saved account is visible):
  1. on Python 3.12 and on 3.13, create a fresh virtual environment and install the built
     wheel file with the `ibm` extra; then, in another fresh environment per version, install
     the built sdist the same way (`'bloq-qci[ibm] @ file:///<absolute path of the sdist>'`);
  2. run the quickstart's offline steps exactly as written, with `QCI_HOME` unset, and
     record every command's output and exit code; `qci where` must name a path under the
     temporary `HOME`, and `qci doctor` must exit 0 with the account check as a note;
  3. in a second fresh environment, install the wheel without the extra: `qci doctor` exits
     0 and reports the extra missing, `qci runs` and `qci compare latest~1 latest` read the
     store from step 2, and `qci run bell.py --backend fake_fez` exits 2 with the extra
     message and the store bytes unchanged;
  4. (part 2) upload both files to TestPyPI and repeat steps 1 and 2 installing from TestPyPI, with
     `--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/`
     and the exact version pinned (`bloq-qci[ibm]==0.1.0`), so no other project's
     `bloq-qci` can be picked.
  R1c records the machine, the OS and Python versions, the wheel hash, the outputs, and
  whether the hidden `.pth` problem appeared, in this ADR's Findings.
- **PyPI (R1d).** Gated on D29 being resolved for a public release (section 9). The
  licensing gate is met (section 1). The repository stays private until D29 is resolved.
  Then the user tags `v0.1.0`, uploads the two files whose hashes R1c recorded, and repeats
  the quickstart's offline steps from PyPI in a fresh environment. A packaged file that
  changes after R1c (for example README links once visibility is settled) means a
  new build, and R1c is repeated on it before R1d.

### 9. Out of scope for R1

- New comparison features: no new section, statistic, rule, threshold or policy version. The
  magnitude summary is a view of existing deltas.
- Hosted services of any kind: no server, telemetry, update check, account system or
  hosted store. Only `qci snapshot capture` and `qci snapshot backfill` use the network.
- Any redistribution of IBM data: no IBM calibration document, fixture, backfilled value,
  store or manifest in any package, and no change to D29's limits. The repository's
  committed `ibm_fez` fixture is outside the packages; the repository is made private until
  D29 is resolved, and whether a public repository may hold the fixture is part of that
  review. A mitigating fact, not a resolution: Qiskit's own fake backends distribute
  equivalent IBM calibration snapshots under Apache-2.0.
- New providers, a Windows-specific installer, conda packages, and a `qci` example command
  (the quickstart writes the workload file instead).

### 10. Acceptance criteria

#### R1b acceptance criteria (approved 2026-10-20)

Commit order and provenance:

- [ ] The first R1b commit changes no file under `src/` and adds the CLI-level golden files
      of section 6 (`--json` and text, for `qci compare` over the runs of the 13
      service-level cases, and for `qci snapshot compare` and `qci snapshot compare-run` over
      their existing test cases on the committed fixture), in `tests/golden/cli/`, compared
      byte for byte. They are green on unmodified `src/`.
- [ ] Every R1b commit carries a `Signed-off-by:` line (DCO 1.1).

Distribution and license:

- [ ] `pyproject.toml`: name `bloq-qci`; `dynamic = ["version"]` read from
      `src/qci/__init__.py`, where `__version__ = "0.1.0"`; `license = "Apache-2.0"` and
      `license-files = ["LICENSE", "NOTICE"]`; build requirement `hatchling>=1.27`;
      `requires-python = ">=3.12"`; classifiers for Python 3.12 and 3.13 only; no
      `[project.urls]`; core dependencies, and the `ibm` and `dev` extras, exactly as in
      section 2, with `qiskit-ibm-runtime>=0.50,<0.51`.
- [x] `LICENSE` is the unmodified Apache License 2.0 text and `NOTICE` is the two lines in
      section 1 (on `main` since PR #5, 2026-10-20; Findings). R1b leaves both unchanged.
- [ ] `AUTHORS` says the QCI Authors are the commit authors in the git history and names no
      one. `tests/fixtures/snapshots/README.md` and `CONTRIBUTING.md` say the IBM data under
      `tests/fixtures/` is not licensed by this project and is provided by IBM under IBM's
      own terms (moved from the README by user decision, 2026-10-20).
- [ ] `CONTRIBUTING.md` adopts the Developer Certificate of Origin 1.1, includes its text, and
      asks for `git commit -s`. `CLAUDE.md`'s step workflow requires a `Signed-off-by:` line
      on every commit, including commits made through Claude Code.
- [ ] `src/qci/py.typed` exists and is in the wheel.
- [ ] `provenance/environment.py` reads the version of the distribution `bloq-qci` and
      records it under the package key `qci`; a test shows the key and a non-null version
      with the package installed.
- [ ] `tests/test_distribution_contents.py` builds the sdist and the wheel from that sdist
      with `python -m build --no-isolation` into a temporary directory, and reports every
      member that meets any of the five conditions of section 1; no member does. The wheel
      and the sdist hold exactly the allow-listed members. A scanner self-test reports a
      synthetic archive holding `ibm_fez.json` under `tests/fixtures/`, and one holding the
      fixture's text inside a `.py` file.
- [ ] The build test writes nothing in the working tree (`git status` is clean afterwards).

Extras:

- [ ] With an import hook that blocks `qiskit`, `qiskit_ibm_runtime` and `qiskit_aer`, in a
      subprocess over a store prepared in the test session: `qci runs`, `qci show`,
      `qci compare`, `qci snapshots`, `qci snapshot show`, `qci snapshot compare`,
      `qci snapshot compare-run`, `qci where` and `qci doctor` print the same stdout and
      exit with the same code as with the SDKs (for `qci doctor`, every line except the
      `ibm` extra and saved-account lines, which report the extra missing by design; clarified
      2026-10-20 in R1b); `qci run`, `qci snapshot capture`,
      `qci snapshot backfill` and `qci snapshot export` exit 2 with the message in
      section 2, before opening the store or loading a workload, and the store bytes are
      unchanged.
- [ ] The extra check lives in `adapters/qiskit_ibm/` and uses `importlib.util.find_spec`
      without importing the SDKs. The architecture test still holds.

Store location:

- [ ] The per-user directory is tested for `darwin`, `win32` with and without
      `LOCALAPPDATA`, and another platform with `XDG_DATA_HOME` absolute, relative and unset,
      by patching the platform and environment. `QCI_HOME` overrides it; an empty `QCI_HOME`
      counts as unset.
- [ ] Read-only commands on a missing per-user directory create nothing and read an empty
      store. The first write creates the directory, with mode `0o700` on POSIX.
- [ ] `qci where` prints exactly the absolute `qci.db` path on stdout, its source and whether
      the file exists on stderr, opens no store, and exits 0.
- [ ] The `./.qci` note of section 3 is printed to stderr exactly when `QCI_HOME` is unset and
      `./.qci/qci.db` is a file in the current directory, by every command that opens a store
      and by `qci where` and `qci doctor`; never for a parent directory. stdout and exit codes
      are identical with and without it. The legacy file's bytes and modification time are
      unchanged after every command.

`qci doctor`:

- [ ] Each check of section 4 has a test for each of its `ok`, `note` and `problem` outcomes,
      with the account lister and the environment injected.
- [ ] A stub saved account whose token, instance, URL and channel are sentinel strings: none of
      them appears in stdout or stderr; the account name does. An unparseable account file
      prints only the exception type.
- [ ] Store outcomes `empty`, `healthy` (with schema versions and counts), `damaged` and
      `other schema version` are each tested, for runs and snapshots separately; the store
      bytes are unchanged after every case.
- [ ] Exit 0 with notes only, exit 1 with any `problem`. No IBM client is constructed and no
      connection is opened (the session guard).

Selectors:

- [ ] `qci/core/selectors.py` is a pure function over `(id, backend, sort_key)` lists with no
      provider import and no SQL; the architecture test covers it.
- [ ] Every argument listed in section 5 accepts each form: full ID, unique prefix of 8 to 25
      characters, `latest`, `latest~N`, and `BACKEND:latest[~N]`. For runs, the order is
      `run_id` descending and includes every status. For snapshots, it is `calibrated_at`
      descending, a snapshot without `calibrated_at` is never selected, and `BACKEND:` is
      required.
- [ ] Each ambiguity of section 5 (a prefix with two or more matches, a run sharing its
      millisecond with a neighbor, a snapshot sharing its `calibrated_at` with a neighbor)
      exits 1, selects nothing and lists the candidates, at most 10 and then a count.
- [ ] No match exits 1. Each malformed form of section 5 exits 2.
- [ ] A selector echoes `<role>: <selector> -> <ID>` on stderr. For each command, stdout with a
      selector is byte-identical to stdout with the full ID it resolved to.

Summary-first output:

- [ ] Default text output of the three commands is the summary of section 6. `--verbose`
      output is that summary followed by exactly the text golden of the first commit.
- [ ] `git diff` from the first R1b commit to the last over `tests/golden/` is empty for every
      JSON file, the 13 service-level ones and the CLI-level ones.
- [ ] `--json` and `--json --verbose` print identical bytes for every golden case.
- [ ] Magnitudes: for each parameter name and unit, counts compared and changed, median and
      largest absolute delta with unit, median and largest relative delta, each largest one
      naming its resource. Tests cover a baseline of exactly 0 (left out of relative figures,
      counted as "baseline 0", no infinite value) and `unavailable` and `not_comparable`
      parameters (counted, never entered as 0).
- [ ] Each figure is a `Metric` with `EvidenceKind.CALCULATED`, method
      `qci.summary.magnitude`, version 1, built in `qci/compare/summary.py` from the existing
      models. `ComparisonPolicy.version` (`qci.compare.v3`) and `ENGINE_VERSION` are
      unchanged.
- [ ] The existing neutral-wording tests of the three commands cover the default summary,
      with the M1.4b word list.

Docs:

- [ ] README is self-contained as in section 7, written for users in the order of section 7:
      the quickstart verbatim, the essential explanations inline, a "License and
      contributing" section pointing to `CONTRIBUTING.md` (which has the editable install),
      and no relative link (checked by a test). A test runs the quickstart's offline commands,
      extracted from `README.md`, in a temporary store. Developer material is in
      `CONTRIBUTING.md` or `docs/`, and the landing-page section in `site/README.md`. The
      README passes the neutral-wording check in full.
- [ ] `CLAUDE.md`, `AGENTS.md`, `docs/architecture.md` and `docs/data-model.md` describe the
      per-user store, `QCI_HOME`, the extras, `qci where`, `qci doctor`, selectors, the
      summary and `--verbose`, and the exit-code rows for the extra check, `qci doctor`,
      selectors and `qci where`. `CHANGELOG.md` exists with an `Unreleased` section describing
      R1. `PLAN.md` marks D5 resolved.
- [ ] All gates are clean, and every neutral-wording hit is justified.

#### R1c acceptance criteria (approved 2026-10-20, split 2026-10-20; run by the user)

Part 1, local clean-machine test (no gate):

- [ ] Before part 2: the name `bloq-qci` is unclaimed on PyPI and TestPyPI, and a search of
      PyPI for distributions shipping a top-level `qci` package is recorded.
- [ ] `CHANGELOG.md` has its dated `0.1.0` entry and every packaged file is final before the
      build. The two files are built once with `python -m build` from a clean checkout of the
      release commit on `main`; the archive test is run over those exact files, and both
      SHA-256 hashes are recorded.
- [ ] The clean-machine test of section 8, steps 1 to 3, on Python 3.12 and on 3.13, outside
      the repository, with `PYTHONPATH` unset and `HOME` a new empty directory, from the
      locally built wheel and, separately, the locally built sdist: every command and exit
      code is recorded; `qci where` names a path under that `HOME`; `qci doctor` exits 0
      with the account check as a note; the core-only environment reads the store, and
      `qci run` there exits 2 with the extra message and the store bytes unchanged.
- [ ] Whether the hidden `.pth` problem appeared is recorded.

Part 2, TestPyPI (gated on the two license agreements: met 2026-10-20; not gated on D29):

- [x] Both license agreements are recorded (PR #5, 2026-10-20; Findings).
- [ ] Part 1 is complete, on the same two files (hashes checked).
- [ ] The user uploads both files to TestPyPI. Steps 1 and 2 are repeated installing
      `bloq-qci[ibm]==0.1.0` from TestPyPI with the index options of section 8, and the
      installed wheel's hash equals the recorded one.
- [ ] Machine, OS, Python versions, hashes and outputs are recorded in this ADR's Findings. No
      IBM call is made; the quickstart's optional live part is not part of R1c.

#### R1d acceptance criteria (approved 2026-10-20; run by the user)

- [ ] D29 is resolved for a public release, with the date and the outcome in `PLAN.md`.
- [x] The comments by `toorha` and `dhruvhptl` on the pull request that adds `LICENSE`, each
      stating "I agree to license my contributions to this repository under the Apache
      License 2.0.", are recorded in this ADR's Findings (PR #5, 2026-10-20). The NOTICE
      has no `site/` exclusion, so no NOTICE change is needed.
- [ ] No packaged file changed since R1c's build; otherwise R1c is repeated on the new build.
- [ ] The user tags `v0.1.0` on the release commit and uploads to PyPI the two files R1c
      recorded; the hashes PyPI reports equal R1c's.
- [ ] The quickstart's offline steps, run from PyPI in a fresh environment with an empty
      `HOME`, give the same exit codes as in R1c, recorded in this ADR's Findings.
- [ ] `PLAN.md` marks R1 done.

## Findings

### Licensing (2026-10-20)

PR #5 ("chore: license the project under the Apache License 2.0", merged into `main` as
`384fd06`, with a `Signed-off-by:` line) adds `LICENSE` and `NOTICE`. `toorha` and
`dhruvhptl` each commented on PR #5 on 2026-10-20 with the exact sentence "I agree to license
my contributions to this repository under the Apache License 2.0.", as reported by the user.
Checked offline on `main` at `384fd06`:

- `LICENSE` has 202 lines and SHA-256
  `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`, byte-identical to the
  unmodified Apache License 2.0 text installed in `.venv` by `stevedore` 5.9.1
  (`stevedore-5.9.1.dist-info/licenses/LICENSE`).
- `NOTICE` is exactly two lines, `QCI` and `Copyright 2026 The QCI Authors`, each ending in a
  newline.

Consequences: the NOTICE needs no `site/` exclusion, the licensing gate on the TestPyPI
upload and on R1d is met, and R1d stays gated on D29.

### R1b implementation (2026-10-20)

Found while implementing R1b, offline, with `hatchling` 1.32.4, `build` 1.6.1 and
`qiskit-ibm-runtime` 0.50.0. Each led to a dated clarification above.

- **The sdist always holds `.gitignore`.** hatchling's sdist builder force-includes the VCS
  ignore file (`SdistBuilder.get_default_build_data`, from `vcs_exclusion_files`), and
  `only-include` and `ignore-vcs` do not remove it. It holds no data. The allow-list and the
  archive test include it; excluding it would need a build hook, itself shipped in the sdist.
- **`AccountManager.list()` writes.** `read_config` calls `_ensure_file_exists`, which creates
  `~/.qiskit/qiskit-ibm.json` (and its directory) when absent. `qci doctor` checks that the
  file exists first. The test session guard now also blocks `AccountManager.list`, and every
  test runs with a fresh `HOME` (and `USERPROFILE`, which `Path.home()` reads on Windows).
- **An unknown channel raises with the channel in the message.** `Account.from_saved_format`
  raises `InvalidAccountError` quoting the saved channel. `qci doctor` prints only the
  exception type, so a sentinel channel never appears; a test covers it.
- **Check 4 does not match the committed fixture.** Both payload patterns need no whitespace
  where the indented fixture has a newline: its `last_update_date` is a tagged object
  (`"last_update_date": {` then, on the next line, `"$datetime": ...`), so neither pattern
  matches anywhere in `ibm_fez.json`. Check 5 (the fixture's own `last_update_date` value)
  reports the fixture's text in any file, as the scanner self-test shows, and check 4 still
  reports compact payloads. The patterns are kept as written; widening them (for example
  `\{\s*"\$datetime"`) is an open question for review.
- **Short unknown IDs.** CLI tests that passed short unknown IDs (`NOPE`, `RUN`, `SNAP`) and
  expected exit 1 now pass 26-character unknown IDs, as the selector grammar makes short text
  that is not a stored ID a usage error (user decision, 2026-10-20).

## Consequences

- **Good:** a user installs with one command, can read and compare records without the
  provider SDKs, has one store per user, selects records without pasting IDs, and sees a
  short summary first. The archive test keeps IBM data out of both packages mechanically.
- **Good:** no record, store schema, comparison rule or JSON output changes. Existing stores
  open unchanged.
- **Cost:** a changed default store location. Users with `./.qci` stores must set
  `QCI_HOME`; the note tells them how. `CLAUDE.md`, `AGENTS.md`, `README.md`,
  `docs/architecture.md` and `docs/data-model.md` describe `./.qci` today and change in R1b.
- **Cost:** the `qiskit-ibm-runtime` upper bound means a reviewed step for each new minor
  version.
- **Cost:** the sdist carries no tests.
- **Risk:** the import name `qci` is shared with any other distribution that ships a
  top-level `qci` package; R1c checks PyPI for such a distribution and for the availability
  of the name `bloq-qci` before the TestPyPI upload.
