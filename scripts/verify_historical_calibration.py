"""D21 verification protocol for historical calibration lookups (ADR 0008, section 2).

Uses the network. Run by hand only, with a saved account; never run by tests. It prints only
device names, snapshot IDs, requested and returned dates, properties hashes, the store's hash
and outcome labels. It never prints account data, backend payloads or error text; an exception
is reported by its type name only. It writes nothing: the QCI store is opened read-only, once,
before any request, and its SHA-256 is printed before and after.

    PYTHONPATH=src .venv/bin/python scripts/verify_historical_calibration.py --store PATH

Part 1, per device: one current request (``properties(refresh=True)``), one request per offset
in ``OFFSETS_DAYS`` before a single anchor time, and a repeat of the ``REPEAT_OFFSET_DAYS``
request with the identical requested time.

Part 2, ground-truth cross-check: for each stored live snapshot of the device (newest first,
at most ``--max-cross-checks``), a request as of that snapshot's first ``captured_at``, whose
returned properties hash is compared with the hash of the stored ``provider_raw`` properties.

Requested times are aware UTC datetimes with a zero offset, because the client's
``local_to_utc`` reinterprets any other offset as local time. Every properties document is
normalized exactly as ``qci snapshot capture`` normalizes it before hashing.

Outcome labels, part 1 (ADR 0008, section 2), checked in this order:
- inconclusive:no_document, inconclusive:no_returned_date;
- non_monotonic: the returned last_update_date is newer than one returned for a less distant
  request of the same device (the current request counts as the least distant);
- ignored: the returned document equals the current one while the current last_update_date
  is after the requested time; inconclusive:no_newer_document when the current one is itself
  at or before the requested time; inconclusive:no_current_date when it has no date;
- ignored:returned_after_requested: a different document dated after the requested time;
- honored_distant: a different document dated more than ``HONORED_WINDOW`` before the
  requested time;
- honored: a different document dated at or before the requested time, within the window;
- raises:<ExceptionType>; raises:<ExceptionType>:too_many_requests stops the script.
The repeat line is labeled repeat:identical or repeat:different by hash.

Outcome labels, part 2: match, different_document, inconclusive:no_document, raises:<Type>.
"""

import argparse
import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from qci.adapters.qiskit_ibm.live import (
    DEFAULT_ACCOUNT,
    build_captured_calibration,
    create_service,
    quiet_client_logs,
)
from qci.core.hashing import hash_json
from qci.domain.backend import SnapshotSource
from qci.storage.snapshots import SqliteSnapshotRepository

PROTOCOL = "qci.d21.verify.2"
DEVICES = ("ibm_fez", "ibm_kingston", "ibm_marrakesh")
OFFSETS_DAYS = (1, 7, 30, 90, 180, 365)
REPEAT_OFFSET_DAYS = 30
HONORED_WINDOW = timedelta(hours=48)
MIN_PAUSE_SECONDS = 1.0
DEFAULT_STORE = Path.home() / ".qci-live" / "qci.db"


class TooManyRequestsError(Exception):
    """Raised to stop the whole protocol at the first too-many-requests response."""


@dataclass(frozen=True)
class Document:
    """What the protocol keeps from one properties document: its date and its hash."""

    present: bool
    last_update: datetime | None
    hash: str | None


def document(properties: Any) -> Document:
    """Normalize as capture does (UTC, lossless JSON, redaction), then hash the properties."""
    if properties is None:
        return Document(present=False, last_update=None, hash=None)
    captured = build_captured_calibration(
        backend_name="unused",
        backend_version=None,
        source=SnapshotSource.LIVE_CALIBRATION,
        properties=properties.to_dict(),
        configuration=None,
        capture_options={},
        captured_at=datetime.now(UTC),
        environment={},
    )
    return Document(
        present=True,
        last_update=captured.calibrated_at,
        hash=hash_json(captured.provider_raw["properties"]),
    )


def classify(
    requested: datetime, returned: Document, current: Document, floor: datetime | None
) -> str:
    """``floor`` is the oldest last_update_date returned so far for less distant requests."""
    if not returned.present or returned.hash is None:
        return "inconclusive:no_document"
    if returned.last_update is None:
        return "inconclusive:no_returned_date"
    if floor is not None and returned.last_update > floor:
        return "non_monotonic"
    if returned.hash == current.hash:
        if current.last_update is None:
            return "inconclusive:no_current_date"
        if current.last_update <= requested:
            return "inconclusive:no_newer_document"
        return "ignored"
    if returned.last_update > requested:
        return "ignored:returned_after_requested"
    if requested - returned.last_update > HONORED_WINDOW:
        return "honored_distant"
    return "honored"


def _too_many_requests(exc: BaseException) -> bool:
    """HTTP 429 or IBM error code 1202 anywhere in the chain. The text is never printed."""
    seen: BaseException | None = exc
    while seen is not None:
        if getattr(seen, "status_code", None) == 429 or "Error code: 1202" in str(seen):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def _raises(exc: Exception) -> str:
    label = f"raises:{type(exc).__name__}"
    return f"{label}:too_many_requests" if _too_many_requests(exc) else label


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "none"


def _digest(doc: Document | None) -> str:
    return doc.hash if doc is not None and doc.hash is not None else "none"


def _line(device: str, requested: str, doc: Document | None, outcome: str) -> None:
    returned = _iso(doc.last_update) if doc is not None else "none"
    print(
        f"{device}  requested_before={requested}  returned_last_update={returned}  "
        f"properties_hash={_digest(doc)}  outcome={outcome}",
        flush=True,
    )


