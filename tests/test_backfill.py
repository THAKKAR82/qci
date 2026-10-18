"""``qci snapshot backfill`` with stub clients only (ADR 0008, sections 3 to 6). No network."""

import sqlite3
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from qci.adapters.qiskit_ibm import live
from qci.adapters.qiskit_ibm.historical import (
    VERIFIED_LOOKUP_DEPTH_DAYS,
    IbmHistoricalCalibrationSource,
    is_too_many_requests,
)
from qci.cli.app import app
from qci.core.errors import TooManyRequestsError
from qci.core.hashing import hash_json
from qci.domain.backend import SnapshotSource
from qci.services import backfill_service
from qci.services.backfill_service import grid_times
from qci.storage.snapshots import SqliteSnapshotRepository
from snapshot_stubs import (
    SENTINEL_ACCOUNT,
    SENTINELS,
    HistoryBackend,
    RateLimitError,
    StubFactory,
)

NOW = datetime(2026, 10, 18, 21, 0, 30, tzinfo=UTC)
MIDNIGHT = datetime(2026, 10, 18, tzinfo=UTC)
DEVICE = "ibm_fez"
# One document every 12 hours, stamped 06:30 and 18:30 UTC, for more than a year.
STAMPS = [
    datetime(2025, 10, 1, 6, 30, tzinfo=UTC) + timedelta(hours=12 * i) for i in range(2 * 385)
]


def day(n: int) -> datetime:
    """The UTC midnight ``n`` days before ``MIDNIGHT``."""
    return MIDNIGHT - timedelta(days=n)


@dataclass
class Env:
    home: Path
    pauses: list[float] = field(default_factory=list)

    @property
    def db(self) -> Path:
        return self.home / "qci.db"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    state = Env(home=tmp_path / "store")
    monkeypatch.setenv("QCI_HOME", str(state.home))
    monkeypatch.setattr(backfill_service, "utc_now", lambda: NOW)
    monkeypatch.setattr(time, "sleep", state.pauses.append)
    yield state


def install(monkeypatch: pytest.MonkeyPatch, backend: HistoryBackend) -> StubFactory:
    factory = StubFactory(backend)
    monkeypatch.setattr(live, "create_service", factory)
    return factory


def fez(**kwargs: object) -> HistoryBackend:
    backend = HistoryBackend(STAMPS, **kwargs)  # type: ignore[arg-type]
    backend.name = DEVICE
    return backend


def backfill(*args: str, backend: str = DEVICE) -> Result:
    return CliRunner().invoke(app, ["snapshot", "backfill", "--backend", backend, *args])


def requested(backend: HistoryBackend) -> list[datetime]:
    return [call["datetime"] for call in backend.properties_calls]


def lookups(db: Path) -> list[tuple[str, str]]:
    """(capture_id, requested_before) of every stored lookup, through a read-only connection."""
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        rows = conn.execute("select capture_id, requested_before from snapshot_lookups")
        return [(str(a), str(b)) for a, b in rows]
    finally:
        conn.close()


# --- the grid -------------------------------------------------------------------------------


def test_default_grid_is_utc_midnights_newest_first() -> None:
    assert grid_times(NOW, 3, 24) == [day(0), day(1), day(2)]
    for at in grid_times(NOW, 365, 24):
        assert at.tzinfo is UTC and at.utcoffset() == timedelta(0)
        assert (at.hour, at.minute, at.second, at.microsecond) == (0, 0, 0, 0)


def test_grid_never_reaches_further_back_than_days() -> None:
    for days in (1, 3, 30, 365):
        for step in (1, 5, 24):
            times = grid_times(NOW, days, step)
            assert times == sorted(times, reverse=True)
            assert times[0] <= MIDNIGHT
            assert min(times) >= NOW - timedelta(days=days)
    assert len(grid_times(NOW, 365, 24)) == 365
    hourly = grid_times(NOW, 1, 1)
    assert hourly[0] == MIDNIGHT and hourly[-1] == datetime(2026, 10, 17, 22, tzinfo=UTC)


def test_grid_times_are_fixed_instants_across_days() -> None:
    today = set(grid_times(NOW, 10, 5))
    tomorrow = set(grid_times(NOW + timedelta(days=1), 10, 5))
    assert len(today & tomorrow) >= len(today) - 6
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    assert all((at - epoch) % timedelta(hours=5) == timedelta(0) for at in today | tomorrow)


