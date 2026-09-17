"""Database enums.

Each is created as a native Postgres type. Adding a value later requires an
explicit ALTER TYPE in a migration, which is the intended friction: these encode
clinical and legal vocabulary that should not drift silently.
"""

import enum


class UserRole(enum.StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    RESEARCHER = "researcher"
    ADMIN = "admin"


class UserStatus(enum.StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class SexAtBirth(enum.StrEnum):
    FEMALE = "female"
    MALE = "male"
    INTERSEX = "intersex"
    UNDISCLOSED = "undisclosed"


class ConsentType(enum.StrEnum):
    TERMS_OF_SERVICE = "terms_of_service"
    PRIVACY_POLICY = "privacy_policy"
    # Washington My Health My Data Act requires a separate, specific consumer
    # health data disclosure — it cannot be folded into the general privacy policy.
    CONSUMER_HEALTH_DATA = "consumer_health_data"
    RESEARCH_PARTICIPATION = "research_participation"


class ResearchScope(enum.StrEnum):
    SYMPTOMS = "symptoms"
    DIET = "diet"
    MEDICATIONS = "medications"
    ENDOSCOPY = "endoscopy"
    DEMOGRAPHICS = "demographics"


class AuditOutcome(enum.StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    ERROR = "error"


class DysphagiaSeverity(enum.StrEnum):
    """Graded by what the patient had to do about it, not by a 1-10 feeling.

    A self-reported intensity number is not comparable between patients or
    against a trial cohort. "Did it stick, and did you need help getting it down"
    is observable, and it is the distinction the DSQ itself draws.
    """

    NONE = "none"
    MILD_SLOW = "mild_slow"
    STUCK_SELF_RESOLVED = "stuck_self_resolved"
    STUCK_INTERVENTION = "stuck_intervention"


class CopingAction(enum.StrEnum):
    """What the patient did when food stuck.

    Recorded because it is the clearest signal of severity a patient can report
    reliably, and because the behavioural adaptations are what a
    gastroenterologist asks about and patients forget by the appointment.
    """

    DRANK_LIQUID = "drank_liquid"
    EXTRA_CHEWING = "extra_chewing"
    SPIT_OUT = "spit_out"
    LEFT_TABLE = "left_table"
    INDUCED_VOMIT = "induced_vomit"
    ER_VISIT = "er_visit"


class EntryMethod(enum.StrEnum):
    """Whether the entry was logged on the day it describes.

    Research weights same-day entries more heavily than recalled ones, and this
    is derived server-side from the patient's own timezone rather than trusted
    from the client.
    """

    SAME_DAY = "same_day"
    BACKFILL = "backfill"


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


class AllergenGroup(enum.StrEnum):
    """The groups elimination diets are built from.

    The first six are the six-food elimination diet (6FED) groups, split where the
    diet treats them as one — nuts into peanut and tree nut, seafood into fish and
    shellfish — so that a 4FED or 2FED is expressible without losing the finer
    grain. Sesame is here because US labelling added it in 2023, not because the
    EoE diets eliminate it.

    PENDING CLINICAL CONFIRMATION: the group assigned to each catalog ingredient
    (migration 0004) needs the clinical advisor's review before it drives any
    patient-facing insight.
    """

    MILK = "milk"
    WHEAT = "wheat"
    EGG = "egg"
    SOY = "soy"
    PEANUT = "peanut"
    TREE_NUT = "tree_nut"
    FISH = "fish"
    SHELLFISH = "shellfish"
    SESAME = "sesame"


class Meal(enum.StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"