def _request(backend: Any, at: datetime | None) -> Document:
    properties = backend.properties(refresh=True) if at is None else backend.properties(datetime=at)
    return document(properties)


def _stop_if_limited(outcome: str) -> None:
    if outcome.endswith(":too_many_requests"):
        raise TooManyRequestsError


@dataclass(frozen=True)
class StoredSnapshot:
    snapshot_id: str
    captured_at: datetime
    calibrated_at: datetime | None
    properties_hash: str | None


def stored_live_snapshots(store: Path, limit: int) -> dict[str, list[StoredSnapshot]]:
    """Live snapshots per device, newest first capture first, read once in read-only mode."""
    repository = SqliteSnapshotRepository(store, read_only=True)
    try:
        found: dict[str, list[StoredSnapshot]] = {}
        for device in DEVICES:
            rows: list[StoredSnapshot] = []
            for item in repository.list_snapshots(backend_name=device):
                snapshot = repository.get(item.snapshot_id)
                if snapshot.source is not SnapshotSource.LIVE_CALIBRATION:
                    continue
                properties = snapshot.provider_raw.get("properties")
                rows.append(
                    StoredSnapshot(
                        snapshot_id=snapshot.snapshot_id,
                        captured_at=snapshot.captured_at.astimezone(UTC),
                        calibrated_at=snapshot.calibrated_at,
                        properties_hash=hash_json(properties) if properties is not None else None,
                    )
                )
                if len(rows) == limit:
                    break
            found[device] = rows
        return found
    finally:
        repository.close()


def _store_hash(store: Path) -> str:
    return hashlib.sha256(store.read_bytes()).hexdigest() if store.is_file() else "absent"


def _verify_offsets(backend: Any, device: str, anchor: datetime, pause: float) -> None:
    try:
        current = _request(backend, None)
    except Exception as exc:
        outcome = _raises(exc)
        _line(device, "current", None, outcome)
        _stop_if_limited(outcome)
        return
    _line(device, "current", current, "current")

    floor = current.last_update
    first: dict[int, Document] = {}
    for days in (*OFFSETS_DAYS, REPEAT_OFFSET_DAYS):
        time.sleep(pause)
        requested = anchor - timedelta(days=days)
        try:
            returned = _request(backend, requested)
        except Exception as exc:
            outcome = _raises(exc)
            _line(device, requested.isoformat(), None, outcome)
            _stop_if_limited(outcome)
            continue
        if days in first:
            same = first[days].hash is not None and first[days].hash == returned.hash
            outcome = "repeat:identical" if same else "repeat:different"
            _line(device, requested.isoformat(), returned, outcome)
            continue
        first[days] = returned
        _line(
            device, requested.isoformat(), returned, classify(requested, returned, current, floor)
        )
        if returned.last_update is not None and (floor is None or returned.last_update < floor):
            floor = returned.last_update


def _cross_check(backend: Any, device: str, snapshots: list[StoredSnapshot], pause: float) -> None:
    for snap in snapshots:
        time.sleep(pause)
        returned: Document | None = None
        try:
            returned = _request(backend, snap.captured_at)
        except Exception as exc:
            outcome = _raises(exc)
        else:
            if not returned.present:
                outcome = "inconclusive:no_document"
            elif returned.hash == snap.properties_hash:
                outcome = "match"
            else:
                outcome = "different_document"
        print(
            f"{device}  cross_check  snapshot={snap.snapshot_id}  "
            f"requested_before={snap.captured_at.isoformat()}  "
            f"stored_last_update={_iso(snap.calibrated_at)}  "
            f"returned_last_update={_iso(returned.last_update if returned else None)}  "
            f"stored_hash={snap.properties_hash or 'none'}  returned_hash={_digest(returned)}  "
            f"outcome={outcome}",
            flush=True,
        )
        _stop_if_limited(outcome)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify historical calibration lookups (D21).")
    parser.add_argument("--account", default=DEFAULT_ACCOUNT)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE, help="QCI store, read-only.")
    parser.add_argument(
        "--pause", type=float, default=5.0, help="Seconds between requests (minimum 1)."
    )
    parser.add_argument(
        "--max-cross-checks", type=int, default=10, help="Stored snapshots per device (max)."
    )
    args = parser.parse_args()
    pause = max(float(args.pause), MIN_PAUSE_SECONDS)
    store: Path = args.store.expanduser()

    anchor = datetime.now(UTC).replace(microsecond=0)
    print(f"protocol={PROTOCOL}  anchor={anchor.isoformat()}  pause_s={pause:g}", flush=True)
    print(f"store_sha256_before={_store_hash(store)}", flush=True)
    snapshots = stored_live_snapshots(store, max(int(args.max_cross_checks), 0))
    print(
        "stored_live_snapshots  "
        + "  ".join(f"{device}={len(snapshots[device])}" for device in DEVICES),
        flush=True,
    )
    status = 0
    with quiet_client_logs():
        try:
            service = create_service(name=args.account)
            for index, device in enumerate(DEVICES):
                if index:
                    time.sleep(pause)
                try:
                    backend = service.backend(device, use_fractional_gates=False)
                except Exception as exc:
                    outcome = _raises(exc)
                    _line(device, "backend", None, outcome)
                    _stop_if_limited(outcome)
                    continue
                _verify_offsets(backend, device, anchor, pause)
                _cross_check(backend, device, snapshots[device], pause)
        except TooManyRequestsError:
            print("stopped  outcome=too_many_requests  (no retries)", flush=True)
            status = 3
        except Exception as exc:
            print(f"setup  outcome={_raises(exc)}", flush=True)
            status = 1
    print(f"store_sha256_after={_store_hash(store)}", flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
