# AGENTS.md

`CLAUDE.md` is authoritative for the non-negotiable rules and the step workflow: branching,
never committing to `main`, the gates, and stopping for review. `PLAN.md` names the current
step. If this file conflicts with `CLAUDE.md`, `CLAUDE.md` wins.

This file adds only Windows and environment notes. Architecture facts live in
`docs/architecture.md`.

## Windows command equivalents

These use Git Bash, which the neutral-wording check needs for `grep`. Python on Windows
separates `MYPYPATH` entries with `;`, not `:`, so quote the value: an unquoted `;` ends the
shell command.

```bash
python -m venv .venv && .venv/Scripts/python.exe -m pip install -e '.[dev]'

.venv/Scripts/ruff.exe check .
.venv/Scripts/ruff.exe format --check .
.venv/Scripts/python.exe -m mypy --strict src tests
MYPYPATH='src;experiments/repeated_sampling' .venv/Scripts/python.exe -m mypy --strict experiments
.venv/Scripts/python.exe -m pytest -q --basetemp="$TEMP/qci-pytest"
git diff main...HEAD -U0 -- src docs README.md | grep -E '^\+' | grep -v '^+++' | grep -n -i -E 'better|worse|regress|improv|degrad|\bpass|fail|significan|verdict|caus' || echo "neutral-wording check: no hits"
```

In PowerShell, set the experiments path with
`$env:MYPYPATH = "src;experiments/repeated_sampling"` before running mypy. When `CLAUDE.md`
adds an experiment directory to `MYPYPATH`, add it here with `;`. `CLAUDE.md` is the source of
truth for which gates exist.

## Windows gotchas

- **`pytest` needs `--basetemp`.** A stale `%TEMP%\pytest-of-<user>` with a broken ACL makes
  tests error at fixture setup with `PermissionError: [WinError 5]`, unrelated to the code.
  Pass `--basetemp=<writable dir>`, as above. A fresh directory outside the repository keeps
  the working tree clean.
- **`tests/test_architecture.py` must keep `SYSTEMROOT` in the child environment.** The test
  scrubs the environment of the subprocess it starts. On Windows, `asyncio` imports
  `_overlapped` (Winsock), which fails with `WinError 10106` without `SYSTEMROOT`. Do not
  reduce that environment to `PYTHONPATH` alone.

## Running the CLI

Use the `qci` console script, `.venv/Scripts/qci.exe`. `python -m qci.cli.app` exits 0 with
no output, because `cli/app.py` defines `main()` without a `__main__` guard, and there is no
`qci/__main__.py`.

## Website

The website lives in `site/`. It is independent of the Python package, has no build step, and
is not covered by the product gates.
