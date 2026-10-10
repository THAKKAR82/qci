"""SnapshotService: capture published calibration and export sanitized fixtures (ADR 0005).

Depends only on ports. The redactor is injected because its rules belong to the adapter.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from qci.core.errors import FixtureExportError
from qci.core.hashing import hash_json
from qci.core.ids import new_run_id
from qci.core.ports import CalibrationSource, CapturedCalibration, SnapshotRepository
from qci.domain.backend import SnapshotSource
from qci.domain.snapshot import (
    CalibrationSnapshot,
    SnapshotCapture,
    SnapshotFixture,
)

Redactor = Callable[[JsonValue], tuple[JsonValue, list[str]]]

FIXTURE_SNAPSHOT_ID = "FIXTURE-SNAPSHOT"


def fixture_capture_id(index: int) -> str:
    return f"FIXTURE-CAPTURE-{index}"


def snapshot_content_hash(captured: CapturedCalibration) -> str:
    """Hash of what the provider published, independent of when or where it was captured.

    Covers provider, backend name, capture options and the redacted, UTC-normalized payload.
    Excludes ``captured_at`` and the environment.
    """
    return hash_json(
        {
            "provider": captured.provider,
            "backend_name": captured.backend_name,
            "capture_options": captured.capture_options,
            "provider_raw": captured.provider_raw,
        }
    )


def fixture_text(fixture: SnapshotFixture) -> str:
    """Plain UTF-8 JSON, sorted keys, 2-space indent, trailing newline. Never compressed."""
    return (
        json.dumps(fixture.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=False)
        + "\n"
    )


@dataclass(frozen=True)
class CaptureOutcome:
    snapshot: CalibrationSnapshot
    capture: SnapshotCapture
    created: bool
    """False when the content was identical to an existing snapshot."""
    measurement_count: int


class SnapshotService:
    def __init__(self, repository: SnapshotRepository) -> None:
        self._repository = repository

    def capture(self, source: CalibrationSource, backend_name: str) -> CaptureOutcome:
        """Capture once and record it. Any error propagates and persists nothing."""
        return self.record(source.capture(backend_name))

    def record(self, captured: CapturedCalibration) -> CaptureOutcome:
        snapshot = CalibrationSnapshot(
            snapshot_id=new_run_id(),
            content_hash=snapshot_content_hash(captured),
            provider=captured.provider,
            backend_name=captured.backend_name,
            backend_version=captured.backend_version,
            source=captured.source,
            captured_at=captured.captured_at,
            calibrated_at=captured.calibrated_at,
            capture_options=captured.capture_options,
            extraction_method=captured.extraction_method,
            extraction_method_version=captured.extraction_method_version,
            redactions=captured.redactions,
            environment=captured.environment,
            provider_raw=captured.provider_raw,
        )
        capture = SnapshotCapture(
            capture_id=new_run_id(),
            snapshot_id=snapshot.snapshot_id,
            captured_at=captured.captured_at,
        )
        stored, created = self._repository.save(snapshot, captured.measurements, capture)
        return CaptureOutcome(
            snapshot=stored,
            capture=capture.model_copy(update={"snapshot_id": stored.snapshot_id}),
            created=created,
            measurement_count=len(self._repository.measurements(stored.snapshot_id)),
        )

    def export_fixture(
        self,
        snapshot_id: str,
        *,
        redact: Redactor,
        secrets: Sequence[str],
        note: str | None = None,
    ) -> str:
        """Return the sanitized fixture text. Raises ``FixtureExportError`` instead of
        returning anything unsafe.

        The payload is redacted again with the current rules, and any new paths are added to
        ``redactions``. Local IDs become placeholders. If anything outside ``provider_raw``
        would need redaction, or the text contains any of ``secrets`` verbatim, the export
        aborts: the rules are incomplete, and that is fixed in code, not in the fixture.
        """
        snapshot = self._repository.get(snapshot_id)
        provider_raw, new_paths = redact(snapshot.provider_raw)
        if not isinstance(provider_raw, dict):  # pragma: no cover - redaction keeps the shape
            raise FixtureExportError("redaction changed the payload shape")
        record = CalibrationSnapshot.model_validate(
            {
                **snapshot.model_dump(),
                "snapshot_id": FIXTURE_SNAPSHOT_ID,
                "provider_raw": provider_raw,
                "redactions": [*snapshot.redactions, *new_paths],
            }
        )
        captures = [
            SnapshotCapture(
                capture_id=fixture_capture_id(index),
                snapshot_id=FIXTURE_SNAPSHOT_ID,
                captured_at=capture.captured_at,
            )
            for index, capture in enumerate(self._repository.captures(snapshot_id), start=1)
        ]
        fixture = SnapshotFixture(
            fixture_origin=(
                "live_capture"
                if snapshot.source is SnapshotSource.LIVE_CALIBRATION
                else "synthetic"
            ),
            fixture_note=note,
            snapshot=record,
            measurements=self._repository.measurements(snapshot_id),
            captures=captures,
        )

        outside = fixture.model_dump(mode="json")
        outside["snapshot"].pop("provider_raw")
        _, outside_paths = redact(outside)
        if outside_paths:
            raise FixtureExportError(
                f"{len(outside_paths)} value(s) outside the provider payload match a redaction "
                "rule; recapture with the current rules. Nothing was written."
            )

        text = fixture_text(fixture)
        for secret in secrets:
            if secret and (secret in text or json.dumps(secret)[1:-1] in text):
                raise FixtureExportError(
                    "the export contains a value of the saved account that no redaction rule "
                    "covers; fix the rules in code. Nothing was written."
                )
        return text
