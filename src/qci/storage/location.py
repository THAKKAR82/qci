"""Where the store lives (ADR 0009, section 3). Standard library only.

``QCI_HOME`` names the directory holding ``qci.db``; an empty value counts as unset. Otherwise
the store is per user, in the platform's data directory. A ``./.qci/qci.db`` from before R1 is
never moved, copied, linked or merged: callers only report it.
"""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DB_FILENAME = "qci.db"
LEGACY_DIRECTORY = ".qci"


def user_data_directory(platform: str, environ: Mapping[str, str], home: Path) -> Path:
    """The per-user store directory for ``platform`` (a ``sys.platform`` value)."""
    if platform == "darwin":
        return home / "Library" / "Application Support" / "qci"
    if platform == "win32":
        local = environ.get("LOCALAPPDATA")
        return Path(local) / "qci" if local else home / "AppData" / "Local" / "qci"
    xdg = environ.get("XDG_DATA_HOME")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / "qci"
    return home / ".local" / "share" / "qci"


@dataclass(frozen=True)
class StoreLocation:
    directory: Path
    """Absolute."""
    source: Literal["QCI_HOME", "per-user default"]

    @property
    def db(self) -> Path:
        return self.directory / DB_FILENAME


def store_location(
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> StoreLocation:
    environ = os.environ if environ is None else environ
    configured = environ.get("QCI_HOME")
    if configured:
        return StoreLocation(Path(configured).absolute(), "QCI_HOME")
    directory = user_data_directory(
        sys.platform if platform is None else platform, environ, home or Path.home()
    )
    return StoreLocation(directory.absolute(), "per-user default")


def legacy_store(cwd: Path, environ: Mapping[str, str] | None = None) -> Path | None:
    """``cwd/.qci``, absolute, when ``QCI_HOME`` is unset and ``cwd/.qci/qci.db`` is a file.

    Only ``cwd`` is checked, never its parents, and only with ``Path.is_file``.
    """
    environ = os.environ if environ is None else environ
    if environ.get("QCI_HOME"):
        return None
    directory = cwd.absolute() / LEGACY_DIRECTORY
    return directory if (directory / DB_FILENAME).is_file() else None


def legacy_note(legacy: Path, location: StoreLocation) -> str:
    return (
        f"note: ./{LEGACY_DIRECTORY}/{DB_FILENAME} exists, but QCI now uses {location.db} by "
        "default.\n"
        "To keep using that store, set QCI_HOME to its directory:\n"
        f'  export QCI_HOME="{legacy}"'
    )


def create_store_directory(directory: Path) -> None:
    """Create ``directory`` for a write, mode 0o700 on POSIX. An existing one is untouched."""
    directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        return
    if os.name == "posix":
        directory.chmod(0o700)  # mkdir's mode is reduced by the umask
