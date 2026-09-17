"""EREFS grading and histologic thresholds.

EREFS scores five endoscopic features of EoE: Edema, Rings, Exudates, Furrows,
and Stricture. The features do not share a range, and the ranges changed when a
severity grade was added to edema and furrows. Applying one uniform range would
silently admit impossible scores, and totals from the two gradings are not
comparable. Every stored score therefore carries its version, and totals are
computed here, per version, rather than stored.

PENDING CLINICAL CONFIRMATION
-----------------------------
Both of these need the clinical advisor's sign-off before M2 closes:

- The feature maxima below. "classic" follows the original grading (edema and
  furrows present or absent). "graded" adds a severity grade to both.
- The remission threshold of 15 eosinophils per high-power field. It is the
  consensus diagnostic and response cut-off, but it depends on the field area
  the pathologist used, which patients rarely know.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from eoehelp_api.models.enums import EosComparator, ErefsVersion, HistologyStatus

FEATURES = ("edema", "rings", "exudates", "furrows", "stricture")


@dataclass(frozen=True)
class ErefsScale:
    version: ErefsVersion
    label: str
    maxima: Mapping[str, int]

    @property
    def max_total(self) -> int:
        return sum(self.maxima.values())


SCALES: Mapping[ErefsVersion, ErefsScale] = MappingProxyType(
    {
        ErefsVersion.CLASSIC: ErefsScale(
            version=ErefsVersion.CLASSIC,
            label="Original grading (edema and furrows present or absent)",
            maxima=MappingProxyType(
                {"edema": 1, "rings": 3, "exudates": 2, "furrows": 1, "stricture": 1}
            ),
        ),
        ErefsVersion.GRADED: ErefsScale(
            version=ErefsVersion.GRADED,
            label="Severity grading (edema and furrows graded 0-2)",
            maxima=MappingProxyType(
                {"edema": 2, "rings": 3, "exudates": 2, "furrows": 2, "stricture": 1}
            ),
        ),
    }
)


def out_of_range(version: ErefsVersion, scores: Mapping[str, int | None]) -> list[str]:
    """The features whose score the given grading does not allow."""
    maxima = SCALES[version].maxima
    return [
        feature
        for feature in FEATURES
        if (value := scores.get(feature)) is not None and not 0 <= value <= maxima[feature]
    ]


def total(scores: Mapping[str, int | None]) -> int | None:
    """The sum of all five features, or None if any was not recorded.

    A partial sum would read as a lower score, not as a missing one, which is
    the wrong way round for a disease-activity measure.
    """
    values = [scores.get(feature) for feature in FEATURES]
    if any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


# --- histology ---------------------------------------------------------------

REMISSION_THRESHOLD_EOS_PER_HPF = 15


def classify_count(count: int, comparator: EosComparator) -> HistologyStatus:
    """Read one peak count against the threshold, respecting how it was stated.

    ">50" is certainly at or above 15; ">10" could be either. "<15" is certainly
    below; "<20" could be either. Saying "indeterminate" is the honest answer for
    those, and the report shows it as such rather than guessing.
    """
    threshold = REMISSION_THRESHOLD_EOS_PER_HPF
    if comparator is EosComparator.EXACT:
        return (
            HistologyStatus.BELOW_THRESHOLD
            if count < threshold
            else HistologyStatus.AT_OR_ABOVE_THRESHOLD
        )
    if comparator is EosComparator.GREATER_THAN:
        # ">14" means at least 15.
        return (
            HistologyStatus.AT_OR_ABOVE_THRESHOLD
            if count >= threshold - 1
            else HistologyStatus.INDETERMINATE
        )
    # "<15" means at most 14.
    return HistologyStatus.BELOW_THRESHOLD if count <= threshold else HistologyStatus.INDETERMINATE


def classify_procedure(statuses: Iterable[HistologyStatus]) -> HistologyStatus | None:
    """One reading for a whole scope, from its biopsy sites.

    EoE is patchy, so the peak site decides: any site at or above the threshold
    means the procedure is. It is below only if every site certainly is. None
    means no biopsies were reported, which is different from indeterminate.
    """
    readings = list(statuses)
    if not readings:
        return None
    if HistologyStatus.AT_OR_ABOVE_THRESHOLD in readings:
        return HistologyStatus.AT_OR_ABOVE_THRESHOLD
    if all(r is HistologyStatus.BELOW_THRESHOLD for r in readings):
        return HistologyStatus.BELOW_THRESHOLD
    return HistologyStatus.INDETERMINATE
