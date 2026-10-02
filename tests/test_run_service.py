import subprocess
from pathlib import Path

import pytest

from conftest import StubAdapter
from qci.core.errors import WorkloadLoadError
from qci.core.ports import LoadedWorkload
from qci.domain.circuit import CompileConfig
from qci.domain.execution import ExecutionConfig
from qci.domain.metric import EvidenceKind
from qci.domain.run import RunStage, RunStatus
from qci.provenance.environment import collect_environment
from qci.provenance.git import collect_git, strip_credentials
from qci.services.run_service import RunRequest, RunService, sanitize_error_message
from qci.storage.sqlite import SqliteRunRepository


def _request(tmp_path: Path) -> RunRequest:
    return RunRequest(
        workload_path=tmp_path / "workload.py",
        backend_name="stub_backend",
        compile_config=CompileConfig(optimization_level=1, seed_transpiler=3),
        execution_config=ExecutionConfig(shots=10, seed_simulator=3),
        tags={"k": "v"},
    )


def test_successful_run_is_persisted_with_labeled_metrics(
    tmp_path: Path, repo: SqliteRunRepository
) -> None:
    run = RunService(StubAdapter(), repo).run(_request(tmp_path))
    assert run.status is RunStatus.SUCCEEDED
    assert repo.get(run.run_id) == run
    assert run.tags == {"k": "v"}
    kinds = {m.name: m.kind for m in run.metrics}
    assert kinds["total_shots"] is EvidenceKind.MEASURED
    assert kinds["transpiled_depth"] is EvidenceKind.CALCULATED
    assert {m.kind for m in run.metrics} <= {EvidenceKind.MEASURED, EvidenceKind.CALCULATED}


def test_execution_failure_is_persisted_as_failed_run_with_partial_capture(
    tmp_path: Path, repo: SqliteRunRepository
) -> None:
    adapter = StubAdapter(executor_error=RuntimeError("device exploded"))
    run = RunService(adapter, repo).run(_request(tmp_path))

    stored = repo.get(run.run_id)
    assert stored.status is RunStatus.FAILED
    assert stored.error is not None
    assert stored.error.stage is RunStage.EXECUTE
    assert stored.error.error_type == "builtins.RuntimeError"
    assert stored.error.message == "device exploded"
    # Everything captured before the failure is kept.
    assert stored.backend is not None
    assert stored.backend_snapshot is not None
    assert stored.compilation is not None
    assert stored.execution is None and stored.result is None


def test_workload_load_failure_raises_and_persists_nothing(
    tmp_path: Path, repo: SqliteRunRepository
) -> None:
    class FailingLoader:
        def load(self, path: Path, entrypoint: str) -> LoadedWorkload:
            raise WorkloadLoadError("no such workload")

    adapter = StubAdapter()
    adapter.loader = FailingLoader()  # type: ignore[assignment]
    with pytest.raises(WorkloadLoadError):
        RunService(adapter, repo).run(_request(tmp_path))
    assert repo.list_runs() == []


def test_error_messages_are_sanitized() -> None:
    message = "failed to fetch https://user:s3cret@example.com/api " + "x" * 5000
    cleaned = sanitize_error_message(message)
    assert "s3cret" not in cleaned and "user:" not in cleaned
    assert "https://example.com/api" in cleaned
    assert cleaned.endswith("... [truncated]")
    assert len(cleaned) < 2100


# --- provenance collected by the service ---


def test_strip_credentials() -> None:
    assert strip_credentials("https://tok:x@github.com/o/r.git") == "https://github.com/o/r.git"
    assert strip_credentials("https://github.com/o/r.git") == "https://github.com/o/r.git"
    assert strip_credentials("git@github.com:o/r.git") == "git@github.com:o/r.git"


def test_collect_git_outside_repo_is_all_none(tmp_path: Path) -> None:
    git = collect_git(tmp_path)
    assert (git.commit, git.branch, git.dirty, git.remote) == (None, None, None, None)


def test_collect_git_in_repo(tmp_path: Path) -> None:
    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    run("remote", "add", "origin", "https://user:pw@example.com/repo.git")
    (tmp_path / "f.txt").write_text("1")
    run("add", "f.txt")
    run("commit", "-q", "-m", "init")
    clean = collect_git(tmp_path)
    assert clean.commit is not None and len(clean.commit) == 40
    assert clean.branch == "main"
    assert clean.dirty is False
    assert clean.remote == "https://example.com/repo.git"
    (tmp_path / "f.txt").write_text("2")
    assert collect_git(tmp_path).dirty is True


def test_collect_environment_reports_requested_packages() -> None:
    env = collect_environment(["pydantic", "definitely-not-installed-pkg"])
    assert env.packages["qci"] is not None
    assert env.packages["pydantic"] is not None
    assert env.packages["definitely-not-installed-pkg"] is None
    assert env.config_hash.startswith("sha256:")
    assert (
        env.config_hash
        == collect_environment(["pydantic", "definitely-not-installed-pkg"]).config_hash
    )
