"""Ingredient identity: canonical keys, additives, and allergen groups.

**Canonical keys** use Open Food Facts' taxonomy form (``en:soya-oil``,
``en:e202``), so an ingredient reads the same whether it came from an OFF
product, a USDA label parsed here, or the patient's own typing. The synonym
table below is small and curated; it maps the spellings US labels actually use
onto the keys OFF assigns. Anything it does not know gets a slug key and is
marked unrecognized, which is shown to the patient rather than hidden.

**Additives** matter here specifically: a food-symptom analysis should be able
to ask about carrageenan, or about emulsifiers as a class, not only about the
nine allergen groups.

**Allergen groups** are classified from words, with the exceptions that make
naive matching wrong: buckwheat is not wheat, coconut milk and cocoa butter are
not milk, nutmeg and butternut are not nuts, and peanut butter is peanut.

PENDING CLINICAL CONFIRMATION: the allergen rules and the additive classes need
the clinical advisor's review before they drive any patient-facing insight. The
E-number assignments are regulatory facts and are not in question.

A full import of the OFF ingredient taxonomy is planned alongside the local
mirror of both datasets; this table is the bridge until then.
"""

import enum
import re
import unicodedata
from dataclasses import dataclass

from eoehelp_api.food.enums import AllergenGroup, EliminationGroup


class AdditiveClass(enum.StrEnum):
    PRESERVATIVE = "preservative"
    ANTIOXIDANT = "antioxidant"
    EMULSIFIER = "emulsifier"
    THICKENER = "thickener"
    COLOUR = "colour"
    SWEETENER = "sweetener"
    FLAVOUR_ENHANCER = "flavour_enhancer"
    ACIDITY_REGULATOR = "acidity_regulator"
    RAISING_AGENT = "raising_agent"
    ANTI_CAKING = "anti_caking"
    HUMECTANT = "humectant"
    GLAZING = "glazing"


@dataclass(frozen=True)
class Additive:
    key: str
    name: str
    additive_class: AdditiveClass


P, A, E, T = (
    AdditiveClass.PRESERVATIVE,
    AdditiveClass.ANTIOXIDANT,
    AdditiveClass.EMULSIFIER,
    AdditiveClass.THICKENER,
)
C, S, F, R = (
    AdditiveClass.COLOUR,
    AdditiveClass.SWEETENER,
    AdditiveClass.FLAVOUR_ENHANCER,
    AdditiveClass.ACIDITY_REGULATOR,
)

