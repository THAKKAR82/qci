"""RunSnapshotCompareService: a fake-backend run's stored calibration against one live snapshot.

Read-only: it never writes to either repository, and the comparison is never persisted.
"""

from collections.abc import Mapping

from qci.compare.run_snapshot import compare_run_to_snapshot
from qci.core.ports import RunRepository, RunSnapshotComparisonSupport, SnapshotRepository
from qci.domain.snapshot import RunSnapshotComparison


class RunSnapshotCompareService:
    def __init__(
        self,
        runs: RunRepository,
        snapshots: SnapshotRepository,
        supports: Mapping[str, RunSnapshotComparisonSupport],
    ) -> None:
        self._runs = runs
        self._snapshots = snapshots
        self._supports = dict(supports)

    def compare(self, run_id: str, snapshot_id: str) -> RunSnapshotComparison:
        """Raises ``RunNotFoundError`` or ``SnapshotNotFoundError`` for an unknown ID."""
        return compare_run_to_snapshot(
            self._runs.get(run_id), self._snapshots.get(snapshot_id), self._supports.get
        )
