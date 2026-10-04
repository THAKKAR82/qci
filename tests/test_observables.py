"""Compare-time observables: bitstring-to-(k, n) conversion, input rules, gate and identity."""

import pytest
from pydantic import ValidationError

from conftest import make_run, physical_bell_qasm, physical_run
from qci.adapters.qiskit_ibm.calibration import IbmPropertiesCalibrationReader
from qci.cli.render_compare import render_comparison
from qci.compare.observables import bitstring_set_counts, observables_hash
from qci.compare.proportions import newcombe_difference, wilson_interval
from qci.core.errors import InvalidObservableError
from qci.core.hashing import hash_json
from qci.domain.circuit import CircuitSummary
from qci.domain.comparison import (
    Comparison,
    ComparisonPolicy,
    ComparisonStatus,
    ObservableComparison,
    ObservableSpec,
)
from qci.domain.metric import EvidenceKind
from qci.domain.run import Run, RunError, RunStage, RunStatus
from qci.services.compare_service import CompareService, comparison_id
from qci.storage.sqlite import SqliteRunRepository

READERS = {"qiskit_ibm": IbmPropertiesCalibrationReader()}


def spec(name: str, *bits: str, **kwargs: str) -> ObservableSpec:
    return ObservableSpec(name=name, bitstrings=list(bits), **kwargs)


@pytest.fixture
def service(repo: SqliteRunRepository) -> CompareService:
    repo.save(physical_run("BASE", qasm3=physical_bell_qasm(1, 0)))  # 00: 52, 11: 48
    repo.save(
        physical_run(
            "CAND", qasm3=physical_bell_qasm(1, 0), counts={"c": {"00": 40, "11": 55, "01": 5}}
        )
    )
    repo.save(
        physical_run(
            "OTHERLOGIC",
            qasm3=physical_bell_qasm(1, 0),
            counts={"c": {"00": 50, "11": 50}},
        ).model_copy(
            update={
                "logical_circuit": CircuitSummary.model_validate(
                    {
                        **make_run().logical_circuit.model_dump(),
                        "qasm3": "OPENQASM 3.0; // different",
                    }
                )
            }
        )
    )
    repo.save(
        make_run(
            "FAIL",
            status=RunStatus.FAILED,
            error=RunError(stage=RunStage.RESOLVE_BACKEND, error_type="E", message="m"),
            backend=None,
            backend_snapshot=None,
            compilation=None,
            execution=None,
            result=None,
            metrics=[],
        )
    )
    return CompareService(repo, READERS)


# --- conversion: bitstring counts to (k, n) -------------------------------------------------


def test_bitstring_set_counts() -> None:
    counts = {"00": 52, "11": 40, "01": 8}
    assert bitstring_set_counts(counts, ["00", "11"]) == (92, 100)
    assert bitstring_set_counts(counts, ["01"]) == (8, 100)


def test_unobserved_bitstring_counts_as_zero() -> None:
    assert bitstring_set_counts({"00": 10}, ["11"]) == (0, 10)
    assert bitstring_set_counts({"00": 10}, ["00", "10"]) == (10, 10)


def test_conversion_returns_plain_ints_for_the_statistics() -> None:
    k, n = bitstring_set_counts({"00": 7, "11": 3}, ["11"])
    assert type(k) is int and type(n) is int


# --- spec input rules -----------------------------------------------------------------------


def test_bitstrings_are_sorted() -> None:
    assert spec("ghz", "11111", "00000").bitstrings == ["00000", "11111"]


@pytest.mark.parametrize(
    "bits",
    [["00", "00"], ["0a"], ["0 1"], [""], ["00", "111"], []],
)
def test_invalid_bitstrings_are_rejected(bits: list[str]) -> None:
    with pytest.raises(ValidationError):
        ObservableSpec(name="x", bitstrings=bits)


@pytest.mark.parametrize("name", ["", "1x", "a-b", "a b", "a=b"])
def test_names_must_be_identifiers(name: str) -> None:
    with pytest.raises(ValidationError):
        spec(name, "00")


