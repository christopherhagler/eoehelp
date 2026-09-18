"""Database enums for this area.

Each is created as a native Postgres type. Adding a value later needs an
explicit ALTER TYPE in a migration, which is the intended friction: these
encode clinical and legal vocabulary that should not drift silently.
"""

import enum


class DysphagiaRelief(enum.StrEnum):
    """DSQ question 3: what the patient had to do to get relief.

    Asked about the most difficult episode of the day, as a single choice, and
    scored 0-4 in this order. The wording and the scoring follow the published
    instrument (Dellon et al., Aliment Pharmacol Ther 2013); a bespoke severity
    scale would produce a number no one can compare with a trial.
    """

    CLEARED_ON_ITS_OWN = "cleared_on_its_own"
    DRANK_LIQUID = "drank_liquid"
    COUGHED_OR_GAGGED = "coughed_or_gagged"
    VOMITED = "vomited"
    SOUGHT_MEDICAL_ATTENTION = "sought_medical_attention"
