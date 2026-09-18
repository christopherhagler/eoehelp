"""Parsing a printed ingredient statement into a tree.

Labels follow conventions loosely, so this is a tolerant parser rather than a
grammar. What it handles, because real US labels do all of it:

- nested lists: ``MUSTARD (WATER, MUSTARD SEED, VINEGAR)``, with any bracket style
- threshold phrases: ``CONTAINS 2% OR LESS OF: SALT, SPICES``
- function notes that are not ingredients: ``POTASSIUM SORBATE (TO PROTECT
  FRESHNESS)``, ``SUCRALOSE (SWEETENER)``, ``... AS A PRESERVATIVE``
- the allergen statement: ``CONTAINS: EGG, SOY``
- the precautionary statement: ``MAY CONTAIN PEANUTS``, ``MADE IN A FACILITY
  THAT ALSO PROCESSES TREE NUTS``. Kept separately from the declaration, because
  it is a different claim — possible cross-contact, not an ingredient — and
  trace exposure is plausibly relevant in EoE.
- trailing text that is not ingredients at all: "distributed by", addresses

It does not decide what an ingredient *is*; that is vocabulary.py.
"""

import re
from dataclasses import dataclass, field

MAX_DEPTH = 4


@dataclass(frozen=True)
class LabelIngredient:
    name: str
    note: str | None = None
    children: tuple["LabelIngredient", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ParsedLabel:
    ingredients: tuple[LabelIngredient, ...]
    # The words after "Contains:", split but not yet classified.
    declared_allergens: tuple[str, ...]
    # The words of any "may contain" / shared-facility statement, likewise.
    may_contain: tuple[str, ...] = ()


_OPEN = "([{"
_CLOSE = ")]}"

# Where the ingredient list ends and something else begins.
_ALLERGEN_STATEMENT = re.compile(r"\bcontains\s*:", re.IGNORECASE)
_PRECAUTION = re.compile(
    r"\b(?:may\s+contain(?:\s+traces\s+of)?|(?:made|manufactured|produced|processed|packaged)"
    r"\s+(?:in|on)\s+(?:a\s+)?(?:facility|equipment|shared\s+equipment|a\s+plant)"
    r"(?:\s+that\s+(?:also\s+)?(?:processes|handles|uses|produces|manufactures))?"
    r"(?:\s+with)?)\s*:?",
    re.IGNORECASE,
)
_TRAILER = re.compile(
    r"\b(?:distributed\s+by|manufactured\s+(?:by|for)|packed\s+(?:by|for)"
    r"|allergy\s+information|for\s+allergens|remove\s+inner|visit\s+us)\b",
    re.IGNORECASE,
)
_LEADER = re.compile(r"^\s*ingredients?\s*:\s*", re.IGNORECASE)

_THRESHOLD = re.compile(
    r"^(?:and\s+)?(?:contains\s+)?(?:"
    r"(?:less\s+than|not\s+more\s+than)\s+\d+(?:\.\d+)?\s*%"
    r"|\d+(?:\.\d+)?\s*%\s+or\s+less"
    r")\s*(?:of\s*)?(?:(?:each\s+of\s+)?the\s+following\s*)?(?:ingredients?\s*)?:?\s*",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"\s*\(?\b\d+(?:\.\d+)?\s*%\)?")

# Words that make a parenthetical a description of purpose, not a sub-list.
_FUNCTION = re.compile(
    r"^(?:used\s+)?(?:to|for|as)\b|preserv|freshness|quality|\bcolou?r\b|sweetener"
    r"|emulsifier|thickener|stabili[sz]er|antioxidant|mold\s+inhibitor|leavening"
    r"|dough\s+conditioner|flavou?r\s+enhancer|acidulant|anti-?caking|\bvitamin\b\s*[a-z0-9]*$",
    re.IGNORECASE,
)
_TRAILING_FUNCTION = re.compile(
    r"\s+(?:added\s+)?(?:as|to|for)\s+(?:a\s+|an\s+)?"
    r"(?:preservative|protect\b|preserve\b|maintain\b|retain\b|promote\b|prevent\b"
    r"|colou?r\b|freshness\b|flavou?r\b|thicken|emulsif).*$",
    re.IGNORECASE,
)


def is_function_note(text: str) -> bool:
    """Whether a fragment describes an ingredient's purpose rather than naming one."""
    return "," not in text and bool(_FUNCTION.search(text.strip()))


def _split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char in _OPEN:
            depth += 1
        elif char in _CLOSE:
            depth = max(depth - 1, 0)
        if char in ",;" and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _clean(name: str) -> str:
    name = _THRESHOLD.sub("", name.strip())
    name = _PERCENT.sub("", name)
    name = _TRAILING_FUNCTION.sub("", name)
    name = re.sub(r"^\s*and\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[\s*†‡.:]+$", "", name)
    return " ".join(name.split())


def _parse_item(raw: str, depth: int) -> LabelIngredient | None:
    raw = _THRESHOLD.sub("", raw.strip())
    open_at = next((i for i, c in enumerate(raw) if c in _OPEN), -1)
    if open_at < 0:
        name = _clean(raw)
        return LabelIngredient(name=name) if name else None

    # Find the bracket that closes the first one; anything after it (rare, but
    # "SALT (SEA) FLAKES" happens) is folded back into the name.
    level = 0
    close_at = len(raw)
    for i in range(open_at, len(raw)):
        if raw[i] in _OPEN:
            level += 1
        elif raw[i] in _CLOSE:
            level -= 1
            if level == 0:
                close_at = i
                break
    inner = raw[open_at + 1 : close_at].strip()
    name = _clean(raw[:open_at] + " " + raw[close_at + 1 :])
    if not name:
        return None

    is_list = "," in inner or ";" in inner
    if not inner or (not is_list and _FUNCTION.search(inner)):
        return LabelIngredient(name=name, note=inner or None)
    if depth >= MAX_DEPTH:
        return LabelIngredient(name=name)
    children = tuple(
        child
        for part in _split_top_level(inner)
        if (child := _parse_item(part, depth + 1)) is not None
    )
    return LabelIngredient(name=name, children=children)


def _statement_words(after: str) -> tuple[str, ...]:
    """The items of a statement, up to the end of its sentence.

    Items are not validated here; anything that is not an allergen word is
    dropped when classified, which is what removes OCR debris like an address.
    """
    sentence = re.split(r"[.\n]|\b(?:distributed|manufactured\s+by)\b", after, maxsplit=1)[0]
    return tuple(
        word.strip().lower()
        for word in re.split(r",|\band\b|\bor\b|&|/", sentence, flags=re.IGNORECASE)
        if word.strip() and len(word.strip()) < 40
    )


def parse(text: str | None) -> ParsedLabel:
    if not text or not text.strip():
        return ParsedLabel(ingredients=(), declared_allergens=())

    body = _LEADER.sub("", " ".join(text.split()))

    # Statements are cut from the end inward, so each sees only its own sentence.
    may_contain: tuple[str, ...] = ()
    precautions = list(_PRECAUTION.finditer(body))
    if precautions:
        # Labels often carry two: "may contain X" and "made in a facility with Y".
        for match in precautions:
            may_contain += _statement_words(body[match.end() :])
        body = body[: precautions[0].start()]

    declared: tuple[str, ...] = ()
    statement = _ALLERGEN_STATEMENT.search(body)
    if statement:
        declared = _statement_words(body[statement.end() :])
        body = body[: statement.start()]

    trailer = _TRAILER.search(body)
    if trailer:
        body = body[: trailer.start()]

    items = tuple(
        item for part in _split_top_level(body) if (item := _parse_item(part, 0)) is not None
    )
    return ParsedLabel(ingredients=items, declared_allergens=declared, may_contain=may_contain)
