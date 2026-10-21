"""Built archives hold exactly the allow-listed files and no IBM data (ADR 0009, section 1).

The sdist is built from the working tree, and the wheel from that sdist, as a user installing
from source would get it, with ``python -m build --no-isolation`` into a temporary directory.
Set ``QCI_DIST_DIR`` to a directory holding one built ``.tar.gz`` and one ``.whl`` to scan those
exact files instead (the release process, ADR 0009 section 8).

A member is reported when:

1. its path (after the sdist's ``bloq_qci-<version>/`` prefix) starts with ``tests/``,
   ``experiments/``, ``docs/``, ``site/``, ``examples/`` or ``scripts/``;
2. it is not on the allow-list;
3. it is byte-identical (SHA-256) to a file under ``tests/fixtures/``;
4. its bytes match an IBM payload marker or contain a SQLite header;
5. it contains the committed fixture's own ``last_update_date`` value.
"""

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

import qci

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
IBM_FEZ = FIXTURES / "snapshots" / "ibm_fez.json"
VERSION = qci.__version__
SDIST_PREFIX = f"bloq_qci-{VERSION}/"
DIST_INFO = f"bloq_qci-{VERSION}.dist-info/"

EXCLUDED_DIRECTORIES = ("tests/", "experiments/", "docs/", "site/", "examples/", "scripts/")
# hatchling always adds the VCS ignore file to an sdist; it holds no data (ADR 0009, section 1).
SDIST_FILES = {
    "pyproject.toml",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "NOTICE",
    "AUTHORS",
    "PKG-INFO",
    ".gitignore",
}
WHEEL_FILES = {
    f"{DIST_INFO}{name}"
    for name in (
        "METADATA",
        "WHEEL",
        "RECORD",
        "entry_points.txt",
        "licenses/LICENSE",
        "licenses/NOTICE",
    )
}
PAYLOAD_MARKERS = (
    re.compile(rb'"last_update_date"\s*:\s*"\d{4}-\d{2}-\d{2}'),
    re.compile(rb'\{"\$datetime"\s*:\s*"\d{4}-'),
    re.compile(re.escape(b"SQLite format 3\x00")),
)


@dataclass(frozen=True)
class Archive:
    kind: str
    """``sdist`` or ``wheel``."""
    members: dict[str, bytes]
    """Member path (without the sdist prefix) -> bytes."""


def read_sdist(data: bytes) -> Archive:
    members: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for info in tar.getmembers():
            if not info.isfile():
                continue
            extracted = tar.extractfile(info)
            assert extracted is not None
            name = info.name.removeprefix(SDIST_PREFIX)
            members[name] = extracted.read()
    return Archive("sdist", members)


def read_wheel(data: bytes) -> Archive:
    with zipfile.ZipFile(io.BytesIO(data)) as wheel:
        members = {
            info.filename: wheel.read(info) for info in wheel.infolist() if not info.is_dir()
        }
    return Archive("wheel", members)


def allowed(kind: str, name: str) -> bool:
    if kind == "sdist":
        return name in SDIST_FILES or name == "src/qci/py.typed" or _package_py(name, "src/qci/")
    return name in WHEEL_FILES or name == "qci/py.typed" or _package_py(name, "qci/")


def _package_py(name: str, root: str) -> bool:
    return name.startswith(root) and name.endswith(".py") and "__pycache__" not in name


@cache
def fixture_hashes() -> frozenset[str]:
    return frozenset(
        hashlib.sha256(p.read_bytes()).hexdigest() for p in FIXTURES.rglob("*") if p.is_file()
    )


@cache
def fixture_stamp() -> bytes:
    data = json.loads(IBM_FEZ.read_text(encoding="utf-8"))
    stamp = data["snapshot"]["provider_raw"]["properties"]["last_update_date"]
    value = stamp["$datetime"] if isinstance(stamp, dict) else stamp
    assert isinstance(value, str) and value
    return value.encode()


def findings(archive: Archive) -> list[str]:
    """Every member that meets any of the five conditions, one line per condition."""
    found: list[str] = []
    for name, data in sorted(archive.members.items()):
        where = f"{archive.kind}: {name}"
        if name.startswith(EXCLUDED_DIRECTORIES):
            found.append(f"{where}: in an excluded directory")
        if not allowed(archive.kind, name):
            found.append(f"{where}: not on the allow-list")
        if hashlib.sha256(data).hexdigest() in fixture_hashes():
            found.append(f"{where}: byte-identical to a file under tests/fixtures/")
        for marker in PAYLOAD_MARKERS:
            if marker.search(data):
                found.append(f"{where}: matches {marker.pattern!r}")
        if fixture_stamp() in data:
            found.append(f"{where}: contains the fixture's last_update_date")
    return found


