"""One manual check of historical calibration by datetime (ADR 0005, Findings). Uses the network.

Run once, by hand, with a saved account. Never run by tests. It asks for the current properties
and for properties as of 24 hours earlier, and prints only dates, whether the two payloads
match, and an exception type. It never prints account data or error text.

    PYTHONPATH=src .venv/bin/python scripts/check_historical_calibration.py --backend ibm_fez

Interpretation (recorded in ADR 0005, never acted on in code):
- honored: match=no and past_last_update is at or before requested_before;
- ignored: match=yes and now_last_update is after requested_before;
- raises: an exception type is printed for the historical request;
- inconclusive: match=yes and now_last_update is itself before requested_before.
"""

import argparse
from datetime import UTC, datetime, timedelta
from typing import Any

from qci.adapters.qiskit_ibm.live import DEFAULT_ACCOUNT, create_service, quiet_client_logs


def _date(properties: Any) -> str:
    when = getattr(properties, "last_update_date", None) if properties is not None else None
    return when.astimezone(UTC).isoformat() if isinstance(when, datetime) else "none"


def main() -> int:
    parser = argparse.ArgumentParser(description="One historical-calibration check.")
    parser.add_argument("--backend", default="ibm_fez")
    parser.add_argument("--account", default=DEFAULT_ACCOUNT)
    args = parser.parse_args()

    with quiet_client_logs():
        try:
            backend = create_service(name=args.account).backend(
                args.backend, use_fractional_gates=False
            )
            now = backend.properties(refresh=True)
        except Exception as exc:
            print(f"exception during setup: {type(exc).__name__}")
            return 1
        at = datetime.now(UTC) - timedelta(hours=24)
        print(f"requested_before: {at.isoformat()}")
        print(f"now_last_update: {_date(now)}")
        try:
            past = backend.properties(datetime=at)
        except Exception as exc:
            print(f"exception during historical request: {type(exc).__name__}")
            return 0
        print(f"past_last_update: {_date(past)}")
        same = (now.to_dict() if now else None) == (past.to_dict() if past else None)
    print(f"match: {'yes' if same else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
