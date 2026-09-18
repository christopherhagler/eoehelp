"""Label parsing, ingredient identity, and allergen classification.

Pure functions, tested against the kinds of text real US labels carry.
"""

import pytest

from eoehelp_api.fooddata import labels, vocabulary
from eoehelp_api.fooddata.records import flatten, normalise_barcode
from eoehelp_api.models.enums import AllergenGroup as G
from eoehelp_api.models.enums import EliminationGroup as E


def names(text: str) -> list[tuple[int, str]]:
    return [(i.depth, i.name) for i in flatten(labels.parse(text).ingredients)]


class TestParsing:
    def test_nested_lists_keep_their_depth(self) -> None:
        text = "AVOCADO OIL, MUSTARD (WATER, MUSTARD SEEDS [BROWN, YELLOW]), SALT."
        assert names(text) == [
            (0, "AVOCADO OIL"),
            (0, "MUSTARD"),
            (1, "WATER"),
            (1, "MUSTARD SEEDS"),
            (2, "BROWN"),
            (2, "YELLOW"),
            (0, "SALT"),
        ]

    def test_threshold_phrases_are_not_ingredients(self) -> None:
        text = "SUGAR, CONTAINS 2% OR LESS OF: SALT, contains less than 2% of natural flavor"
        assert [n for _, n in names(text)] == ["SUGAR", "SALT", "natural flavor"]

    def test_a_stated_purpose_is_a_note_not_an_ingredient(self) -> None:
        parsed = labels.parse(
            "POTASSIUM SORBATE (TO PROTECT FRESHNESS), SUCRALOSE (SWEETENER), "
            "CITRIC ACID ADDED AS A PRESERVATIVE, THIAMIN (VITAMIN B1)"
        )
        assert [(i.name, i.note, i.children) for i in parsed.ingredients] == [
            ("POTASSIUM SORBATE", "TO PROTECT FRESHNESS", ()),
            ("SUCRALOSE", "SWEETENER", ()),
            ("CITRIC ACID", None, ()),
            ("THIAMIN", "VITAMIN B1", ()),
        ]

    def test_the_contains_statement_is_the_declaration(self) -> None:
        parsed = labels.parse("Ingredients: FLOUR, EGGS. Contains: Wheat, Egg and Milk.")
        assert [i.name for i in parsed.ingredients] == ["FLOUR", "EGGS"]
        assert parsed.declared_allergens == ("wheat", "egg", "milk")
        assert parsed.may_contain == ()

    def test_precautionary_statements_are_kept_separately_and_all_of_them(self) -> None:
        parsed = labels.parse(
            "OATS, HONEY. CONTAINS: ALMONDS. MAY CONTAIN MILK AND TREE NUTS. "
            "MADE IN A FACILITY THAT ALSO PROCESSES PEANUTS, SOY, AND SESAME. "
            "DISTRIBUTED BY ACME FOODS, CHICAGO IL 60601"
        )
        assert [i.name for i in parsed.ingredients] == ["OATS", "HONEY"]
        assert parsed.declared_allergens == ("almonds",)
        groups = vocabulary.allergen_groups(*parsed.may_contain)
        assert groups == {G.MILK, G.TREE_NUT, G.PEANUT, G.SOY, G.SESAME}

    def test_debris_in_a_statement_classifies_to_nothing(self) -> None:
        """A real OCR'd label put an address inside its allergen statement."""
        parsed = labels.parse("water, eggs contains: egg, 2% kraft heinz, il 60601 remove seal")
        assert vocabulary.allergen_groups(*parsed.declared_allergens) == {G.EGG}

    def test_empty_text(self) -> None:
        assert labels.parse(None) == labels.ParsedLabel(ingredients=(), declared_allergens=())
        assert labels.parse("   ").ingredients == ()