def test_kind_and_bit_order_are_fixed() -> None:
    s = spec("bell", "00")
    assert (s.kind, s.bit_order) == ("bitstring_set_probability", "provider_counts_key")
    with pytest.raises(ValidationError):
        ObservableSpec.model_validate({"name": "x", "bitstrings": ["0"], "kind": "parity"})


def test_wrong_width_is_rejected_at_input(service: CompareService) -> None:
    with pytest.raises(InvalidObservableError, match="wrong width"):
        service.compare("BASE", "CAND", [spec("ghz", "00000")])


def test_unknown_register_is_rejected_at_input(service: CompareService) -> None:
    with pytest.raises(InvalidObservableError, match="register"):
        service.compare("BASE", "CAND", [spec("bell", "00", classical_register="meas")])


def test_duplicate_names_are_rejected(service: CompareService) -> None:
    with pytest.raises(InvalidObservableError, match="duplicate"):
        service.compare("BASE", "CAND", [spec("a", "00"), spec("a", "11")])


# --- values ---------------------------------------------------------------------------------


def test_observable_values_and_labels(service: CompareService) -> None:
    c = service.compare("BASE", "CAND", [spec("bell", "11", "00"), spec("odd", "01")])
    assert [o.spec.name for o in c.observables] == ["bell", "odd"]
    bell = c.observables[0]
    assert bell.status is ComparisonStatus.CHANGED
    assert bell.classical_register == "c"
    assert bell.baseline is not None and bell.candidate is not None
    assert bell.difference is not None
    assert (bell.baseline.k, bell.baseline.n) == (100, 100)
    assert (bell.candidate.k, bell.candidate.n) == (95, 100)
    assert bell.candidate.estimate.value == pytest.approx(0.95)
    assert bell.candidate.estimate.kind is EvidenceKind.CALCULATED
    lower, upper = wilson_interval(95, 100)
    assert (bell.candidate.wilson_lower.value, bell.candidate.wilson_upper.value) == (lower, upper)
    assert bell.candidate.wilson_lower.kind is EvidenceKind.STATISTICAL
    d, dl, du = newcombe_difference(100, 100, 95, 100)
    assert bell.difference.delta.value == d == pytest.approx(-0.05)
    assert bell.difference.delta.kind is EvidenceKind.CALCULATED
    assert bell.difference.newcombe_lower is not None
    assert bell.difference.newcombe_upper is not None
    assert bell.difference_unavailable_reason is None
    assert (bell.difference.newcombe_lower.value, bell.difference.newcombe_upper.value) == (dl, du)
    assert bell.difference.newcombe_upper.kind is EvidenceKind.STATISTICAL
    odd = c.observables[1]
    assert odd.baseline is not None and (odd.baseline.k, odd.baseline.n) == (0, 100)


def test_equal_estimates_are_unchanged(service: CompareService) -> None:
    c = service.compare("BASE", "BASE", [spec("bell", "00", "11")])
    assert c.observables[0].status is ComparisonStatus.UNCHANGED


# --- gate -----------------------------------------------------------------------------------


def test_failed_gate_makes_every_observable_not_comparable(service: CompareService) -> None:
    c = service.compare("BASE", "OTHERLOGIC", [spec("a", "00"), spec("b", "11")])
    assert c.distribution.status is ComparisonStatus.NOT_COMPARABLE
    for o in c.observables:
        assert o.status is ComparisonStatus.NOT_COMPARABLE
        assert o.reasons == c.distribution.reasons
        assert o.baseline is None and o.candidate is None and o.difference is None


def test_unavailable_distribution_makes_observables_unavailable(service: CompareService) -> None:
    c = service.compare("BASE", "FAIL", [spec("a", "00")])
    assert c.observables[0].status is ComparisonStatus.UNAVAILABLE
    assert c.observables[0].reasons == c.distribution.reasons


# --- identity -------------------------------------------------------------------------------


