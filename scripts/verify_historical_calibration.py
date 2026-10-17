"""D21 verification protocol for historical calibration lookups (ADR 0008, section 2).

Uses the network. Run by hand only, with a saved account; never run by tests. It reads
calibration and writes nothing: it opens no QCI store and creates no file. It prints only
device names, requested and returned dates, properties hashes and outcome labels. It never
prints account data, backend payloads or error text; an exception is reported by its type
name only.

    PYTHONPATH=src .venv/bin/python scripts/verify_historical_calibration.py

For each device: one current request (``properties(refresh=True)``), one request per offset in
``OFFSETS_DAYS`` before a single anchor time, and a repeat of the ``REPEAT_OFFSET_DAYS``
request with the identical requested time. Requested times are aware UTC datetimes with a zero
offset, because the client's ``local_to_utc`` reinterprets any other offset as local time.

Outcome labels (ADR 0008, section 2):
- honored: the returned document differs from the current one (by hash) and its
  last_update_date is at or before the requested time;
- ignored: the returned document equals the current one while the current last_update_date
  is after the requested time;
- ignored:returned_after_requested: a different document whose last_update_date is after the
  requested time;
- raises:<ExceptionType>: the request raised;
- inconclusive:<reason>: no document, no date, or the current document is itself at or before
  the requested time, so honored and ignored cannot be told apart.
The repeat line is labeled repeat:identical or repeat:different by hash.
"""

import argparse
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from qci.adapters.qiskit_ibm.jsonable import to_jsonable
from qci.adapters.qiskit_ibm.live import (
    DEFAULT_ACCOUNT,
    create_service,
    quiet_client_logs,
    utc_datetimes,
)
from qci.adapters.qiskit_ibm.redact import redact_payload
from qci.core.hashing import hash_json

PROTOCOL = "qci.d21.verify.1"
DEVICES = ("ibm_fez", "ibm_kingston", "ibm_marrakesh")
OFFSETS_DAYS = (1, 7, 30, 90, 180, 365)
REPEAT_OFFSET_DAYS = 30
MIN_PAUSE_SECONDS = 1.0


class Document:
    """What the protocol keeps from one response: its date and its hash, nothing else."""

    def __init__(self, properties: Any) -> None:
        self.present = properties is not None
        when = getattr(properties, "last_update_date", None) if self.present else None
        self.last_update = when.astimezone(UTC) if isinstance(when, datetime) else None
        self.hash: str | None = None
        if self.present:
            redacted, _ = redact_payload(to_jsonable(utc_datetimes(properties.to_dict())))
            self.hash = hash_json(redacted)


def classify(requested: datetime, returned: Document, current: Document) -> str:
    if not returned.present or returned.hash is None:
        return "inconclusive:no_document"
    if returned.last_update is None:
        return "inconclusive:no_returned_date"
    if returned.hash == current.hash:
        if current.last_update is None:
            return "inconclusive:no_current_date"
        if current.last_update <= requested:
            return "inconclusive:no_newer_document"
        return "ignored"
    if returned.last_update <= requested:
        return "honored"
    return "ignored:returned_after_requested"


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "none"


def _line(device: str, requested: str, doc: Document | None, outcome: str) -> None:
    returned = _iso(doc.last_update) if doc is not None else "none"
    digest = doc.hash if doc is not None and doc.hash is not None else "none"
    print(
        f"{device}  requested_before={requested}  returned_last_update={returned}  "
        f"properties_hash={digest}  outcome={outcome}",
        flush=True,
    )


def _verify_device(service: Any, device: str, anchor: datetime, pause: float) -> None:
    try:
        backend = service.backend(device, use_fractional_gates=False)
        current = Document(backend.properties(refresh=True))
    except Exception as exc:
        _line(device, "current", None, f"raises:{type(exc).__name__}")
        return
    _line(device, "current", current, "current")

    by_offset: dict[int, Document] = {}
    for days in (*OFFSETS_DAYS, REPEAT_OFFSET_DAYS):
        time.sleep(pause)
        requested = anchor - timedelta(days=days)
        try:
            returned = Document(backend.properties(datetime=requested))
        except Exception as exc:
            _line(device, requested.isoformat(), None, f"raises:{type(exc).__name__}")
            continue
        if days in by_offset:
            first = by_offset[days]
            same = first.hash is not None and first.hash == returned.hash
            _line(
                device,
                requested.isoformat(),
                returned,
                "repeat:identical" if same else "repeat:different",
            )
            continue
        by_offset[days] = returned
        _line(device, requested.isoformat(), returned, classify(requested, returned, current))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify historical calibration lookups (D21).")
    parser.add_argument("--account", default=DEFAULT_ACCOUNT)
    parser.add_argument(
        "--pause", type=float, default=5.0, help="Seconds between requests (minimum 1)."
    )
    args = parser.parse_args()
    pause = max(float(args.pause), MIN_PAUSE_SECONDS)

    anchor = datetime.now(UTC).replace(microsecond=0)
    print(f"protocol={PROTOCOL}  anchor={anchor.isoformat()}  pause_s={pause:g}", flush=True)
    with quiet_client_logs():
        try:
            service = create_service(name=args.account)
        except Exception as exc:
            print(f"setup  outcome=raises:{type(exc).__name__}", flush=True)
            return 1
        for index, device in enumerate(DEVICES):
            if index:
                time.sleep(pause)
            _verify_device(service, device, anchor, pause)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
