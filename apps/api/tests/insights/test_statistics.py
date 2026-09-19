"""The food-pattern statistics against hand computation and brute force."""

import itertools
import math

import pytest

from eoehelp_api.insights import statistics


def brute_force_p(blocks: list[tuple[list[int], list[int]]]) -> float:
    """Every combination of per-block shifts, counted directly."""
    observed = sum(sum(e * y for e, y in zip(ex, out, strict=True)) for ex, out in blocks)
    at_least = total = 0
    for shifts in itertools.product(*(range(len(ex)) for ex, _ in blocks)):
        value = 0
        for (ex, out), s in zip(blocks, shifts, strict=True):
            n = len(ex)
            value += sum(ex[(i + s) % n] * out[i] for i in range(n))
        total += 1
        at_least += value >= observed
    return at_least / total


class TestShiftTest:
    @pytest.mark.parametrize(
        "blocks",
        [
            [([1, 1, 0, 0, 0], [1, 1, 0, 0, 1])],
            [([1, 0, 1, 0], [1, 0, 1, 0]), ([0, 1, 1, 0, 0, 1], [0, 1, 1, 0, 0, 0])],
            [([1, 1, 1, 0], [0, 0, 0, 1]), ([1, 0, 0], [1, 0, 0]), ([0, 1], [1, 1])],
        ],
    )
    def test_the_exact_distribution_matches_brute_force(self, blocks) -> None:
        assert statistics.shift_test(blocks) == pytest.approx(brute_force_p(blocks))

    def test_the_unshifted_alignment_is_part_of_the_null(self) -> None:
        """A single perfectly aligned block can do no better than 1/n. Leaving
        the observed alignment out of the null would report 0 instead."""
        assert statistics.shift_test([([1, 0, 0, 0], [1, 0, 0, 0])]) == pytest.approx(0.25)

    def test_blocks_with_nothing_to_compare_do_not_move_the_answer(self) -> None:
        informative = ([1, 1, 0, 0, 0], [1, 1, 0, 0, 1])
        constant_exposure = ([1, 1, 1], [1, 0, 1])
        constant_outcome = ([1, 0, 1], [0, 0, 0])
        assert statistics.shift_test(
            [informative, constant_exposure, constant_outcome]
        ) == pytest.approx(statistics.shift_test([informative]))

    def test_no_blocks_is_no_evidence(self) -> None:
        assert statistics.shift_test([]) == 1.0


class TestMantelHaenszel:
    def test_matches_a_hand_computed_two_block_example(self) -> None:
        # Block 1: exposed 3 of 4 symptom, unexposed 1 of 4.
        # Block 2: exposed 1 of 2 symptom, unexposed 0 of 4.
        blocks = [
            ([1, 1, 1, 1, 0, 0, 0, 0], [1, 1, 1, 0, 1, 0, 0, 0]),
            ([1, 1, 0, 0, 0, 0], [1, 0, 0, 0, 0, 0]),
        ]
        rd = statistics.mantel_haenszel_rd(blocks)
        assert rd is not None
        # Weights n1*n0/n: 4*4/8 = 2 and 2*4/6 = 4/3.
        # Numerator (a*n0 - c*n1)/n: (3*4 - 1*4)/8 = 1 and (1*4 - 0*2)/6 = 2/3.
        assert rd.estimate == pytest.approx((1 + 2 / 3) / (2 + 4 / 3))
        # Sato: P = sum (n1^2 c - n0^2 a + n1 n0 (n0 - n1)/2) / n^2,
        #       Q = sum (a (n0 - c) + c (n1 - a)) / (2n).
        p_term = (16 * 1 - 16 * 3 + 0) / 64 + (4 * 0 - 16 * 1 + 8 * 2 / 2) / 36
        q_term = (3 * 3 + 1 * 1) / 16 + (1 * 4 + 0) / 12
        weight = 2 + 4 / 3
        assert rd.variance == pytest.approx((rd.estimate * p_term + q_term) / weight**2)
        assert (rd.exposed_days, rd.unexposed_days) == (6, 8)

    def test_uninformative_blocks_are_left_out_entirely(self) -> None:
        only_exposed = ([1, 1, 1], [1, 1, 0])
        mixed = ([1, 0, 1, 0], [1, 0, 0, 0])
        with_extra = statistics.mantel_haenszel_rd([mixed, only_exposed])
        alone = statistics.mantel_haenszel_rd([mixed])
        assert with_extra == alone

    def test_no_informative_block_gives_no_estimate(self) -> None:
        assert statistics.mantel_haenszel_rd([([1, 1], [1, 0]), ([0, 0], [0, 1])]) is None

    def test_the_upper_bound_inflates_the_standard_error(self) -> None:
        rd = statistics.RiskDifference(
            estimate=0.1, variance=0.01, exposed_days=8, unexposed_days=8
        )
        assert rd.upper_bound(1.0) == pytest.approx(0.1 + statistics.Z_95 * 0.1)
        assert rd.upper_bound(1.7) == pytest.approx(0.1 + statistics.Z_95 * 0.1 * 1.7)
        assert math.isclose(statistics.Z_95, 1.6448536, rel_tol=1e-7)


class TestBenjaminiHochberg:
    def test_matches_a_worked_example(self) -> None:
        # Sorted: 0.005, 0.01, 0.03, 0.04 with m = 4. Raw: 0.02, 0.02, 0.04, 0.04,
        # already monotone.
        assert statistics.benjamini_hochberg([0.01, 0.04, 0.03, 0.005]) == pytest.approx(
            [0.02, 0.04, 0.04, 0.02]
        )

    def test_q_values_are_monotone_in_p_and_never_exceed_one(self) -> None:
        q = statistics.benjamini_hochberg([0.9, 0.5, 0.95, 0.2])
        assert q == pytest.approx([0.95, 0.95, 0.95, 0.8])
        assert max(q) <= 1.0

    def test_an_empty_family(self) -> None:
        assert statistics.benjamini_hochberg([]) == []
