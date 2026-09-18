"""EREFS grading and the histologic threshold, as pure functions.

These decide what a clinician reads on the report, so every boundary is pinned.
"""

import importlib.util
from pathlib import Path

import pytest

from eoehelp_api.procedures import erefs
from eoehelp_api.procedures.enums import EosComparator, ErefsVersion, HistologyStatus

ABOVE = HistologyStatus.AT_OR_ABOVE_THRESHOLD
BELOW = HistologyStatus.BELOW_THRESHOLD
UNSURE = HistologyStatus.INDETERMINATE


class TestScales:
    def test_the_gradings_differ_only_where_they_should(self) -> None:
        classic = erefs.SCALES[ErefsVersion.CLASSIC].maxima
        graded = erefs.SCALES[ErefsVersion.GRADED].maxima
        assert {f for f in erefs.FEATURES if classic[f] != graded[f]} == {"edema", "furrows"}
        assert erefs.SCALES[ErefsVersion.CLASSIC].max_total == 8
        assert erefs.SCALES[ErefsVersion.GRADED].max_total == 10

    def test_a_graded_edema_score_is_out_of_range_for_classic(self) -> None:
        assert erefs.out_of_range(ErefsVersion.CLASSIC, {"edema": 2}) == ["edema"]
        assert erefs.out_of_range(ErefsVersion.GRADED, {"edema": 2}) == []
        assert erefs.out_of_range(ErefsVersion.GRADED, {"rings": 4, "stricture": 2}) == [
            "rings",
            "stricture",
        ]

    def test_the_migration_enforces_the_same_maxima(self) -> None:
        """The database check constraints are written out in migration 0005. If
        they and the service disagreed, one layer would accept what the other
        refuses."""
        path = Path(__file__).resolve().parents[1] / "alembic/versions/0005_procedures.py"
        spec = importlib.util.spec_from_file_location("migration_0005", path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for feature, classic, graded in module.EREFS_MAXIMA:
            assert erefs.SCALES[ErefsVersion.CLASSIC].maxima[feature] == classic
            assert erefs.SCALES[ErefsVersion.GRADED].maxima[feature] == graded


class TestTotal:
    def test_all_five_features_sum(self) -> None:
        scores = {"edema": 1, "rings": 2, "exudates": 1, "furrows": 1, "stricture": 0}
        assert erefs.total(scores) == 5

    def test_a_missing_feature_gives_no_total_rather_than_a_low_one(self) -> None:
        assert erefs.total({"edema": 1, "rings": 2, "exudates": 1, "furrows": 1}) is None


class TestCountClassification:
    @pytest.mark.parametrize(
        ("count", "comparator", "expected"),
        [
            (14, EosComparator.EXACT, BELOW),
            (15, EosComparator.EXACT, ABOVE),
            (0, EosComparator.EXACT, BELOW),
            # ">14" means at least 15; ">13" could be 14.
            (14, EosComparator.GREATER_THAN, ABOVE),
            (13, EosComparator.GREATER_THAN, UNSURE),
            (50, EosComparator.GREATER_THAN, ABOVE),
            # "<15" means at most 14; "<16" could be 15.
            (15, EosComparator.LESS_THAN, BELOW),
            (16, EosComparator.LESS_THAN, UNSURE),
            (5, EosComparator.LESS_THAN, BELOW),
        ],
    )
    def test_boundaries(
        self, count: int, comparator: EosComparator, expected: HistologyStatus
    ) -> None:
        assert erefs.classify_count(count, comparator) is expected


class TestProcedureClassification:
    def test_no_biopsies_is_not_the_same_as_indeterminate(self) -> None:
        assert erefs.classify_procedure([]) is None

    def test_any_site_at_or_above_decides_it(self) -> None:
        """EoE is patchy; one active site means active disease."""
        assert erefs.classify_procedure([BELOW, UNSURE, ABOVE]) is ABOVE

    def test_below_only_when_every_site_certainly_is(self) -> None:
        assert erefs.classify_procedure([BELOW, BELOW]) is BELOW
        assert erefs.classify_procedure([BELOW, UNSURE]) is UNSURE


class TestDeepRemission:
    @pytest.mark.parametrize(
        ("count", "comparator", "expected"),
        [
            (6, EosComparator.EXACT, BELOW),
            (7, EosComparator.EXACT, ABOVE),
            (0, EosComparator.EXACT, BELOW),
            # "<7" means at most 6; "<8" could be 7.
            (7, EosComparator.LESS_THAN, BELOW),
            (8, EosComparator.LESS_THAN, UNSURE),
            # ">6" means at least 7; ">5" could be 6.
            (6, EosComparator.GREATER_THAN, ABOVE),
            (5, EosComparator.GREATER_THAN, UNSURE),
        ],
    )
    def test_boundaries(
        self, count: int, comparator: EosComparator, expected: HistologyStatus
    ) -> None:
        assert erefs.classify_deep(count, comparator) is expected

    def test_a_count_can_be_a_response_without_being_deep_remission(self) -> None:
        """10 eos/hpf is below 15 but above 6: histologic response, not deep
        remission. Reporting only one threshold would hide that distinction."""
        assert erefs.classify_count(10, EosComparator.EXACT) is BELOW
        assert erefs.classify_deep(10, EosComparator.EXACT) is ABOVE
