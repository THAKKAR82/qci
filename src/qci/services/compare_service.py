"""CompareService: directional comparison of two stored runs (baseline -> candidate).

Read-only: it never writes to the repository. It reports what changed; it never judges better
or worse and never attributes cause.
"""

from collections.abc import Mapping, Sequence

from qci.compare.distribution import SAMPLING_FLOOR_CAVEATS, compare_distributions
from qci.compare.footprint import footprint_for_run
from qci.compare.hardware import compare_footprints, compare_hardware
from qci.compare.observables import compare_observables, observables_hash
from qci.compare.sampling import seed_from_comparison_id
from qci.compare.sections import (
    compare_backend,
    compare_compilation,
    compare_environment,
    compare_execution,
    compare_logical_circuit,
    compare_source,
)
from qci.core.hashing import hash_json
from qci.core.ports import CalibrationReader, RunRepository
from qci.domain.comparison import Comparison, ComparisonPolicy, ComparisonStatus, ObservableSpec

ENGINE_VERSION = "qci.compare.engine.4"
"""Engine 4 adds compare-time observables and includes their request in ``comparison_id``."""

LIMITATIONS = [
    "This comparison reports what differs between the baseline and candidate runs.",
    "It makes no regression, improvement, better/worse or pass/fail judgment.",
    "It makes no causal attribution: a difference listed in one section is not evidence that "
    "it caused a difference in another.",
    "TVD and Hellinger distance are empirical point estimates; seeded or repeated runs can "
    "differ by sampling noise alone.",
    "TVD has a sampling floor when the distributions are comparable: null TVD quantiles and a "
    "Monte Carlo p-value under H0 that both runs sampled one shared distribution, at the "
    "observed shot counts. Hellinger distance still has no sampling floor.",
    *(f"Sampling floor caveat: {caveat}" for caveat in SAMPLING_FLOOR_CAVEATS),
    "The TVD sampling floor is not computed when both runs were simulated with the same "
    "simulator seed: their samples are not independent, and the floor assumes independent "
    "samples.",
    "A changed result distribution means the observed empirical (sampled) distributions "
    "differ. It does not establish that the underlying probability distribution changed, nor "
    "that the difference is statistically significant.",
    "Relevant hardware means calibration data for the physical resources the workload actually "
    "used. It does not mean a parameter is known to affect workload performance, nor that a "
    "calibration change caused any result change.",
    "Hardware calibration is compared only for physical resources identical on both sides.",
    "Observable intervals (Wilson for each run, Newcombe for the difference) describe sampling "
    "uncertainty at the observed shot counts, assuming independent shots. They are not "
    "verdicts, and no multiple-comparison correction is applied across observables. The "
    "Newcombe interval is not computed when both runs were simulated with the same simulator "
    "seed, because the samples are then not independent.",
]

_INCOMPLETE = {
    ComparisonStatus.UNAVAILABLE,
    ComparisonStatus.NOT_COMPARABLE,
    ComparisonStatus.PARTIALLY_COMPARABLE,
}


def comparison_id(
    baseline_run_id: str,
    candidate_run_id: str,
    policy_hash: str,
    observables: Sequence[ObservableSpec] = (),
) -> str:
    return hash_json(
        {
            "baseline_run_id": baseline_run_id,
            "candidate_run_id": candidate_run_id,
            "engine_version": ENGINE_VERSION,
            "observables_hash": observables_hash(observables),
            "policy_hash": policy_hash,
        }
    )


class CompareService:
    def __init__(
        self,
        repository: RunRepository,
        calibration_readers: Mapping[str, CalibrationReader],
        policy: ComparisonPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._readers = dict(calibration_readers)
        self._policy = policy or ComparisonPolicy()

    def compare(
        self,
        baseline_run_id: str,
        candidate_run_id: str,
        observables: Sequence[ObservableSpec] = (),
    ) -> Comparison:
        baseline = self._repository.get(baseline_run_id)
        candidate = self._repository.get(candidate_run_id)
        policy_hash = hash_json(self._policy)
        cid = comparison_id(baseline.run_id, candidate.run_id, policy_hash, observables)

        b_fp, c_fp = footprint_for_run(baseline), footprint_for_run(candidate)
        source = compare_source(baseline, candidate)
        environment = compare_environment(baseline, candidate)
        logical_circuit = compare_logical_circuit(baseline, candidate)
        compilation = compare_compilation(baseline, candidate)
        execution = compare_execution(baseline, candidate)
        backend = compare_backend(baseline, candidate)
        footprint = compare_footprints(b_fp, c_fp)
        hardware = compare_hardware(baseline, candidate, b_fp, c_fp, self._readers.get)
        distribution = compare_distributions(
            baseline, candidate, b_fp, c_fp, self._policy, seed=seed_from_comparison_id(cid)
        )
        observable_comparisons = compare_observables(
            observables, baseline, candidate, distribution, self._policy
        )

        statuses = {
            source.status,
            environment.status,
            logical_circuit.status,
            compilation.status,
            execution.status,
            backend.status,
            footprint.status,
            hardware.status,
            distribution.status,
            *(o.status for o in observable_comparisons),
        }
        if statuses & _INCOMPLETE:
            overall = ComparisonStatus.PARTIALLY_COMPARABLE
        elif ComparisonStatus.CHANGED in statuses:
            overall = ComparisonStatus.CHANGED
        else:
            overall = ComparisonStatus.UNCHANGED

        return Comparison(
            comparison_id=cid,
            engine_version=ENGINE_VERSION,
            policy=self._policy,
            policy_hash=policy_hash,
            baseline_run_id=baseline.run_id,
            candidate_run_id=candidate.run_id,
            status=overall,
            baseline_footprint=b_fp,
            candidate_footprint=c_fp,
            baseline_counts=baseline.result.counts if baseline.result else None,
            candidate_counts=candidate.result.counts if candidate.result else None,
            limitations=LIMITATIONS,
            source=source,
            environment=environment,
            logical_circuit=logical_circuit,
            compilation=compilation,
            execution=execution,
            backend=backend,
            footprint=footprint,
            hardware=hardware,
            distribution=distribution,
            observables=observable_comparisons,
        )
