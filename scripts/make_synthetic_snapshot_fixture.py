"""Write the SYNTHETIC snapshot fixture from the installed FakeFez. Offline; no account.

The data is FakeFez's frozen configuration and properties, passed through the same path as a
live capture (UTC normalization, lossless conversion, redaction, measurement extraction,
storage, export). It is not live hardware data: the snapshot's source is ``static_fake``, its
backend is ``fake_fez``, and the fixture's ``fixture_origin`` is ``synthetic``.

    .venv/bin/python scripts/make_synthetic_snapshot_fixture.py
"""

import argparse
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from qiskit_ibm_runtime.fake_provider import FakeFez

from qci.adapters.qiskit_ibm.live import build_captured_calibration, capture_environment
from qci.adapters.qiskit_ibm.redact import redact_payload
from qci.domain.backend import SnapshotSource
from qci.services.snapshot_service import SnapshotService
from qci.storage.snapshots import SqliteSnapshotRepository

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "tests" / "fixtures" / "snapshots" / "synthetic_fake_fez.json"
CAPTURED_AT = datetime(2026, 10, 9, tzinfo=UTC)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    fake = FakeFez()
    configuration = fake.configuration()
    properties = fake.properties()
    environment = capture_environment()
    captured = build_captured_calibration(
        backend_name=fake.name,
        backend_version=str(configuration.backend_version),
        source=SnapshotSource.STATIC_FAKE,
        properties=properties.to_dict(),
        configuration=configuration.to_dict(),
        capture_options={"use_fractional_gates": False},
        captured_at=CAPTURED_AT,
        environment=environment,
    )
    note = (
        "SYNTHETIC: derived from the frozen FakeFez configuration and properties shipped with "
        f"qiskit-ibm-runtime {environment['qiskit-ibm-runtime']}. Not a live capture. "
        "Regenerate with scripts/make_synthetic_snapshot_fixture.py."
    )
    with tempfile.TemporaryDirectory() as tmp:
        repository = SqliteSnapshotRepository(Path(tmp) / "qci.db")
        try:
            service = SnapshotService(repository)
            outcome = service.record(captured)
            text = service.export_fixture(
                outcome.snapshot.snapshot_id, redact=redact_payload, secrets=[], note=note
            )
        finally:
            repository.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"wrote {args.output} ({len(text.encode())} bytes)")


if __name__ == "__main__":
    main()
