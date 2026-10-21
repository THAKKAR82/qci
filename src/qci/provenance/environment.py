"""Python environment provenance."""

import platform
from collections.abc import Iterable
from importlib import metadata

from qci.core.hashing import hash_json
from qci.domain.provenance import EnvironmentProvenance

DISTRIBUTIONS = {"qci": "bloq-qci"}
"""Package key -> installed distribution, where they differ. QCI is distributed as
``bloq-qci`` and still recorded under the key ``qci`` (ADR 0009, section 1)."""


def package_version(name: str) -> str | None:
    """The installed version of package ``name``, or None if it is not installed."""
    try:
        return metadata.version(DISTRIBUTIONS.get(name, name))
    except metadata.PackageNotFoundError:
        return None


def collect_environment(packages: Iterable[str]) -> EnvironmentProvenance:
    """Collect interpreter details and the versions of ``qci`` plus ``packages``."""
    names = sorted({"qci", *packages})
    fields = {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": {name: package_version(name) for name in names},
    }
    return EnvironmentProvenance.model_validate({**fields, "config_hash": hash_json(fields)})
