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


class EliminationGroup(enum.StrEnum):
    """Groups that elimination-diet protocols remove but labelling law does not name.

    The 2-4-6 step-up protocol's first step removes milk and every
    gluten-containing cereal (wheat, barley, rye), and the four-food diet in
    its Spanish form removes all legumes rather than soy alone. Neither is one
    of the nine allergen groups, so each is detected separately.

    PENDING CLINICAL CONFIRMATION with the rest of the classifier rules.
    """

    GLUTEN_CEREALS = "gluten_cereals"
    LEGUMES = "legumes"


class Meal(enum.StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


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
    without its version. See services/erefs.py for the ranges.
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


class FoodDataSource(enum.StrEnum):
    OPEN_FOOD_FACTS = "open_food_facts"
    USDA_FDC = "usda_fdc"


class IngredientProvenance(enum.StrEnum):
    """Who says this ingredient was in the food.

    ``label`` comes from a product's printed ingredient list. ``patient`` is the
    patient's own account, whether picked from the catalog or typed. An analysis
    can weigh them differently; a label is evidence, a recollection is testimony.
    """

    LABEL = "label"
    PATIENT = "patient"