def expected_members(kind: str) -> set[str]:
    """Exactly the allow-listed members: every package module, plus the fixed files."""
    modules = {str(p.relative_to(ROOT / "src")) for p in (ROOT / "src" / "qci").rglob("*.py")} | {
        "qci/py.typed"
    }
    if kind == "sdist":
        return {f"src/{m}" for m in modules} | SDIST_FILES
    return modules | WHEEL_FILES


# --- building ----------------------------------------------------------------------------------


def _git_status() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain", "--ignored", "--untracked-files=all"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _build(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )


@dataclass(frozen=True)
class Built:
    sdist: Archive
    wheel: Archive
    status_before: str
    status_after: str


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Built]:
    given = os.environ.get("QCI_DIST_DIR")
    before = _git_status()
    if given:
        out = Path(given)
    else:
        out = tmp_path_factory.mktemp("dist")
        _build("--sdist", "--outdir", str(out), str(ROOT))
        (sdist_path,) = out.glob("*.tar.gz")
        _build("--wheel", "--outdir", str(out), str(sdist_path))
    (sdist_path,) = out.glob("*.tar.gz")
    (wheel_path,) = out.glob("*.whl")
    yield Built(
        read_sdist(sdist_path.read_bytes()),
        read_wheel(wheel_path.read_bytes()),
        before,
        _git_status(),
    )


def test_no_member_meets_any_condition(built: Built) -> None:
    assert findings(built.sdist) + findings(built.wheel) == []


@pytest.mark.parametrize("kind", ["sdist", "wheel"])
def test_archives_hold_exactly_the_allow_listed_members(built: Built, kind: str) -> None:
    archive = built.sdist if kind == "sdist" else built.wheel
    assert set(archive.members) == expected_members(kind)


def test_wheel_is_typed_and_licensed(built: Built) -> None:
    assert built.wheel.members["qci/py.typed"] == b""
    assert built.wheel.members[f"{DIST_INFO}licenses/LICENSE"] == (ROOT / "LICENSE").read_bytes()
    assert built.wheel.members[f"{DIST_INFO}licenses/NOTICE"] == (ROOT / "NOTICE").read_bytes()
    metadata = built.wheel.members[f"{DIST_INFO}METADATA"].decode()
    assert "Name: bloq-qci\n" in metadata
    assert f"Version: {VERSION}\n" in metadata
    assert "License-Expression: Apache-2.0\n" in metadata
    assert "Project-URL" not in metadata


def test_build_writes_nothing_in_the_working_tree(built: Built) -> None:
    assert built.status_after == built.status_before


# --- the scanner detects what it looks for -----------------------------------------------------


def _tar(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(SDIST_PREFIX + name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as wheel:
        for name, data in members.items():
            wheel.writestr(name, data)
    return buffer.getvalue()


def test_scanner_reports_the_fixture_under_tests_fixtures() -> None:
    name = "tests/fixtures/snapshots/ibm_fez.json"
    archive = read_sdist(_tar({"README.md": b"# QCI\n", name: IBM_FEZ.read_bytes()}))
    reported = findings(archive)
    for condition in (
        "in an excluded directory",
        "not on the allow-list",
        "byte-identical to a file under tests/fixtures/",
        "contains the fixture's last_update_date",
    ):
        assert f"sdist: {name}: {condition}" in reported
    assert not [line for line in reported if line.startswith("sdist: README.md")]


def test_scanner_reports_fixture_text_inside_a_python_file() -> None:
    text = IBM_FEZ.read_text(encoding="utf-8")
    source = f"PAYLOAD = {text!r}\n".encode()
    reported = findings(read_wheel(_zip({"qci/leak.py": source, "qci/clean.py": b"X = 1\n"})))
    # The fixture is pretty-printed, so its tagged dates do not match check 4's patterns,
    # which expect no whitespace after "{"; check 5 reports it.
    assert "wheel: qci/leak.py: contains the fixture's last_update_date" in reported
    assert not [line for line in reported if line.startswith("wheel: qci/clean.py")]


def test_scanner_reports_a_store_and_a_tagged_date() -> None:
    members = {
        "qci/store.py": b"SQLite format 3\x00...",
        "qci/tagged.py": b'D = {"$datetime": "2025-01-01T00:00:00+00:00"}\n',
        "qci/stamp.py": b'P = {"last_update_date": "2025-01-01T00:00:00Z"}\n',
    }
    reported = findings(Archive("wheel", members))
    for name in members:
        assert [line for line in reported if line.startswith(f"wheel: {name}: matches")], name
