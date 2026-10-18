"""BackfillService: historical calibration lookups on a fixed UTC grid (ADR 0008, sections 4-6).

Depends only on ports. One invocation is one bounded run: no daemon, scheduler, polling or
retries. Each lookup is validated, then stored in its own transaction, so everything stored
before an error is kept. Grid times already stored as lookups are skipped without a request,
so re-running the same command continues where the last one stopped.

Backfilled history is documents by provider stamp time, not what a user would have seen at a
given time: a document stamped before a requested time can have been published after it.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from qci.core.errors import BackfillRejectedError, LookupRejectedError
from qci.core.ports import HistoricalCalibrationSource, HistoricalLookup, SnapshotRepository
from qci.services.snapshot_service import CaptureOutcome, SnapshotService

DEFAULT_STEP_HOURS = 24
MIN_STEP_HOURS = 1
DEFAULT_MAX_REQUESTS = 30
MAX_REQUESTS_LIMIT = 100
DEFAULT_PAUSE_SECONDS = 10.0
MIN_PAUSE_SECONDS = 2.0

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def utc_now() -> datetime:
    return datetime.now(UTC)


def grid_times(now: datetime, days: int, step_hours: int) -> list[datetime]:
    """The requested times, newest first, as aware UTC datetimes with a zero offset.

    Every instant at a whole multiple of ``step_hours`` since 1970-01-01T00:00Z that is at or
    before the most recent UTC midnight at or before ``now``, and no more than ``days`` days
    before ``now``. With the default step of 24 hours that is one UTC midnight per day. The
    times are fixed instants, so a re-run requests the same times.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    if step_hours < MIN_STEP_HOURS:
        raise ValueError(f"step_hours must be at least {MIN_STEP_HOURS}")
    now = now.astimezone(UTC)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    oldest = now - timedelta(days=days)
    step = timedelta(hours=step_hours)
    at = _EPOCH + ((midnight - _EPOCH) // step) * step
    times: list[datetime] = []
    while at >= oldest:
        times.append(at)
        at -= step
    return times


@dataclass(frozen=True)
class BackfillPlan:
    provider: str
    backend_name: str
    verified_depth_days: int
    grid: list[datetime]
    """Every grid time, newest first."""
    pending: list[datetime]
    """Grid times with no stored lookup yet, newest first."""

    @property
    def already_stored(self) -> int:
        return len(self.grid) - len(self.pending)


@dataclass(frozen=True)
class LookupResult:
    requested_before: datetime
    outcome: CaptureOutcome


@dataclass(frozen=True)
class BackfillReport:
    requested: int
    remaining: int
    """Pending grid times not requested in this invocation."""


class BackfillService:
    def __init__(
        self,
        source: HistoricalCalibrationSource,
        *,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._source = source
        self._sleep = sleep or time.sleep
        self._clock = clock or utc_now

    def plan(
        self, repository: SnapshotRepository, backend_name: str, days: int, step_hours: int
    ) -> BackfillPlan:
        """Check the request against the verified depth and list the pending grid times.
        Requests nothing. Raises ``BackfillRejectedError``."""
        depth = self._source.verified_depth_days(backend_name)
        if depth is None:
            raise BackfillRejectedError(
                f"{backend_name!r} has no verified historical lookup depth; it is not "
                "backfilled. Nothing was requested."
            )
        if days < 1 or days > depth:
            raise BackfillRejectedError(
                f"--days {days} is outside 1 to {depth}, the verified lookup depth of "
                f"{backend_name!r}. Nothing was requested."
            )
        if step_hours < MIN_STEP_HOURS:
            raise BackfillRejectedError(
                f"--step-hours must be at least {MIN_STEP_HOURS}. Nothing was requested."
            )
        grid = grid_times(self._clock(), days, step_hours)
        stored = repository.lookup_times(self._source.provider, backend_name)
        return BackfillPlan(
            provider=self._source.provider,
            backend_name=backend_name,
            verified_depth_days=depth,
            grid=grid,
            pending=[at for at in grid if at not in stored],
        )

    def open(self, plan: BackfillPlan) -> HistoricalLookup:
        return self._source.open(plan.backend_name)

    def run(
        self,
        repository: SnapshotRepository,
        lookup: HistoricalLookup,
        plan: BackfillPlan,
        *,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        pause_seconds: float = DEFAULT_PAUSE_SECONDS,
        on_result: Callable[[LookupResult], None] = lambda result: None,
    ) -> BackfillReport:
        """Request up to ``max_requests`` pending grid times, newest first, pausing
        ``pause_seconds`` before each request. The first error stops the run and propagates;
        nothing is retried, and every lookup stored before it is kept."""
        if not 1 <= max_requests <= MAX_REQUESTS_LIMIT:
            raise BackfillRejectedError(
                f"--max-requests must be between 1 and {MAX_REQUESTS_LIMIT}"
            )
        if pause_seconds < MIN_PAUSE_SECONDS:
            raise BackfillRejectedError(f"--pause must be at least {MIN_PAUSE_SECONDS:g} s")
        recorder = SnapshotService(repository)
        batch = plan.pending[:max_requests]
        for requested_before in batch:
            self._sleep(pause_seconds)
            captured = lookup.lookup(requested_before)
            stamp = captured.calibrated_at
            if (
                captured.requested_before != requested_before
                or stamp is None
                or (stamp > requested_before)
            ):
                returned = stamp.isoformat() if stamp is not None else "none"
                raise LookupRejectedError(
                    f"{plan.backend_name}: the lookup for requested_before "
                    f"{requested_before.isoformat()} returned a document stamped {returned}, "
                    "which is missing or after the requested time. Nothing was stored for "
                    "this request."
                )
            on_result(LookupResult(requested_before, recorder.record(captured)))
        return BackfillReport(requested=len(batch), remaining=len(plan.pending) - len(batch))