# (E-number, display name, class, US label spellings)
_ADDITIVES: tuple[tuple[str, str, AdditiveClass, tuple[str, ...]], ...] = (
    # Preservatives
    ("e200", "Sorbic acid", P, ("sorbic acid",)),
    ("e202", "Potassium sorbate", P, ("potassium sorbate",)),
    ("e210", "Benzoic acid", P, ("benzoic acid",)),
    ("e211", "Sodium benzoate", P, ("sodium benzoate",)),
    ("e220", "Sulfur dioxide", P, ("sulfur dioxide", "sulphur dioxide")),
    ("e223", "Sodium metabisulfite", P, ("sodium metabisulfite", "sodium bisulfite")),
    ("e224", "Potassium metabisulfite", P, ("potassium metabisulfite",)),
    ("e234", "Nisin", P, ("nisin",)),
    ("e235", "Natamycin", P, ("natamycin",)),
    ("e250", "Sodium nitrite", P, ("sodium nitrite",)),
    ("e251", "Sodium nitrate", P, ("sodium nitrate",)),
    ("e280", "Propionic acid", P, ("propionic acid",)),
    ("e281", "Sodium propionate", P, ("sodium propionate",)),
    ("e282", "Calcium propionate", P, ("calcium propionate",)),
    ("e385", "Calcium disodium EDTA", P, ("calcium disodium edta", "edta")),
    # Antioxidants
    ("e300", "Ascorbic acid", A, ("ascorbic acid", "vitamin c")),
    ("e301", "Sodium ascorbate", A, ("sodium ascorbate",)),
    ("e306", "Tocopherols", A, ("tocopherols", "mixed tocopherols", "vitamin e")),
    ("e319", "TBHQ", A, ("tbhq", "tertiary butylhydroquinone")),
    ("e320", "BHA", A, ("bha", "butylated hydroxyanisole")),
    ("e321", "BHT", A, ("bht", "butylated hydroxytoluene")),
    ("e392", "Rosemary extract", A, ("rosemary extract", "extract of rosemary")),
    # Emulsifiers
    ("e322", "Lecithin", E, ("lecithin",)),
    ("e433", "Polysorbate 80", E, ("polysorbate 80",)),
    ("e471", "Mono- and diglycerides", E, ("mono and diglycerides", "mono- and diglycerides")),
    ("e472e", "DATEM", E, ("datem",)),
    ("e481", "Sodium stearoyl lactylate", E, ("sodium stearoyl lactylate",)),
    ("e491", "Sorbitan monostearate", E, ("sorbitan monostearate",)),
    # Thickeners, gelling agents, stabilizers
    ("e401", "Sodium alginate", T, ("sodium alginate",)),
    ("e406", "Agar", T, ("agar", "agar agar")),
    ("e407", "Carrageenan", T, ("carrageenan",)),
    ("e410", "Locust bean gum", T, ("locust bean gum", "carob bean gum")),
    ("e412", "Guar gum", T, ("guar gum",)),
    ("e414", "Gum arabic", T, ("gum arabic", "acacia gum", "gum acacia")),
    ("e415", "Xanthan gum", T, ("xanthan gum",)),
    ("e418", "Gellan gum", T, ("gellan gum",)),
    ("e440", "Pectin", T, ("pectin",)),
    ("e460", "Cellulose", T, ("cellulose", "microcrystalline cellulose", "cellulose gel")),
    ("e461", "Methylcellulose", T, ("methylcellulose",)),
    ("e464", "Hydroxypropyl methylcellulose", T, ("hydroxypropyl methylcellulose",)),
    ("e466", "Cellulose gum", T, ("cellulose gum", "carboxymethylcellulose")),
    ("e1422", "Modified starch", T, ("modified food starch", "modified starch")),
    # Colours
    ("e100", "Curcumin", C, ("curcumin", "turmeric extract", "turmeric color")),
    ("e102", "Tartrazine", C, ("tartrazine", "yellow 5", "fd&c yellow no. 5", "yellow #5")),
    (
        "e110",
        "Sunset yellow",
        C,
        ("sunset yellow", "yellow 6", "fd&c yellow no. 6", "yellow #6"),
    ),
    ("e127", "Erythrosine", C, ("erythrosine", "red 3", "fd&c red no. 3")),
    ("e129", "Allura red", C, ("allura red", "red 40", "fd&c red no. 40", "red #40")),
    ("e133", "Brilliant blue", C, ("brilliant blue", "blue 1", "fd&c blue no. 1", "blue #1")),
    ("e132", "Indigotine", C, ("indigotine", "blue 2", "fd&c blue no. 2")),
    ("e150", "Caramel color", C, ("caramel color", "caramel colour")),
    ("e160a", "Beta-carotene", C, ("beta carotene", "beta-carotene")),
    ("e160b", "Annatto", C, ("annatto", "annatto extract", "annatto color")),
    ("e162", "Beet red", C, ("beet juice color", "beetroot red")),
    ("e171", "Titanium dioxide", C, ("titanium dioxide",)),
    # Sweeteners
    ("e420", "Sorbitol", S, ("sorbitol",)),
    ("e950", "Acesulfame potassium", S, ("acesulfame potassium", "acesulfame k")),
    ("e951", "Aspartame", S, ("aspartame",)),
    ("e955", "Sucralose", S, ("sucralose",)),
    ("e960", "Steviol glycosides", S, ("stevia extract", "steviol glycosides", "rebaudioside a")),
    ("e965", "Maltitol", S, ("maltitol",)),
    ("e967", "Xylitol", S, ("xylitol",)),
    ("e968", "Erythritol", S, ("erythritol",)),
    # Flavour enhancers
    ("e621", "Monosodium glutamate", F, ("monosodium glutamate", "msg")),
    ("e627", "Disodium guanylate", F, ("disodium guanylate",)),
    ("e631", "Disodium inosinate", F, ("disodium inosinate",)),
    # Acidity regulators
    ("e260", "Acetic acid", R, ("acetic acid",)),
    ("e270", "Lactic acid", R, ("lactic acid",)),
    ("e296", "Malic acid", R, ("malic acid",)),
    ("e330", "Citric acid", R, ("citric acid",)),
    ("e334", "Tartaric acid", R, ("tartaric acid",)),
    ("e338", "Phosphoric acid", R, ("phosphoric acid",)),
    ("e339", "Sodium phosphate", R, ("sodium phosphate", "disodium phosphate")),
    ("e341", "Calcium phosphate", R, ("calcium phosphate", "tricalcium phosphate")),
    # Raising agents
    (
        "e450",
        "Sodium acid pyrophosphate",
        AdditiveClass.RAISING_AGENT,
        ("sodium acid pyrophosphate",),
    ),
    (
        "e500",
        "Sodium bicarbonate",
        AdditiveClass.RAISING_AGENT,
        (
            "sodium bicarbonate",
            "baking soda",
        ),
    ),
    ("e503", "Ammonium bicarbonate", AdditiveClass.RAISING_AGENT, ("ammonium bicarbonate",)),
    # Anti-caking, humectants, glazing
    ("e551", "Silicon dioxide", AdditiveClass.ANTI_CAKING, ("silicon dioxide", "silica")),
    ("e552", "Calcium silicate", AdditiveClass.ANTI_CAKING, ("calcium silicate",)),
    ("e900", "Dimethylpolysiloxane", AdditiveClass.ANTI_CAKING, ("dimethylpolysiloxane",)),
    ("e422", "Glycerin", AdditiveClass.HUMECTANT, ("glycerin", "glycerol", "vegetable glycerin")),
    ("e1520", "Propylene glycol", AdditiveClass.HUMECTANT, ("propylene glycol",)),
    ("e901", "Beeswax", AdditiveClass.GLAZING, ("beeswax",)),
    ("e903", "Carnauba wax", AdditiveClass.GLAZING, ("carnauba wax",)),
    ("e904", "Shellac", AdditiveClass.GLAZING, ("shellac", "confectioner's glaze")),
)

