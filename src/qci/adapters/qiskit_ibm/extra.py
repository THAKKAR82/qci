"""Whether the ``ibm`` extra is installed (ADR 0009, section 2).

Checked with ``importlib.util.find_spec``, which locates a module without importing it, so
the check never loads a provider SDK.
"""

import importlib.util

SDK_MODULES = ("qiskit", "qiskit_ibm_runtime", "qiskit_aer")
SDK_DISTRIBUTIONS = ("qiskit", "qiskit-ibm-runtime", "qiskit-aer")
EXTRA_MESSAGE = "this command needs the ibm extra: pip install 'bloq-qci[ibm]'"
EXTRA_COMMANDS = ("qci run", "qci snapshot capture", "qci snapshot backfill", "qci snapshot export")
"""The commands that need the extra; every other command works without it."""


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        # A parent that cannot be imported, or a module blocked in sys.modules.
        return False


def missing_sdk_modules() -> list[str]:
    """The provider SDK modules that cannot be found, in ``SDK_MODULES`` order."""
    return [module for module in SDK_MODULES if not _installed(module)]
