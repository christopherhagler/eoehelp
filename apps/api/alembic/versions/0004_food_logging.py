"""Food logging: the ingredient catalog, patient ingredients, and logged foods.

Hand-written like its predecessors, for the same reasons: autogenerate cannot
express row-level security or grants, and grants do not reach tables created
after them.

The catalog is seeded here, as the medication catalog was, so the foreign key
from logged ingredients can never dangle and a fresh database is usable at once.
The data is written out in this file rather than imported from application code:
a migration must produce the same result forever, and application modules change.

Revision ID: 0004_food_logging
Revises: 0003_medications
Create Date: 2026-09-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_food_logging"
down_revision: str | None = "0003_medications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = ("custom_ingredients", "food_log_items", "food_log_item_ingredients")

ALLERGEN_GROUPS = (
    "milk",
    "wheat",
    "egg",
    "soy",
    "peanut",
    "tree_nut",
    "fish",
    "shellfish",
    "sesame",
)

# (code, name, allergen groups, lower-case aliases)
#
# Plain ingredients, plus a few staples patients think of as ingredients (bread,
# pasta) because forcing "wheat flour, water, yeast" for every sandwich is how
# food logging gets abandoned. Where a staple usually but not always contains a
# group, it is tagged with the group that defines it and nothing else.
#
# PENDING CLINICAL CONFIRMATION: the group assignments need the clinical
# advisor's review before they drive any patient-facing insight. Two known
# judgement calls: molluscs are grouped with crustaceans as "shellfish", as the
# six-food elimination diet does, although US labelling law covers only
# crustaceans; and coconut is not a tree nut, following the FDA's 2025 guidance.
CATALOG: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = [
    # Milk
    ("milk", "Milk", ("milk",), ("cow's milk", "whole milk", "skim milk", "dairy")),
    ("butter", "Butter", ("milk",), ()),
    ("ghee", "Ghee", ("milk",), ("clarified butter",)),
    ("cheese", "Cheese", ("milk",), ("cheddar", "mozzarella", "parmesan")),
    ("cream", "Cream", ("milk",), ("heavy cream", "sour cream", "creme fraiche")),
    ("cream_cheese", "Cream cheese", ("milk",), ()),
    ("yogurt", "Yogurt", ("milk",), ("yoghurt", "greek yogurt")),
    ("ice_cream", "Ice cream", ("milk",), ()),
    ("whey", "Whey", ("milk",), ("whey protein",)),
    ("casein", "Casein", ("milk",), ("caseinate",)),
    ("goat_milk", "Goat's milk", ("milk",), ("goat cheese",)),
    ("milk_chocolate", "Milk chocolate", ("milk",), ()),
    # Wheat
    ("wheat_flour", "Wheat flour", ("wheat",), ("flour", "all-purpose flour", "white flour")),
    ("whole_wheat", "Whole wheat", ("wheat",), ("wholemeal", "whole wheat flour")),
    ("bread", "Bread", ("wheat",), ("toast", "sandwich bread")),
    ("pasta", "Pasta", ("wheat",), ("spaghetti", "macaroni", "noodles")),
    ("couscous", "Couscous", ("wheat",), ()),
    ("semolina", "Semolina", ("wheat",), ("durum",)),
    ("bulgur", "Bulgur", ("wheat",), ("bulgar",)),
    ("spelt", "Spelt", ("wheat",), ()),
    ("farro", "Farro", ("wheat",), ()),
    ("seitan", "Seitan", ("wheat",), ("wheat gluten", "vital wheat gluten")),
    ("breadcrumbs", "Breadcrumbs", ("wheat",), ("panko",)),
    ("crackers", "Crackers", ("wheat",), ()),
    ("tortilla_flour", "Flour tortilla", ("wheat",), ()),
    # Egg
    ("egg", "Egg", ("egg",), ("eggs", "egg white", "egg yolk")),
    ("mayonnaise", "Mayonnaise", ("egg",), ("mayo",)),
    ("egg_noodles", "Egg noodles", ("egg", "wheat"), ()),
    # Soy
    ("soybean", "Soybeans", ("soy",), ("soy", "soya")),
    ("tofu", "Tofu", ("soy",), ("bean curd",)),
    ("edamame", "Edamame", ("soy",), ()),
    ("soy_milk", "Soy milk", ("soy",), ("soya milk",)),
    ("soy_sauce", "Soy sauce", ("soy", "wheat"), ("shoyu",)),
    ("tamari", "Tamari", ("soy",), ()),
    ("miso", "Miso", ("soy",), ()),
    ("tempeh", "Tempeh", ("soy",), ()),
    ("soy_lecithin", "Soy lecithin", ("soy",), ("lecithin",)),
    # Peanut
    ("peanut", "Peanuts", ("peanut",), ("peanut", "groundnut")),
    ("peanut_butter", "Peanut butter", ("peanut",), ()),
    # Tree nuts
    ("almond", "Almonds", ("tree_nut",), ("almond",)),
    ("almond_milk", "Almond milk", ("tree_nut",), ()),
    ("cashew", "Cashews", ("tree_nut",), ("cashew",)),
    ("walnut", "Walnuts", ("tree_nut",), ("walnut",)),
    ("pecan", "Pecans", ("tree_nut",), ("pecan",)),
    ("pistachio", "Pistachios", ("tree_nut",), ("pistachio",)),
    ("hazelnut", "Hazelnuts", ("tree_nut",), ("hazelnut", "filbert", "nutella")),
    ("macadamia", "Macadamia nuts", ("tree_nut",), ("macadamia",)),
    ("brazil_nut", "Brazil nuts", ("tree_nut",), ("brazil nut",)),
    ("pine_nut", "Pine nuts", ("tree_nut",), ("pine nut", "pignoli")),
    # Fish
    ("salmon", "Salmon", ("fish",), ()),
    ("tuna", "Tuna", ("fish",), ()),
    ("cod", "Cod", ("fish",), ()),
    ("tilapia", "Tilapia", ("fish",), ()),
    ("white_fish", "White fish", ("fish",), ("haddock", "pollock", "halibut", "fish")),
    ("anchovy", "Anchovies", ("fish",), ("anchovy",)),
    ("sardine", "Sardines", ("fish",), ("sardine",)),
    ("fish_sauce", "Fish sauce", ("fish",), ()),
    # Shellfish
    ("shrimp", "Shrimp", ("shellfish",), ("prawns", "prawn")),
    ("crab", "Crab", ("shellfish",), ()),
    ("lobster", "Lobster", ("shellfish",), ()),
    ("clam", "Clams", ("shellfish",), ("clam",)),
    ("mussel", "Mussels", ("shellfish",), ("mussel",)),
    ("scallop", "Scallops", ("shellfish",), ("scallop",)),
    ("oyster", "Oysters", ("shellfish",), ("oyster",)),
    ("squid", "Squid", ("shellfish",), ("calamari",)),
    # Sesame
    ("sesame_seed", "Sesame seeds", ("sesame",), ("sesame",)),
    ("tahini", "Tahini", ("sesame",), ()),
    ("sesame_oil", "Sesame oil", ("sesame",), ()),
    ("hummus", "Hummus", ("sesame",), ()),
    # Grains and starches without a group
    ("rice", "Rice", (), ("white rice", "brown rice")),
    ("oats", "Oats", (), ("oatmeal", "porridge")),
    ("corn", "Corn", (), ("maize", "cornmeal", "polenta", "sweetcorn")),
    ("corn_tortilla", "Corn tortilla", (), ()),
    ("barley", "Barley", (), ()),
    ("rye", "Rye", (), ()),
    ("quinoa", "Quinoa", (), ()),
    ("buckwheat", "Buckwheat", (), ("soba",)),
    ("potato", "Potato", (), ("potatoes", "fries", "chips")),
    ("sweet_potato", "Sweet potato", (), ("yam",)),
    ("rice_noodles", "Rice noodles", (), ()),
    # Meat and poultry
    ("chicken", "Chicken", (), ()),
    ("turkey", "Turkey", (), ()),
    ("beef", "Beef", (), ("steak", "hamburger", "ground beef")),
    ("pork", "Pork", (), ("ham", "bacon", "sausage")),
    ("lamb", "Lamb", (), ("mutton",)),
    # Legumes
    ("beans", "Beans", (), ("black beans", "kidney beans", "pinto beans")),
    ("lentils", "Lentils", (), ("lentil", "dal")),
    ("chickpeas", "Chickpeas", (), ("garbanzo",)),
    ("peas", "Peas", (), ("pea",)),
    # Vegetables
    ("tomato", "Tomato", (), ("tomatoes", "tomato sauce", "marinara")),
    ("onion", "Onion", (), ("onions", "shallot")),
    ("garlic", "Garlic", (), ()),
    ("carrot", "Carrot", (), ("carrots",)),
    ("broccoli", "Broccoli", (), ()),
    ("spinach", "Spinach", (), ()),
    ("lettuce", "Lettuce", (), ("salad greens", "romaine")),
    ("bell_pepper", "Bell pepper", (), ("peppers", "capsicum")),
    ("chili_pepper", "Chili pepper", (), ("chilli", "jalapeno", "hot sauce")),
    ("cucumber", "Cucumber", (), ()),
    ("mushroom", "Mushrooms", (), ("mushroom",)),
    ("avocado", "Avocado", (), ("guacamole",)),
    ("celery", "Celery", (), ()),
    ("zucchini", "Zucchini", (), ("courgette",)),
    # Fruit
    ("apple", "Apple", (), ("apples",)),
    ("banana", "Banana", (), ("bananas",)),
    ("berries", "Berries", (), ("strawberries", "blueberries", "raspberries")),
    ("citrus", "Citrus", (), ("orange", "lemon", "lime", "grapefruit")),
    ("grapes", "Grapes", (), ("raisins",)),
    ("stone_fruit", "Stone fruit", (), ("peach", "plum", "cherry", "apricot")),
    ("melon", "Melon", (), ("watermelon", "cantaloupe")),
    ("mango", "Mango", (), ()),
    ("pineapple", "Pineapple", (), ()),
    ("coconut", "Coconut", (), ("coconut milk",)),
    # Fats, sweeteners, drinks, and everything else
    ("olive_oil", "Olive oil", (), ()),
    ("vegetable_oil", "Vegetable oil", (), ("canola oil", "sunflower oil")),
    ("sugar", "Sugar", (), ()),
    ("honey", "Honey", (), ()),
    ("dark_chocolate", "Dark chocolate", (), ("cocoa", "cacao")),
    ("coffee", "Coffee", (), ("espresso",)),
    ("tea", "Tea", (), ()),
    ("wine", "Wine", (), ()),
    ("beer", "Beer", (), ()),
    ("seeds", "Seeds", (), ("sunflower seeds", "pumpkin seeds", "chia", "flax")),
    ("spices", "Spices", (), ("cinnamon", "cumin", "paprika", "curry")),
]


def upgrade() -> None:
    allergen_group = postgresql.ENUM(*ALLERGEN_GROUPS, name="allergen_group", create_type=False)
    meal = postgresql.ENUM("breakfast", "lunch", "dinner", "snack", name="meal", create_type=False)
    # entry_method already exists, created by 0002.
    entry_method = postgresql.ENUM("same_day", "backfill", name="entry_method", create_type=False)
    for enum in (allergen_group, meal):
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ingredient_catalog",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("allergen_groups", postgresql.ARRAY(allergen_group), nullable=False),
        sa.Column("aliases", postgresql.ARRAY(sa.String(length=120)), nullable=False),
        sa.PrimaryKeyConstraint("code", name="pk_ingredient_catalog"),
    )
    op.bulk_insert(
        sa.table(
            "ingredient_catalog",
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("allergen_groups", postgresql.ARRAY(allergen_group)),
            sa.column("aliases", postgresql.ARRAY(sa.String)),
        ),
        [
            {
                "code": code,
                "name": name,
                # Declaration order, matching how the application stores groups,
                # so the same set never reads back in two different orders.
                "allergen_groups": sorted(groups, key=ALLERGEN_GROUPS.index),
                "aliases": list(aka),
            }
            for code, name, groups, aka in CATALOG
        ],
    )

    op.create_table(
        "custom_ingredients",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("name_key", sa.String(length=120), nullable=False),
        sa.Column("allergen_groups", postgresql.ARRAY(allergen_group), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_custom_ingredients"),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name="fk_custom_ingredients_patient_id_patients",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "patient_id", "name_key", name="uq_custom_ingredients_patient_id_name_key"
        ),
    )

    op.create_table(
        "food_log_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("eaten_on", sa.Date(), nullable=False),
        sa.Column("meal", meal, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("name_key", sa.String(length=120), nullable=False),
        sa.Column("entry_method", entry_method, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_food_log_items"),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name="fk_food_log_items_patient_id_patients",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_food_log_items_patient_id_eaten_on", "food_log_items", ["patient_id", "eaten_on"]
    )

    op.create_table(
        "food_log_item_ingredients",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingredient_code", sa.String(length=64), nullable=True),
        sa.Column("custom_ingredient_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_food_log_item_ingredients"),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name="fk_food_log_item_ingredients_patient_id_patients",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["food_log_items.id"],
            name="fk_food_log_item_ingredients_item_id_food_log_items",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingredient_code"],
            ["ingredient_catalog.code"],
            name="fk_food_log_item_ingredients_ingredient_code",
        ),
        # NO ACTION, not RESTRICT: checked at end of statement, so a patient
        # deletion can cascade through both tables in whichever order it runs.
        # These two names drop the referred table, which the convention appends,
        # because the full form passes Postgres's 63-character identifier limit.
        sa.ForeignKeyConstraint(
            ["custom_ingredient_id"],
            ["custom_ingredients.id"],
            name="fk_food_log_item_ingredients_custom_ingredient_id",
        ),
        sa.CheckConstraint(
            "(ingredient_code IS NULL) <> (custom_ingredient_id IS NULL)",
            name="ck_food_log_item_ingredients_exactly_one_ingredient",
        ),
        sa.UniqueConstraint(
            "item_id", "ingredient_code", name="uq_food_log_item_ingredients_item_id_code"
        ),
        sa.UniqueConstraint(
            "item_id",
            "custom_ingredient_id",
            name="uq_food_log_item_ingredients_item_id_custom",
        ),
    )
    op.create_index(
        "ix_food_log_item_ingredients_patient_id", "food_log_item_ingredients", ["patient_id"]
    )

    _apply_row_level_security()
    _apply_runtime_grants()


def _apply_row_level_security() -> None:
    scope = "NULLIF(current_setting('app.current_patient_id', true), '')::uuid"
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY patient_isolation ON {table} USING (patient_id = {scope})")


def _apply_runtime_grants() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON custom_ingredients TO app_runtime;
                GRANT SELECT, INSERT, UPDATE, DELETE ON food_log_items TO app_runtime;
                GRANT SELECT, INSERT, UPDATE, DELETE ON food_log_item_ingredients TO app_runtime;
                -- Reference data: readable, never writable by the application.
                GRANT SELECT ON ingredient_catalog TO app_runtime;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("food_log_item_ingredients")
    op.drop_table("food_log_items")
    op.drop_table("custom_ingredients")
    op.drop_table("ingredient_catalog")

    # entry_method belongs to 0002 and stays.
    for enum_name in ("meal", "allergen_group"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
