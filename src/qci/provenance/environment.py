"""Python environment provenance."""

import platform
from collections.abc import Iterable
from importlib import metadata

from qci.core.hashing import hash_json
from qci.domain.provenance import EnvironmentProvenance


def _version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def collect_environment(packages: Iterable[str]) -> EnvironmentProvenance:
    """Collect interpreter details and the versions of ``qci`` plus ``packages``."""
    names = sorted({"qci", *packages})
    fields = {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": {name: _version(name) for name in names},
    }
    return EnvironmentProvenance.model_validate({**fields, "config_hash": hash_json(fields)})
