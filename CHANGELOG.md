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
  `qiskit-aer`).
- `CONTRIBUTING.md`, with the Developer Certificate of Origin 1.1 for contributions.

### Changed

- Run records keep the version of the `bloq-qci` distribution under the package key `qci`.