def test_observable_request_changes_the_comparison_id(service: CompareService) -> None:
    plain = service.compare("BASE", "CAND")
    bell = service.compare("BASE", "CAND", [spec("bell", "00", "11")])
    other = service.compare("BASE", "CAND", [spec("bell", "00")])
    renamed = service.compare("BASE", "CAND", [spec("ghz", "00", "11")])
    ids = {plain.comparison_id, bell.comparison_id, other.comparison_id, renamed.comparison_id}
    assert len(ids) == 4
    assert plain.observables == []


def test_same_request_gives_the_same_id_regardless_of_order(service: CompareService) -> None:
    a = service.compare("BASE", "CAND", [spec("x", "00", "11"), spec("y", "01")])
    b = service.compare("BASE", "CAND", [spec("y", "01"), spec("x", "11", "00")])
    assert a.comparison_id == b.comparison_id
    assert a.model_dump_json() == b.model_dump_json()


def test_comparison_id_includes_the_observables_hash() -> None:
    policy_hash = hash_json({"p": 1})
    request = [spec("bell", "00", "11")]
    assert comparison_id("B", "C", policy_hash, request) != comparison_id("B", "C", policy_hash)
    assert observables_hash(request) == observables_hash([spec("bell", "11", "00")])
    assert observables_hash([]) != observables_hash(request)


# --- shared-seed rule -----------------------------------------------------------------------

BELL = [spec("bell", "00", "11")]
CAND_COUNTS = {"c": {"00": 40, "11": 55, "01": 5}}


def seeded_pair(
    repo: SqliteRunRepository,
    seeds: tuple[int | None, int | None],
    simulators: tuple[bool, bool] = (True, True),
    logical: tuple[str, str] = (physical_bell_qasm(1, 0), physical_bell_qasm(1, 0)),
) -> tuple[str, str]:
    for run_id, seed, sim, counts in (
        ("SB", seeds[0], simulators[0], None),
        ("SC", seeds[1], simulators[1], CAND_COUNTS),
    ):
        repo.save(
            physical_run(
                run_id,
                qasm3=physical_bell_qasm(1, 0),
                seed_simulator=seed,
                is_simulator=sim,
                counts=counts,
            )
        )
    return "SB", "SC"


def assert_interval_withheld(o: ObservableComparison, seed: int) -> None:
    assert o.status is ComparisonStatus.CHANGED
    assert o.baseline is not None and o.candidate is not None and o.difference is not None
    assert (o.baseline.wilson_lower.value, o.baseline.wilson_upper.value) == wilson_interval(
        100, 100
    )
    assert (o.candidate.wilson_lower.value, o.candidate.wilson_upper.value) == wilson_interval(
        95, 100
    )
    assert o.difference.delta.value == pytest.approx(-0.05)
    assert o.difference.delta.kind is EvidenceKind.CALCULATED
    assert o.difference.newcombe_lower is None and o.difference.newcombe_upper is None
    assert o.difference_unavailable_reason == (
        f"both samples were drawn with the same simulator seed ({seed}), so they are not "
        "independent; the Newcombe interval assumes independent samples"
    )


def assert_interval_computed(o: ObservableComparison) -> None:
    assert o.difference is not None
    assert o.difference.newcombe_lower is not None and o.difference.newcombe_upper is not None
    _, lower, upper = newcombe_difference(100, 100, 95, 100)
    assert (o.difference.newcombe_lower.value, o.difference.newcombe_upper.value) == (
        lower,
        upper,
    )
    assert o.difference_unavailable_reason is None


def test_shared_seed_withholds_only_the_difference_interval(repo: SqliteRunRepository) -> None:
    b, c = seeded_pair(repo, (7, 7))
    comparison = CompareService(repo, READERS).compare(b, c, BELL)
    assert comparison.distribution.sampling_floor is None
    assert_interval_withheld(comparison.observables[0], 7)


