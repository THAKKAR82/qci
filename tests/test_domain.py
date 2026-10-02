import pytest
from pydantic import ValidationError

from conftest import make_run
from qci.domain.run import Run, RunError, RunStage, RunStatus


def test_run_json_round_trip_is_lossless() -> None:
    run = make_run()
    restored = Run.model_validate_json(run.model_dump_json())
    assert restored == run
    assert restored.model_dump_json() == run.model_dump_json()


def test_run_is_frozen() -> None:
    run = make_run()
    with pytest.raises(ValidationError):
        run.status = RunStatus.FAILED  # type: ignore[misc]


def test_unknown_fields_are_rejected() -> None:
    data = make_run().model_dump(mode="json")
    data["unexpected"] = 1
    with pytest.raises(ValidationError):
        Run.model_validate(data)


def test_naive_datetimes_are_rejected() -> None:
    data = make_run().model_dump(mode="json")
    data["created_at"] = "2026-01-01T12:00:00"
    with pytest.raises(ValidationError):
        Run.model_validate(data)


def test_failed_run_requires_error_and_allows_partial_capture() -> None:
    with pytest.raises(ValidationError):
        make_run(status=RunStatus.FAILED)
    failed = make_run(
        status=RunStatus.FAILED,
        error=RunError(stage=RunStage.EXECUTE, error_type="RuntimeError", message="boom"),
        execution=None,
        result=None,
        metrics=[],
    )
    assert failed.compilation is not None and failed.result is None


def test_succeeded_run_must_be_complete_and_error_free() -> None:
    with pytest.raises(ValidationError):
        make_run(result=None)
    with pytest.raises(ValidationError):
        make_run(error=RunError(stage=RunStage.COMPILE, error_type="E", message="m"))


def test_schema_version_is_pinned() -> None:
    data = make_run().model_dump(mode="json")
    assert data["schema_version"] == 1
    data["schema_version"] = 2
    with pytest.raises(ValidationError):
        Run.model_validate(data)
