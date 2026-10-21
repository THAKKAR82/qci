# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow the rules in
ADR 0009, section 8: before 1.0, a minor version for any change to the command surface, an
exit code, a JSON shape or a store schema, and a patch version otherwise.
`ComparisonPolicy.version`, `ENGINE_VERSION` and the store schema versions are independent of
the package version; an entry names any of them that change.

## [Unreleased]

Release 1 (R1, ADR 0009): packaging and first-run usability. Comparison rules, record schemas
and JSON output are unchanged.

### Added

- Distribution `bloq-qci` (import package and command `qci`), version 0.1.0, under the Apache
  License 2.0, with `LICENSE`, `NOTICE` and `AUTHORS`. The package is typed (`py.typed`).
- An `ibm` extra for the provider SDKs (`qiskit`, `qiskit-ibm-runtime` below 0.51,
  `qiskit-aer`). Without it, `qci run`, `qci snapshot capture`, `qci snapshot backfill` and
  `qci snapshot export` exit 2 with the install command; every other command works.
- `qci where`: the path of the `qci.db` file that commands use.
- `qci doctor`: local, read-only checks of Python, the package, its dependencies, the `ibm`
  extra, the saved IBM account (by name only) and the store. Exit 1 when a check reports a
  problem.
- Selectors: every run or snapshot argument accepts a full ID, a unique ID prefix of 8 or
  more characters, or `[BACKEND:]latest[~N]` (`BACKEND:` required for snapshots, which are
  ordered by `calibrated_at`). Ambiguity exits 1 with the candidates listed.
- A summary printed first by `qci compare`, `qci snapshot compare` and
  `qci snapshot compare-run`, with per-parameter calibration magnitudes (median and largest
  absolute and relative deltas, labeled calculated). `--verbose` adds the previous full text.
- `CONTRIBUTING.md`, with the Developer Certificate of Origin 1.1 for contributions.

### Changed

- The default store is per user (`~/Library/Application Support/qci` on macOS,
  `%LOCALAPPDATA%\qci` on Windows, `$XDG_DATA_HOME/qci` or `~/.local/share/qci` elsewhere),
  no longer `./.qci` in the current directory. `QCI_HOME` still overrides it. An existing
  `./.qci/qci.db` is never moved; commands print a note with the `QCI_HOME` setting that keeps
  using it.
- The default text output of the three comparison commands is the summary; use `--verbose`
  for the full text. `--json` output is unchanged.
- An argument shorter than 8 characters that is not a stored ID is now a usage error (exit 2)
  instead of an unknown ID (exit 1).
- Run and snapshot records keep the version of the `bloq-qci` distribution under the package
  key `qci`.

Unchanged: `ComparisonPolicy.version` (`qci.compare.v3`), the comparison engine version
(`qci.compare.engine.4`), the run and snapshot record schemas (version 1), and the store
schemas (run 1, snapshot 2).
