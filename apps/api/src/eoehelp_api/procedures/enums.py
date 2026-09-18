"""Database enums for this area.

Each is created as a native Postgres type. Adding a value later needs an
explicit ALTER TYPE in a migration, which is the intended friction: these
encode clinical and legal vocabulary that should not drift silently.
"""

import enum


class EndoscopyIndication(enum.StrEnum):
    """Why the scope was done, which changes how its findings are read.

    A diagnostic scope and a scope checking treatment response answer different
    questions, and a food-impaction scope is often done without biopsies.
    """

    DIAGNOSIS = "diagnosis"
    TREATMENT_RESPONSE = "treatment_response"
    FOOD_IMPACTION = "food_impaction"
    SURVEILLANCE = "surveillance"
    OTHER = "other"


class ErefsVersion(enum.StrEnum):
    """Which EREFS grading a set of sub-scores was recorded under.

    The sub-score ranges differ between gradings, so a score is meaningless
    without its version. See procedures/erefs.py for the ranges.
    """

    CLASSIC = "classic"
    GRADED = "graded"


class BiopsyLocation(enum.StrEnum):
    PROXIMAL = "proximal"
    MID = "mid"
    DISTAL = "distal"
    UNSPECIFIED = "unspecified"


class EosComparator(enum.StrEnum):
    """How a pathology report stated the count.

    Reports often say ">50" or "<15" rather than a number. Recording "50" as if
    it were exact would understate the first and invent precision in the second.
    """

    EXACT = "exact"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"


class HistologyStatus(enum.StrEnum):
    """A reading of a peak count against the remission threshold.

    Derived when read, never stored: the threshold is a clinical convention that
    may be refined, and history must not need rewriting when it is.
    """

    BELOW_THRESHOLD = "below_threshold"
    AT_OR_ABOVE_THRESHOLD = "at_or_above_threshold"
    INDETERMINATE = "indeterminate"


class DilatorType(enum.StrEnum):
    BALLOON = "balloon"
    BOUGIE = "bougie"
    UNKNOWN = "unknown"


class DilationComplication(enum.StrEnum):
    NONE = "none"
    CHEST_PAIN = "chest_pain"
    BLEEDING = "bleeding"
    PERFORATION = "perforation"
    OTHER = "other"
