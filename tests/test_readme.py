"""README.md is self-contained for PyPI and its quickstart runs as written (ADR 0009, section 7).

The quickstart's offline commands are extracted from README.md and run in bash, in an empty
working directory with a fresh HOME and no QCI_HOME, so the store is the per-user default
inside that HOME. ``qci`` on PATH is a shim that runs this checkout's ``qci.cli.app``. The
install lines (venv, activate, pip) are not run: tests never use the network.
"""

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from qci.cli.app import app

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
ADR = ROOT / "docs" / "adr" / "0009-packaging-and-first-run.md"
NEUTRAL = re.compile(
    r"better|worse|regress|improv|degrad|\bpass|fail|significan|verdict|caus", re.IGNORECASE
)
INSTALL_LINE = re.compile(r"^(python3? -m venv |source |python -m pip install )")


def _text() -> str:
    return README.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(f"\n{heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def _bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL)


def quickstart() -> str:
    return _section(_text(), "## Quickstart (about five minutes)")


def offline_script() -> str:
    """The quickstart's bash blocks before the optional live part, without install lines."""
    offline = quickstart().split("### Optional:")[0]
    lines = [
        line
        for block in _bash_blocks(offline)
        for line in block.splitlines()
        if not INSTALL_LINE.match(line)
    ]
    return "\n".join(lines) + "\n"


def qci_commands(script: str) -> list[str]:
    return [line for line in script.splitlines() if line.startswith("qci ")]


def test_no_relative_links() -> None:
    text = _text()
    targets = re.findall(r"\]\(([^)]*)\)", text) + re.findall(r"(?:href|src)=[\"']([^\"']*)", text)
    relative = [t for t in targets if not re.match(r"(https?|mailto):", t)]
    assert relative == []
    assert not re.search(r"^\[[^\]]+\]:\s*(?!https?:)", text, flags=re.MULTILINE)


def test_the_whole_readme_uses_neutral_wording() -> None:
    hits = [line for line in _text().splitlines() if NEUTRAL.search(line)]
    assert hits == []


def test_sections_are_in_the_order_users_need() -> None:
    headings = re.findall(r"^## (.+)$", _text(), flags=re.MULTILINE)
    assert headings == [
        "Install",
        "Quickstart (about five minutes)",
        "Core ideas",
        "Command reference",
        "What QCI deliberately does not do",
        "Data and privacy",
        "License and contributing",
    ]


def test_the_quickstart_is_the_adr_text_verbatim() -> None:
    adr = ADR.read_text(encoding="utf-8")
    start = adr.index("````markdown\n") + len("````markdown\n")
    text = adr[start : adr.index("\n````", start)]
    assert text in _text()


def test_the_offline_quickstart_is_what_the_test_runs() -> None:
    assert qci_commands(offline_script()) == [
        "qci doctor",
        "qci where",
        "qci run bell.py --backend fake_fez --seed 7",
        "qci run bell.py --backend fake_fez --seed 7 --seed-simulator 8",
        "qci runs",
        "qci compare latest~1 latest",
        "qci compare latest~1 latest --observable bell=00,11",
        "qci compare latest~1 latest --verbose",
    ]
    assert "cat > bell.py <<'EOF'" in offline_script()


def _commands_in_reference() -> list[list[str]]:
    reference = _section(_text(), "## Command reference")
    found = re.findall(r"^\| `(qci [^`]+)` \|", reference, flags=re.MULTILINE)
    online = _section(_text(), "## Quickstart (about five minutes)").split("### Optional:")[1]
    found += qci_commands("\n".join(_bash_blocks(online)))
    return [shlex.split(command) for command in found]


def test_every_documented_command_exists() -> None:
    commands = _commands_in_reference()
    assert len(commands) >= 16
    for argv in commands:
        words = [w for w in argv[1:] if re.fullmatch(r"[a-z][a-z-]*", w)]
        path = words[:2] if words[:1] == ["snapshot"] else words[:1]
        result = CliRunner().invoke(app, [*path, "--help"])
        assert result.exit_code == 0, (argv, result.output)
        for option in [w for w in argv if w.startswith("--")]:
            assert option in result.stdout, (argv, option)


def _shim(directory: Path) -> Path:
    """A ``qci`` command that runs this checkout's CLI with the test's interpreter."""
    directory.mkdir()
    shim = directory / "qci"
    code = "import sys; from qci.cli.app import main; sys.argv[0] = 'qci'; main()"
    shim.write_text(
        "#!/bin/sh\n"
        f"PYTHONPATH={shlex.quote(str(ROOT / 'src'))} exec {shlex.quote(sys.executable)} "
        f'-c {shlex.quote(code)} "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return directory


@pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None, reason="the quickstart is a bash script"
)
def test_the_offline_quickstart_runs_as_written(tmp_path: Path) -> None:
    home, work = tmp_path / "home", tmp_path / "work"
    home.mkdir()
    work.mkdir()
    bin_dir = _shim(tmp_path / "bin")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(home),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    script = "set -euo pipefail\nset -x\n" + offline_script()
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    store = Path(next(line for line in out.splitlines() if line.endswith("qci.db")))  # where
    assert store.is_relative_to(home) and store.is_file()
    assert "note     saved IBM account: no account file" in out
    assert out.count("Comparison sha256:") == 4  # --verbose: summary, then the full text
    assert "  bell = P({00, 11}): " in out
    assert "Limitations:" in out  # the --verbose comparison
    assert "baseline: latest~1 -> " in result.stderr
    assert (work / "bell.py").is_file()
    # No store in the working directory: loading the workload writes only its bytecode.
    assert {p.name for p in work.iterdir()} <= {"bell.py", "__pycache__"}