class TestIdentity:
    @pytest.mark.parametrize(
        ("printed", "key"),
        [
            ("SOYBEAN OIL", "en:soya-oil"),
            ("Organic Canola Oil", "en:rapeseed-oil"),
            ("whole eggs", "en:whole-egg"),
            ("EGGS", "en:egg"),
            ("Calcium Disodium EDTA", "en:e385"),
            ("POTASSIUM SORBATE", "en:e202"),
            ("xanthan gum", "en:e415"),
            ("Red 40", "en:e129"),
            ("E330", "en:e330"),
            ("natural flavors", "en:natural-flavouring"),
            ("soy lecithin", "en:soya-lecithin"),
        ],
    )
    def test_label_spellings_reach_the_standard_key(self, printed: str, key: str) -> None:
        identity = vocabulary.identify(printed)
        assert identity == vocabulary.Identity(key=key, recognized=True)

    def test_unknown_names_get_a_stable_slug_and_say_so(self) -> None:
        assert vocabulary.identify("Tapioca Starch") == vocabulary.Identity(
            key="en:tapioca-starch", recognized=False
        )
        assert vocabulary.identify("paprīka blend").key == "en:paprika-blend"

    def test_additives_carry_a_class(self) -> None:
        additive = vocabulary.additive("en:e407")
        assert additive is not None
        assert (additive.name, additive.additive_class.value) == ("Carrageenan", "thickener")
        assert vocabulary.additive("en:water") is None

    def test_no_spelling_is_claimed_twice(self) -> None:
        """A spelling mapped to two keys would resolve by table order."""
        spellings: dict[str, set[str]] = {}
        for key, names_ in vocabulary._FOODS.items():
            for name in names_:
                spellings.setdefault(name, set()).add(key)
        for code, _, _, names_ in vocabulary._ADDITIVES:
            for name in names_:
                spellings.setdefault(name, set()).add(f"en:{code}")
        assert {s: k for s, k in spellings.items() if len(k) > 1} == {}


class TestAllergenGroups:
    @pytest.mark.parametrize(
        ("text", "groups"),
        [
            ("whole eggs", {G.EGG}),
            ("en:egg-yolk", {G.EGG}),
            ("whey protein concentrate", {G.MILK}),
            ("sodium caseinate", {G.MILK}),
            ("enriched wheat flour", {G.WHEAT}),
            ("soy lecithin", {G.SOY}),
            ("peanut butter", {G.PEANUT}),
            ("cashew cream", {G.TREE_NUT}),
            ("anchovy paste", {G.FISH}),
            ("shrimp", {G.SHELLFISH}),
            ("tahini", {G.SESAME}),
            # The cases naive matching gets wrong.
            ("buckwheat flour", set()),
            ("coconut milk", set()),
            ("cocoa butter", set()),
            ("nutmeg", set()),
            ("butternut squash", set()),
            ("eggplant", set()),
            ("cream of tartar", set()),
            ("almond milk", {G.TREE_NUT}),
            ("soy milk", {G.SOY}),
            # Recipes vary, so the word alone asserts nothing.
            ("mayonnaise", set()),
            ("natural flavors", set()),
        ],
    )
    def test_classification(self, text: str, groups: set[G]) -> None:
        assert vocabulary.allergen_groups(text) == groups

    def test_order_follows_the_enum(self) -> None:
        assert vocabulary.ordered(frozenset({G.SESAME, G.MILK, G.SOY})) == [G.MILK, G.SOY, G.SESAME]


class TestBarcodes:
    @pytest.mark.parametrize(
        ("raw", "normal"),
        [
            ("048001213487", "0048001213487"),
            ("0048001213487", "0048001213487"),
            ("00048001213487", "0048001213487"),
            ("4050033926900", "4050033926900"),
            ("0 48001 21348 7", "0048001213487"),
            ("1234", None),
            ("", None),
            (None, None),
        ],
    )
    def test_upc_and_ean_forms_meet(self, raw: str | None, normal: str | None) -> None:
        assert normalise_barcode(raw) == normal


class TestEliminationGroups:
    @pytest.mark.parametrize(
        ("text", "groups"),
        [
            ("barley malt", {E.GLUTEN_CEREALS}),
            ("rye flour", {E.GLUTEN_CEREALS}),
            ("enriched wheat flour", {E.GLUTEN_CEREALS}),
            ("malt vinegar", {E.GLUTEN_CEREALS}),
            ("oats", set()),
            ("buckwheat", set()),
            ("gluten-free oats", set()),
            ("lentils", {E.LEGUMES}),
            ("chickpeas", {E.LEGUMES}),
            ("black beans", {E.LEGUMES}),
            ("soy lecithin", {E.LEGUMES}),
            ("peanut butter", {E.LEGUMES}),
            ("pea protein", {E.LEGUMES}),
            ("coffee beans", set()),
            ("cocoa beans", set()),
            ("vanilla bean", set()),
            ("rice", set()),
        ],
    )
    def test_classification(self, text: str, groups: set[E]) -> None:
        assert vocabulary.elimination_groups(text) == groups