# --- what is requested and stored ------------------------------------------------------------


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset is POSIX-only")
def test_the_client_receives_aware_utc_datetimes_under_two_timezones(
    tmp_path: Path, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[set[datetime | None], set[str]]] = []
    try:
        for index, tz in enumerate(("AAA+05", "BBB-05:30")):
            monkeypatch.setenv("TZ", tz)
            time.tzset()
            home = tmp_path / f"tz{index}"
            monkeypatch.setenv("QCI_HOME", str(home))
            backend = fez()
            install(monkeypatch, backend)
            result = backfill("--days", "2")
            assert result.exit_code == 0, result.stderr
            assert backend.properties_calls == [{"datetime": day(0)}, {"datetime": day(1)}]
            for call in backend.properties_calls:
                assert call["datetime"].tzinfo is UTC
                assert call["datetime"].utcoffset() == timedelta(0)
            repository = SqliteSnapshotRepository(home / "qci.db", read_only=True)
            try:
                assert repository.lookup_times("qiskit_ibm", DEVICE) == {day(0), day(1)}
                items = repository.list_snapshots()
                seen.append(
                    (
                        {i.calibrated_at for i in items},
                        {repository.get(i.snapshot_id).content_hash for i in items},
                    )
                )
            finally:
                repository.close()
    finally:
        monkeypatch.undo()
        time.tzset()
    assert seen[0] == seen[1]
    assert len(seen[0][1]) == 2


