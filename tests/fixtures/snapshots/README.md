# Calibration fixtures

`ibm_fez.json` is a calibration document published by IBM for the `ibm_fez` device, captured
read-only with `qci snapshot capture` and written with `qci snapshot export`, which redacts
credential-like values and replaces local IDs with placeholders.

**The IBM data in this directory, and anywhere under `tests/fixtures/`, is not licensed by this
project.** It is provided by IBM under IBM's own terms. The Apache License 2.0 in `LICENSE`
covers the QCI Authors' work only.

These files are test inputs. They are excluded from the built wheel and sdist, which
`tests/test_distribution_contents.py` checks (ADR 0009, section 1). Backfilled historical
calibration is never committed here or anywhere else (ADR 0008, D29 in `PLAN.md`).