ADDITIVES: dict[str, Additive] = {
    f"en:{code}": Additive(key=f"en:{code}", name=name, additive_class=cls)
    for code, name, cls, _ in _ADDITIVES
}

# Non-additive spellings US labels use, onto OFF's keys. Lower-case, singular or
# plural as printed; lookup also tries without a trailing "s".
_FOODS: dict[str, tuple[str, ...]] = {
    "en:water": ("water", "filtered water", "purified water"),
    "en:salt": ("salt", "sea salt", "iodized salt", "kosher salt"),
    "en:sugar": ("sugar", "cane sugar", "granulated sugar", "evaporated cane juice"),
    "en:egg": ("egg", "eggs"),
    "en:whole-egg": ("whole egg", "whole eggs"),
    "en:egg-yolk": ("egg yolk", "egg yolks"),
    "en:egg-white": ("egg white", "egg whites", "albumen"),
    "en:milk": ("milk", "whole milk"),
    "en:skimmed-milk": ("skim milk", "nonfat milk", "non-fat milk"),
    "en:milk-powder": ("milk powder", "dry milk", "nonfat dry milk"),
    "en:whey": ("whey", "whey powder"),
    "en:whey-protein-concentrate": ("whey protein concentrate",),
    "en:butter": ("butter",),
    "en:cream": ("cream", "heavy cream"),
    "en:cheese": ("cheese",),
    "en:wheat-flour": ("wheat flour", "flour", "unbleached wheat flour"),
    "en:fortified-wheat-flour": (
        "enriched flour",
        "enriched wheat flour",
        "enriched bleached flour",
    ),
    "en:whole-wheat-flour": ("whole wheat flour",),
    "en:wheat-gluten": ("wheat gluten", "vital wheat gluten"),
    "en:soya": ("soy", "soya", "soybean", "soybeans"),
    "en:soya-oil": ("soybean oil", "soy oil", "soya oil"),
    "en:soya-lecithin": ("soy lecithin", "soya lecithin", "lecithin (soy)"),
    "en:sunflower-lecithin": ("sunflower lecithin",),
    "en:soy-sauce": ("soy sauce",),
    "en:peanut": ("peanut", "peanuts"),
    "en:rapeseed-oil": ("canola oil", "rapeseed oil", "expeller pressed canola oil"),
    "en:sunflower-oil": ("sunflower oil", "sunflower seed oil", "high oleic sunflower oil"),
    "en:avocado-oil": ("avocado oil",),
    "en:olive-oil": ("olive oil", "extra virgin olive oil"),
    "en:palm-oil": ("palm oil",),
    "en:vinegar": ("vinegar",),
    "en:distilled-vinegar": ("distilled vinegar", "distilled white vinegar", "white vinegar"),
    "en:natural-flavouring": ("natural flavor", "natural flavors", "natural flavoring"),
    "en:flavouring": ("artificial flavor", "artificial flavors", "flavoring"),
    "en:spice": ("spice", "spices"),
    "en:yeast": ("yeast",),
    "en:yeast-extract": ("yeast extract", "autolyzed yeast extract"),
    "en:corn-syrup": ("corn syrup",),
    "en:high-fructose-corn-syrup": ("high fructose corn syrup",),
    "en:dextrose": ("dextrose",),
    "en:maltodextrin": ("maltodextrin",),
    "en:corn-starch": ("corn starch", "cornstarch"),
    "en:modified-corn-starch": ("modified corn starch", "modified cornstarch"),
    "en:garlic-powder": ("garlic powder",),
    "en:onion-powder": ("onion powder",),
    "en:paprika": ("paprika",),
    "en:mustard": ("mustard",),
    "en:concentrated-lemon-juice": ("lemon juice concentrate",),
    "en:chickpea": ("chickpea", "chickpeas", "garbanzo beans"),
    "en:rice": ("rice",),
    "en:niacin": ("niacin",),
    "en:reduced-iron": ("reduced iron",),
    "en:thiamin-mononitrate": ("thiamin mononitrate",),
    "en:riboflavin": ("riboflavin",),
    "en:folic-acid": ("folic acid",),
}

