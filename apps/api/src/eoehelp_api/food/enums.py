"""Database enums for this area.

Each is created as a native Postgres type. Adding a value later needs an
explicit ALTER TYPE in a migration, which is the intended friction: these
encode clinical and legal vocabulary that should not drift silently.
"""

import enum


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
