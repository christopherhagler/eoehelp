"""Database enums for this area.

Each is created as a native Postgres type. Adding a value later needs an
explicit ALTER TYPE in a migration, which is the intended friction: these
encode clinical and legal vocabulary that should not drift silently.
"""

import enum


class DrugClass(enum.StrEnum):
    """The classes actually used in EoE, not a general drug taxonomy.

    Kept coarse deliberately: the report groups by class, and research asks
    "were they on a topical steroid" rather than which brand.
    """

    PPI = "ppi"
    SWALLOWED_TOPICAL_CORTICOSTEROID = "swallowed_topical_corticosteroid"
    BIOLOGIC = "biologic"
    OTHER = "other"


class DoseStatus(enum.StrEnum):
    """Skipped is recorded, not inferred from absence.

    An absent dose is ambiguous — it may mean skipped, or it may mean the patient
    did not open the app. A deliberate skip is information, and the difference
    matters when a clinician is deciding whether a treatment failed or was never
    really taken.
    """

    TAKEN = "taken"
    SKIPPED = "skipped"
    DELAYED = "delayed"


class MedicationStopReason(enum.StrEnum):
    """Why a medication ended.

    Clinically the most informative field on the table: "stopped because it did
    not work" and "stopped because insurance refused it" lead to opposite next
    steps, and patients rarely remember which by the next appointment.
    """

    REMISSION = "remission"
    INEFFECTIVE = "ineffective"
    SIDE_EFFECTS = "side_effects"
    COST = "cost"
    INSURANCE = "insurance"
    PROVIDER_DIRECTED = "provider_directed"
    OTHER = "other"