def test_a_lookup_is_labeled_and_stores_no_configuration(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = fez()
    install(monkeypatch, backend)
    result = backfill("--days", "1")
    assert result.exit_code == 0, result.stderr
    snapshot_id = result.stdout.split()[1]
    repository = SqliteSnapshotRepository(env.db, read_only=True)
    try:
        snap = repository.get(snapshot_id)
        captures = repository.captures(snapshot_id)
    finally:
        repository.close()
    assert snap.source is SnapshotSource.HISTORICAL_LOOKUP
    assert snap.provider_raw["configuration"] is None
    assert snap.calibrated_at == datetime(2026, 10, 17, 18, 30, tzinfo=UTC)
    assert snap.backend_version == "1.0.0"  # from the properties document itself
    assert [(c.method, c.requested_before) for c in captures] == [("historical_lookup", day(0))]
    db_bytes = env.db.read_bytes()
    for marker in (b"coupling_map", b"supported_instructions", b"n_qubits", b"online_date"):
        assert marker not in db_bytes  # present in the stub's configuration() only
    for sentinel in SENTINELS:
        assert sentinel.encode() not in db_bytes
    assert backend.properties_calls == [{"datetime": day(0)}]


def test_two_grid_times_returning_one_document_give_one_snapshot_and_two_lookups(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = HistoryBackend([datetime(2026, 10, 15, 12, tzinfo=UTC)])
    backend.name = DEVICE
    install(monkeypatch, backend)
    result = backfill("--days", "2")
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert [line.split()[-1] for line in lines] == ["new", "existing"]
    repository = SqliteSnapshotRepository(env.db, read_only=True)
    try:
        [item] = repository.list_snapshots()
        snap = repository.get(item.snapshot_id)
        captures = repository.captures(item.snapshot_id)
    finally:
        repository.close()
    assert item.capture_count == 2
    assert {c.requested_before for c in captures} == {day(0), day(1)}
    assert snap.capture_options == {"use_fractional_gates": False}
    assert snap.content_hash == hash_json(
        {
            "provider": snap.provider,
            "backend_name": snap.backend_name,
            "capture_options": snap.capture_options,
            "provider_raw": snap.provider_raw,
        }
    )


@pytest.mark.parametrize(
    ("returned", "shown"),
    [
        (day(1) + timedelta(minutes=5), (day(1) + timedelta(minutes=5)).isoformat()),
        (None, "none"),
    ],
    ids=["after_requested", "undated"],
)
def test_a_document_dated_after_the_request_or_undated_stores_nothing_and_stops(
    env: Env, monkeypatch: pytest.MonkeyPatch, returned: datetime | None, shown: str
) -> None:
    backend = fez(returned={day(1): returned})
    install(monkeypatch, backend)
    result = backfill("--days", "3")
    assert result.exit_code == 1
    assert DEVICE in result.stderr
    assert day(1).isoformat() in result.stderr and shown in result.stderr
    assert "Lookups stored before it are kept: 1." in result.stderr
    assert [b for _, b in lookups(env.db)] == [day(0).isoformat()]
    assert requested(backend) == [day(0), day(1)]


# --- limits, rejection and the store check ------------------------------------------------


@pytest.mark.parametrize(
    ("device", "days"),
    [(DEVICE, "366"), ("ibm_other", "1"), ("fake_fez", "1")],
    ids=["beyond_depth", "unlisted", "fake_name"],
)
def test_beyond_depth_unlisted_or_fake_exits_2_with_nothing_requested(
    env: Env, monkeypatch: pytest.MonkeyPatch, device: str, days: str
) -> None:
    factory = install(monkeypatch, fez())
    result = backfill("--days", days, backend=device)
    assert result.exit_code == 2
    assert "Nothing was requested." in result.stderr
    assert factory.calls == []
    assert not env.home.exists()


def test_every_verified_depth_is_365_days() -> None:
    assert dict(VERIFIED_LOOKUP_DEPTH_DAYS) == {
        "ibm_fez": 365,
        "ibm_kingston": 365,
        "ibm_marrakesh": 365,
    }


def test_simulators_and_fake_objects_exit_2_with_nothing_requested(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = fez(simulator=True)
    factory = install(monkeypatch, backend)
    result = backfill("--days", "1")
    assert result.exit_code == 2 and "simulator" in result.stderr
    assert len(factory.calls) == 1 and backend.properties_calls == []
    assert not env.home.exists()

    from qiskit_ibm_runtime.fake_provider import FakeFez

    factory.backend = FakeFez()  # untyped (Any) under mypy
    result = backfill("--days", "1")
    assert result.exit_code == 2 and "fake" in result.stderr
    assert not env.home.exists()


@pytest.mark.parametrize(
    "args",
    [
        ["--max-requests", "101"],
        ["--max-requests", "0"],
        ["--pause", "1.9"],
        ["--step-hours", "0"],
        ["--days", "0"],
    ],
    ids=lambda v: " ".join(v),
)
def test_option_limits_exit_2_with_nothing_requested(
    env: Env, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    factory = install(monkeypatch, fez())
    days = [] if "--days" in args else ["--days", "3"]
    result = backfill(*days, *args)
    assert result.exit_code == 2
    assert factory.calls == []
    assert not env.home.exists()


def test_default_cap_is_30_requests_with_a_10_second_pause_before_each(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = fez()
    install(monkeypatch, backend)
    result = backfill("--days", "40")
    assert result.exit_code == 0, result.stderr
    assert requested(backend) == [day(n) for n in range(30)]
    assert env.pauses == [10.0] * 30
    assert "grid times: 40; already stored: 0; pending: 40" in result.stderr
    assert "requested: 30; remaining: 10" in result.stderr
    assert "Re-run the same command to continue." in result.stderr
    assert len(lookups(env.db)) == 30


def test_explicit_cap_and_pause(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = fez()
    install(monkeypatch, backend)
    result = backfill("--days", "40", "--max-requests", "5", "--pause", "2.5")
    assert result.exit_code == 0, result.stderr
    assert len(backend.properties_calls) == 5
    assert env.pauses == [2.5] * 5


@pytest.mark.parametrize(
    "error",
    [
        RateLimitError("Too many requests", status_code=429),
        RuntimeError("wrapped"),
    ],
    ids=["http_429", "ibm_code_1202_in_chain"],
)
def test_the_first_too_many_requests_response_stops_with_nothing_retried(
    env: Env, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    if isinstance(error, RuntimeError):
        error.__cause__ = RateLimitError("'{\"errors\":[...]}'. Error code: 1202.")
    backend = fez(errors={3: error})
    install(monkeypatch, backend)
    result = backfill("--days", "10")
    assert result.exit_code == 1
    assert "too-many-requests" in result.stderr and "Nothing was retried." in result.stderr
    assert "Lookups stored before it are kept: 2." in result.stderr
    assert len(backend.properties_calls) == 3
    assert len(lookups(env.db)) == 2
    assert env.pauses == [10.0] * 3


def test_a_rerun_after_an_error_resumes_where_it_stopped(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = fez(errors={3: RuntimeError("connection reset")})
    install(monkeypatch, first)
    result = backfill("--days", "5")
    assert result.exit_code == 1
    assert "RuntimeError" in result.stderr
    assert requested(first) == [day(0), day(1), day(2)]

    second = fez()
    factory = install(monkeypatch, second)
    result = backfill("--days", "5")
    assert result.exit_code == 0, result.stderr
    assert "already stored: 2; pending: 3" in result.stderr
    assert requested(second) == [day(2), day(3), day(4)]
    assert len(factory.calls) == 1
    assert sorted(b for _, b in lookups(env.db)) == sorted(day(n).isoformat() for n in range(5))

    third = fez()
    factory = install(monkeypatch, third)
    before = env.db.read_bytes()
    result = backfill("--days", "5")
    assert result.exit_code == 0
    assert "Nothing to request." in result.stderr
    assert factory.calls == [] and third.properties_calls == []
    assert env.db.read_bytes() == before


def test_the_client_is_built_only_from_the_named_saved_account(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    factory = install(monkeypatch, fez())
    result = backfill("--days", "2", "--account", SENTINEL_ACCOUNT)
    assert result.exit_code == 0, result.stderr
    assert factory.calls == [((), {"name": SENTINEL_ACCOUNT})]
    assert factory.services[0].backend_calls == [((DEVICE,), {"use_fractional_gates": False})]
    for sentinel in SENTINELS:
        assert sentinel not in result.stdout + result.stderr + caplog.text


def test_a_too_many_requests_response_while_resolving_the_device_records_nothing(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = StubFactory(fez(), error=RateLimitError("slow down", status_code=429))
    monkeypatch.setattr(live, "create_service", factory)
    result = backfill("--days", "2")
    assert result.exit_code == 1
    assert "TooManyRequestsError" in result.stderr and "Nothing was recorded." in result.stderr
    assert not env.home.exists()


# --- reading and exporting backfilled data -----------------------------------------------


def test_show_prints_the_source_and_each_requested_before(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = HistoryBackend([datetime(2026, 10, 15, 12, tzinfo=UTC)])
    backend.name = DEVICE
    install(monkeypatch, backend)
    snapshot_id = backfill("--days", "2").stdout.split()[1]
    shown = CliRunner().invoke(app, ["snapshot", "show", snapshot_id])
    assert shown.exit_code == 0
    assert "source:         historical_lookup" in shown.stdout
    assert "historical lookups: 2" in shown.stdout
    assert f"requested_before={day(0).isoformat()}" in shown.stdout
    assert f"requested_before={day(1).isoformat()}" in shown.stdout
    assert "raw provider payloads: properties" in shown.stdout


def test_export_refuses_backfilled_data(
    tmp_path: Path, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live, "load_account_secrets", lambda name: [])
    install(monkeypatch, fez())
    snapshot_id = backfill("--days", "1").stdout.split()[1]
    path = tmp_path / "fixture.json"
    result = CliRunner().invoke(app, ["snapshot", "export", snapshot_id, "--fixture", str(path)])
    assert result.exit_code == 1
    assert "historical lookup data" in result.stderr and "Nothing was written." in result.stderr
    assert not path.exists()


def test_help_states_stamp_time_retries_and_limits() -> None:
    result = CliRunner().invoke(app, ["snapshot", "backfill", "--help"], terminal_width=200)
    text = " ".join(result.stdout.split())
    assert (
        "Backfilled history is documents by provider stamp time, not what a user would have "
        "seen at a given time" in text
    )
    assert "retry some 5xx responses" in text
    assert "too-many-requests response (HTTP 429 or IBM error code 1202)" in text
    assert "--max-requests" in text and "--pause" in text


def test_a_successful_run_states_the_stamp_time_note(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, fez())
    result = backfill("--days", "1")
    assert "note: Backfilled history is documents by provider stamp time" in result.stderr


# --- the adapter ----------------------------------------------------------------------------


def test_lookup_refuses_a_requested_time_with_another_offset() -> None:
    from datetime import timezone

    backend = fez()
    lookup = IbmHistoricalCalibrationSource(service_factory=StubFactory(backend)).open(DEVICE)
    with pytest.raises(ValueError, match="zero offset"):
        lookup.lookup(datetime(2026, 10, 18, tzinfo=timezone(timedelta(hours=2))))
    with pytest.raises(ValueError, match="zero offset"):
        lookup.lookup(datetime(2026, 10, 18))
    assert backend.properties_calls == []


def test_too_many_requests_is_detected_anywhere_in_the_chain() -> None:
    assert is_too_many_requests(RateLimitError("x", status_code=429))
    assert not is_too_many_requests(RateLimitError("x", status_code=500))
    outer = RuntimeError("outer")
    outer.__context__ = RateLimitError("... Error code: 1202.")
    assert is_too_many_requests(outer)
    backend = fez(errors={1: outer})
    lookup = IbmHistoricalCalibrationSource(service_factory=StubFactory(backend)).open(DEVICE)
    with pytest.raises(TooManyRequestsError):
        lookup.lookup(day(0))