def test_policy_flag_off_restores_the_difference_interval(repo: SqliteRunRepository) -> None:
    b, c = seeded_pair(repo, (7, 7))
    policy = ComparisonPolicy(sampling_floor_requires_distinct_simulator_seeds=False)
    comparison = CompareService(repo, READERS, policy).compare(b, c, BELL)
    assert_interval_computed(comparison.observables[0])


@pytest.mark.parametrize(
    ("seeds", "simulators"),
    [
        ((7, 8), (True, True)),
        ((None, None), (True, True)),
        ((7, None), (True, True)),
        ((7, 7), (False, False)),
        ((7, 7), (True, False)),
    ],
    ids=["different-seeds", "both-unseeded", "one-unseeded", "not-simulators", "one-simulator"],
)
def test_difference_interval_is_computed_when_the_guard_does_not_apply(
    repo: SqliteRunRepository,
    seeds: tuple[int | None, int | None],
    simulators: tuple[bool, bool],
) -> None:
    b, c = seeded_pair(repo, seeds, simulators)
    assert_interval_computed(CompareService(repo, READERS).compare(b, c, BELL).observables[0])


def test_failed_gate_leaves_the_unavailable_reason_null(repo: SqliteRunRepository) -> None:
    repo.save(physical_run("SB", qasm3=physical_bell_qasm(1, 0), seed_simulator=7))
    repo.save(
        physical_run(
            "SC",
            qasm3=physical_bell_qasm(1, 0),
            seed_simulator=7,
            logical_qasm3="OPENQASM 3.0; // different",
        )
    )
    o = CompareService(repo, READERS).compare("SB", "SC", BELL).observables[0]
    assert o.status is ComparisonStatus.NOT_COMPARABLE
    assert o.difference is None and o.difference_unavailable_reason is None


def test_withheld_interval_is_rendered_with_both_runs(repo: SqliteRunRepository) -> None:
    b, c = seeded_pair(repo, (7, 7))
    text = render_comparison(CompareService(repo, READERS).compare(b, c, BELL))
    section = text.split("Observables:")[1].split("Limitations:")[0]
    assert "baseline : 100/100 = 1.0000" in section
    assert "candidate: 95/100 = 0.9500" in section
    assert "delta: -0.0500" in section
    assert "Newcombe interval unavailable: both samples were drawn with the same simulator " in (
        section
    )
    assert "Newcombe [" not in section


# --- width check behind a failed gate, and empty counts -------------------------------------


def test_wrong_width_is_rejected_even_when_the_gate_fails(service: CompareService) -> None:
    with pytest.raises(InvalidObservableError, match="wrong width"):
        service.compare("BASE", "OTHERLOGIC", [spec("ghz", "00000")])


def test_width_is_not_checked_when_a_side_has_no_counts(service: CompareService) -> None:
    c = service.compare("BASE", "FAIL", [spec("ghz", "00000")])
    assert c.observables[0].status is ComparisonStatus.UNAVAILABLE


def with_empty_counts(run: Run) -> Run:
    assert run.result is not None
    return run.model_copy(update={"result": run.result.model_copy(update={"counts": {"c": {}}})})


def test_empty_counts_make_the_observable_unavailable(repo: SqliteRunRepository) -> None:
    # A shared seed skips the TVD sampling floor, which itself rejects empty counts, so the
    # observable code is reached with n = 0 on one side.
    repo.save(physical_run("BASE", qasm3=physical_bell_qasm(1, 0), seed_simulator=7))
    repo.save(
        with_empty_counts(physical_run("EMPTY", qasm3=physical_bell_qasm(1, 0), seed_simulator=7))
    )
    c: Comparison = CompareService(repo, READERS).compare("BASE", "EMPTY", BELL)
    assert c.distribution.status is not ComparisonStatus.NOT_COMPARABLE
    o = c.observables[0]
    assert o.status is ComparisonStatus.UNAVAILABLE
    assert o.reasons == ["candidate run has no counts in register 'c'"]
    assert o.baseline is None and o.difference is None
