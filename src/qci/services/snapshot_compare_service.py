"""SnapshotCompareService: footprint-scoped comparison of two stored calibration snapshots.

Read-only: it never writes to either repository, and the comparison is never persisted.
"""

from collections.abc import Mapping

from qci.compare.snapshots import compare_snapshots
from qci.core.ports import RunRepository, SnapshotComparisonSupport, SnapshotRepository
from qci.domain.snapshot import SnapshotComparison


class SnapshotCompareService:
    def __init__(
        self,
        runs: RunRepository,
        snapshots: SnapshotRepository,
        supports: Mapping[str, SnapshotComparisonSupport],
    ) -> None:
        self._runs = runs
        self._snapshots = snapshots
        self._supports = dict(supports)

    def compare(
        self,
        baseline_snapshot_id: str,
        candidate_snapshot_id: str,
        footprint_run_id: str,
        *,
        allow_footprint_backend_mismatch: bool = False,
    ) -> SnapshotComparison:
        """Raises ``SnapshotNotFoundError`` or ``RunNotFoundError`` for an unknown ID."""
        return compare_snapshots(
            self._snapshots.get(baseline_snapshot_id),
            self._snapshots.get(candidate_snapshot_id),
            self._runs.get(footprint_run_id),
            self._supports.get,
            allow_footprint_backend_mismatch=allow_footprint_backend_mismatch,
        )