_SPELLINGS: dict[str, str] = {}
for _key, _names in _FOODS.items():
    for _name in _names:
        _SPELLINGS[_name] = _key
for _code, _, _, _names in _ADDITIVES:
    for _name in _names:
        _SPELLINGS[_name] = f"en:{_code}"

# Descriptors that do not change what an ingredient is.
_NOISE = re.compile(
    r"\b(?:organic|certified|non-?gmo|all natural|expeller[- ]pressed|cultured|"
    r"unbleached|pure|fresh)\b",
    re.IGNORECASE,
)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _fold(text)).strip("-")


@dataclass(frozen=True)
class Identity:
    key: str
    recognized: bool


def identify(name: str) -> Identity:
    """The canonical key for a printed ingredient name, and whether it is known."""
    folded = " ".join(_fold(name).replace("\u2019", "'").split())
    candidates = [folded, " ".join(_NOISE.sub(" ", folded).split())]
    for candidate in candidates:
        for form in (candidate, candidate.removesuffix("s"), candidate.removesuffix("es")):
            if form in _SPELLINGS:
                return Identity(key=_SPELLINGS[form], recognized=True)
    # An E-number printed as such.
    enumber = re.fullmatch(r"e\s?-?(\d{3,4}[a-z]?)", candidates[-1])
    if enumber and f"en:e{enumber.group(1)}" in ADDITIVES:
        return Identity(key=f"en:e{enumber.group(1)}", recognized=True)
    return Identity(key=f"en:{slug(candidates[-1]) or 'unknown'}", recognized=False)


def additive(key: str) -> Additive | None:
    return ADDITIVES.get(key)


# --- allergen groups ----------------------------------------------------------

