"""``qci doctor``: local checks of the installation and the store (ADR 0009, section 4).

Each check reports one line, ``ok``, ``note`` or ``problem``. Nothing here makes a network
call, constructs an IBM client or writes a file: stores are opened read-only (SQLite
``mode=ro``), and the saved-account check reads only account names. Every input is injected
through ``DoctorInputs``, so tests replace the account lister and the environment.
"""

import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Literal

import qci
from qci.adapters.qiskit_ibm import extra
from qci.adapters.qiskit_ibm import live as ibm_live
from qci.core.errors import DamagedStoreError, SchemaVersionError
from qci.storage.location import StoreLocation, legacy_store, store_location
from qci.storage.snapshots import snapshot_store_summary
from qci.storage.sqlite import run_store_summary

Outcome = Literal["ok", "note", "problem"]
VersionLookup = Callable[[str], str | None]
AccountLister = Callable[[], list[str] | None]
"""Saved account names, or None when there is no account file."""

DISTRIBUTION = "bloq-qci"
CORE_DISTRIBUTIONS = ("pydantic", "typer", "sqlalchemy", "numpy", "openqasm3")
TESTED_PYTHON = ((3, 12), (3, 13))


@dataclass(frozen=True)
class Check:
    outcome: Outcome
    name: str
    detail: str

    def line(self) -> str:
        return f"{self.outcome:<7}  {self.name}: {self.detail}"


@dataclass(frozen=True)
class DoctorInputs:
    python_version: tuple[int, int, int]
    version_of: VersionLookup
    """Installed version of a distribution, or None."""
    missing_sdk_modules: Callable[[], list[str]]
    account_lister: AccountLister
    location: StoreLocation
    legacy: Path | None
    """``./.qci`` when its ``qci.db`` exists and ``QCI_HOME`` is unset."""


def installed_version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def default_inputs() -> DoctorInputs:
    v = sys.version_info
    return DoctorInputs(
        python_version=(v.major, v.minor, v.micro),
        version_of=installed_version,
        missing_sdk_modules=extra.missing_sdk_modules,
        account_lister=ibm_live.saved_account_names,
        location=store_location(),
        legacy=legacy_store(Path.cwd()),
    )


def check_python(version: tuple[int, int, int]) -> Check:
    text = ".".join(str(part) for part in version)
    if version[:2] in TESTED_PYTHON:
        return Check("ok", "Python", text)
    if version[:2] > (3, 12):
        return Check("note", "Python", f"{text} (untested; QCI is tested on 3.12 and 3.13)")
    return Check("problem", "Python", f"{text} (QCI needs 3.12 or later)")


def check_package(version_of: VersionLookup) -> Check:
    installed = version_of(DISTRIBUTION)
    if installed == qci.__version__:
        return Check("ok", "package", f"{DISTRIBUTION} {installed}")
    found = f"{DISTRIBUTION} {installed}" if installed else f"no {DISTRIBUTION} distribution"
    return Check(
        "problem",
        "package",
        f"{found}, but the imported qci is {qci.__version__} (a stale or mixed install; "
        f"reinstall {DISTRIBUTION})",
    )


def check_core(version_of: VersionLookup) -> Check:
    versions = {name: version_of(name) for name in CORE_DISTRIBUTIONS}
    missing = [name for name, v in versions.items() if v is None]
    if missing:
        return Check("problem", "core dependencies", f"missing {', '.join(missing)}")
    return Check(
        "ok", "core dependencies", ", ".join(f"{name} {v}" for name, v in versions.items())
    )


def check_ibm_extra(missing_modules: list[str], version_of: VersionLookup) -> Check:
    if not missing_modules:
        return Check(
            "ok",
            "ibm extra",
            ", ".join(f"{name} {version_of(name)}" for name in extra.SDK_DISTRIBUTIONS),
        )
    if len(missing_modules) == len(extra.SDK_MODULES):
        return Check(
            "note",
            "ibm extra",
            f"not installed; {', '.join(extra.EXTRA_COMMANDS)} need it: "
            "pip install 'bloq-qci[ibm]'",
        )
    return Check(
        "problem",
        "ibm extra",
        f"partly installed, {', '.join(missing_modules)} missing: pip install 'bloq-qci[ibm]'",
    )


def check_account(extra_check: Check, lister: AccountLister) -> Check:
    name = "saved IBM account"
    if extra_check.outcome != "ok":
        return Check("note", name, "not checked: the ibm extra is not installed")
    try:
        names = lister()
    except Exception as exc:
        # Only the type: the message could quote the account file.
        return Check("problem", name, f"the account file cannot be read ({type(exc).__name__})")
    if names is None:
        return Check(
            "note",
            name,
            "no account file; qci snapshot capture and backfill need an account saved with "
            "QiskitRuntimeService.save_account",
        )
    if ibm_live.DEFAULT_ACCOUNT in names:
        return Check("ok", name, ibm_live.DEFAULT_ACCOUNT)
    saved = ", ".join(names) if names else "none"
    return Check(
        "note",
        name,
        f"no account named {ibm_live.DEFAULT_ACCOUNT}; saved accounts: {saved} "
        "(select one with --account NAME)",
    )


def store_health(db: Path) -> list[tuple[Outcome, str]]:
    """Runs, then snapshots: ``(ok, "empty" or "healthy, ...")`` or ``(problem, ...)``."""
    found: list[tuple[Outcome, str]] = []
    for label, summarize in (("runs", run_store_summary), ("snapshots", snapshot_store_summary)):
        try:
            summary = summarize(db)
        except DamagedStoreError as exc:
            found.append(("problem", f"{label} damaged: {exc}"))
            continue
        except SchemaVersionError as exc:
            found.append(("problem", f"{label} other schema version: {exc}"))
            continue
        if summary is None:
            found.append(("ok", f"{label} empty"))
        else:
            version, count = summary
            found.append(("ok", f"{label} healthy, schema version {version}, {count} {label}"))
    return found


def check_store(location: StoreLocation) -> list[Check]:
    where = f"{location.db} ({location.source})"
    return [
        Check(outcome, "store", f"{detail}; {where}")
        for outcome, detail in store_health(location.db)
    ]


def check_legacy(legacy: Path | None) -> list[Check]:
    if legacy is None:
        return []
    health = "; ".join(detail for _, detail in store_health(legacy / "qci.db"))
    return [
        Check(
            "note",
            "legacy store",
            f"./.qci/qci.db exists and QCI_HOME is unset ({legacy / 'qci.db'}): {health}",
        )
    ]


def run_checks(inputs: DoctorInputs) -> list[Check]:
    extra_check = check_ibm_extra(inputs.missing_sdk_modules(), inputs.version_of)
    return [
        check_python(inputs.python_version),
        check_package(inputs.version_of),
        check_core(inputs.version_of),
        extra_check,
        check_account(extra_check, inputs.account_lister),
        *check_store(inputs.location),
        *check_legacy(inputs.legacy),
    ]