# Each group: the words that indicate it, and phrases that look like it but are not.
_ALLERGEN_RULES: dict[AllergenGroup, tuple[re.Pattern[str], re.Pattern[str] | None]] = {
    AllergenGroup.MILK: (
        re.compile(
            r"\b(?:milk|whey|casein\w*|lactose|lactalbumin|lactoglobulin|butter\w*|"
            r"buttermilk|cream|cheese|ghee|yogh?urt|kefir|curds?|dairy|skyr|paneer)\b"
        ),
        re.compile(
            r"\b(?:coconut|almond|oat|soy|soya|rice|cashew|hemp|pea|macadamia|flax)\s+"
            r"(?:milk|cream|butter|yogh?urt|cheese)\b|\b(?:cocoa|cacao|shea|peanut|nut|"
            r"almond|cashew|sunflower|seed|apple|butternut)\s*butter\b|\bbutternut\b"
            r"|\bcream of tartar\b|\bmilk thistle\b|\bmilkweed\b|\bbutterfly\b"
        ),
    ),
    AllergenGroup.WHEAT: (
        re.compile(
            r"\b(?:wheat|semolina|durum|spelt|farro|kamut|einkorn|emmer|bulgu?a?r|"
            r"couscous|seitan|triticale|farina)\b|\bwheat\w*"
        ),
        re.compile(r"\bbuckwheat\b"),
    ),
    AllergenGroup.EGG: (
        re.compile(
            # Not "mayonnaise": vegan mayonnaise exists, and this list asserts.
            r"\b(?:eggs?|egg\w+|albumin|albumen|ovalbumin|ovomucoid|lysozyme|"
            r"meringue)\b|\bwhole-egg\b|\begg-"
        ),
        re.compile(r"\beggplants?\b|\begg-?plant\b"),
    ),
    AllergenGroup.SOY: (
        re.compile(r"\b(?:soy\w*|soya\w*|edamame|tofu|tempeh|miso|tamari|natto)\b"),
        None,
    ),
    AllergenGroup.PEANUT: (
        re.compile(r"\b(?:peanuts?|groundnuts?|arachis)\b"),
        None,
    ),
    AllergenGroup.TREE_NUT: (
        re.compile(
            r"\b(?:almonds?|cashews?|walnuts?|pecans?|pistachios?|hazelnuts?|filberts?|"
            r"macadamias?|brazil\s+nuts?|pine\s+nuts?|pignoli|praline|marzipan)\b"
            r"|\btree\s+nuts?\b"
        ),
        None,
    ),
    AllergenGroup.FISH: (
        re.compile(
            r"\b(?:fish|anchov\w*|salmon|tuna|cod|pollock|tilapia|haddock|halibut|"
            r"sardines?|mackerel|trout|bass|catfish|herring|swordfish|snapper|"
            r"bonito|surimi)\b"
        ),
        re.compile(r"\bshellfish\b"),
    ),
    AllergenGroup.SHELLFISH: (
        re.compile(
            r"\b(?:shellfish|shrimps?|prawns?|crabs?|lobsters?|crayfish|crawfish|"
            r"clams?|mussels?|oysters?|scallops?|squid|calamari|octopus|krill)\b"
        ),
        None,
    ),
    AllergenGroup.SESAME: (
        re.compile(r"\b(?:sesame|tahini|tahina|benne)\b"),
        None,
    ),
}


def allergen_groups(*texts: str) -> frozenset[AllergenGroup]:
    """The groups any of the given names or keys indicate.

    Keys and names are both passed, because each catches what the other misses:
    ``en:e322`` says nothing, but "soy lecithin" does; "natural flavor" says
    nothing either way, and neither does its key.
    """
    found: set[AllergenGroup] = set()
    for text in texts:
        folded = _fold(text).replace("en:", " ").replace("-", " ")
        for group, (include, exclude) in _ALLERGEN_RULES.items():
            cleaned = exclude.sub(" ", folded) if exclude else folded
            if include.search(cleaned):
                found.add(group)
    return frozenset(found)


def ordered(groups: frozenset[AllergenGroup] | set[AllergenGroup]) -> list[AllergenGroup]:
    return [group for group in AllergenGroup if group in groups]


# --- elimination-diet groups --------------------------------------------------

_ELIMINATION_RULES: dict[EliminationGroup, tuple[re.Pattern[str], re.Pattern[str] | None]] = {
    # Wheat and its forms, plus the other gluten cereals and their products.
    # Oats are left out: they are gluten-free unless cross-contaminated, and the
    # protocols treat them separately.
    EliminationGroup.GLUTEN_CEREALS: (
        re.compile(
            r"\b(?:wheat|semolina|durum|spelt|farro|kamut|einkorn|emmer|bulgu?a?r|"
            r"couscous|seitan|triticale|farina|barley|rye|malt\w*|gluten)\b|\bwheat\w*"
        ),
        re.compile(r"\bbuckwheat\b|\bgluten[- ]free\b"),
    ),
    # Soy and peanut are legumes too, so a legume-free diet removes them as well.
    EliminationGroup.LEGUMES: (
        re.compile(
            r"\b(?:legumes?|beans?|lentils?|dal|chickpeas?|garbanzo|peas|pea\b|"
            r"lupin\w*|soy\w*|soya\w*|edamame|tofu|tempeh|miso|tamari|peanuts?|"
            r"groundnuts?|fava|carob|hummus)\b"
        ),
        # Called beans, but not legumes. Green beans and snow peas are, and stay in.
        re.compile(r"\b(?:coffee|cocoa|cacao|vanilla|jelly) beans?\b"),
    ),
}


def elimination_groups(*texts: str) -> frozenset[EliminationGroup]:
    """The elimination-diet groups any of the given names or keys indicate."""
    found: set[EliminationGroup] = set()
    for text in texts:
        folded = _fold(text).replace("en:", " ").replace("-", " ")
        for group, (include, exclude) in _ELIMINATION_RULES.items():
            cleaned = exclude.sub(" ", folded) if exclude else folded
            if include.search(cleaned):
                found.add(group)
    return frozenset(found)
