"""A small markdown grammar for the legal documents, parsed into typed blocks.

The documents are the one place where wrong rendering is a legal problem, so
this parser is deliberately tiny and fatal: anything it does not recognise
raises rather than passing through. Parsing server-side means the web app
receives typed blocks and never needs `innerHTML`, a sanitiser, or a markdown
dependency — the whole class of injection bugs is absent rather than defended
against.

What it accepts:

- `## Heading` and `### Heading` (plain text, no inline markup)
- paragraphs: consecutive lines, joined with a space
- `- item` bullets, with continuation lines indented two spaces
- `Table: caption` followed by a pipe table with a `|---|` rule
- inline `**bold**` and `[text](href)`, where href is https://, mailto:, or
  an internal path

Everything else — a `#` or `####` heading, a literal `<` or `>`, an unbalanced
`**`, any other href scheme — is a `LegalTextError`.
"""

import re
from dataclasses import dataclass, field

# Sections are numbered in the heading text, so no ordered lists are needed.
HEADING = re.compile(r"^(?P<hashes>#+)\s+(?P<text>.+)$")
BULLET = re.compile(r"^-\s+(?P<text>.+)$")
TABLE_CAPTION = re.compile(r"^Table:\s+(?P<caption>.+)$")
TABLE_RULE = re.compile(r"^\|(\s*:?-+:?\s*\|)+$")
LINK = re.compile(r"\[(?P<text>[^\]\[]+)\]\((?P<href>[^)\s]+)\)")
ALLOWED_SCHEMES = ("https://", "mailto:")
# An internal path is a single slash followed by something that is not another
# slash or a backslash. "//evil.test" is a protocol-relative URL and "/\evil.test"
# is normalised to one by browsers: both leave the site while looking internal
# to a bare startswith("/"), which would bind them to routerLink. The documents
# are repository-controlled, so this is a lint today rather than a boundary —
# but it is the check the web app mirrors, and the parser is where the rule
# belongs.
INTERNAL_PATH = re.compile(r"^/(?![/\\]|%2[fF]|%5[cC])")


class LegalTextError(ValueError):
    """A legal document does not fit the grammar. Fatal at startup, by design."""


@dataclass(frozen=True)
class Span:
    text: str
    bold: bool = False
    href: str | None = None


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    anchor: str
    kind: str = "heading"


@dataclass(frozen=True)
class Paragraph:
    spans: list[Span]
    kind: str = "paragraph"


@dataclass(frozen=True)
class Bullets:
    items: list[list[Span]]
    kind: str = "bullets"


@dataclass(frozen=True)
class Table:
    header: list[str]
    rows: list[list[list[Span]]]
    caption: str | None = None
    kind: str = "table"


Block = Heading | Paragraph | Bullets | Table


@dataclass
class _Reader:
    """Lines with a cursor, so each construct consumes exactly what it owns."""

    lines: list[str]
    index: int = 0
    blocks: list[Block] = field(default_factory=list)

    def peek(self) -> str | None:
        return self.lines[self.index] if self.index < len(self.lines) else None

    def take(self) -> str:
        line = self.lines[self.index]
        self.index += 1
        return line


def anchor_for(text: str) -> str:
    """A stable id for a heading, for the table of contents and deep links."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def parse_spans(text: str) -> list[Span]:
    """Inline markup: **bold** and [text](href), in one pass, order preserved."""
    if "<" in text or ">" in text:
        raise LegalTextError(f"Literal angle bracket in legal text: {text!r}")
    if text.count("**") % 2:
        raise LegalTextError(f"Unbalanced ** in legal text: {text!r}")

    spans: list[Span] = []
    position = 0
    for match in LINK.finditer(text):
        spans.extend(_emphasis(text[position : match.start()]))
        href = match.group("href")
        if not href.startswith(ALLOWED_SCHEMES) and not INTERNAL_PATH.match(href):
            raise LegalTextError(f"Unsupported link target in legal text: {href!r}")
        spans.append(Span(text=match.group("text"), href=href))
        position = match.end()
    spans.extend(_emphasis(text[position:]))
    return [span for span in spans if span.text]


def _emphasis(text: str) -> list[Span]:
    """Bold runs within one link-free segment.

    Emphasis may not span a link. The whole-string balance check above counts
    every ``**`` in the line, so ``a **b [x](/y) c** d`` passes it while each
    segment here sees an odd count — which would silently invert the bolding
    from the link onwards. In a grammar whose contract is that anything
    unrecognised raises, rendering a legal document wrongly is the one outcome
    that must not happen quietly.
    """
    if text.count("**") % 2:
        raise LegalTextError(f"Emphasis crosses a link in legal text: {text!r}")
    return [
        Span(text=part, bold=bool(index % 2)) for index, part in enumerate(text.split("**")) if part
    ]


def _heading(reader: _Reader, line: str) -> Heading:
    match = HEADING.match(line)
    assert match is not None
    level = len(match.group("hashes"))
    if level not in (2, 3):
        raise LegalTextError(
            f"Legal documents use ## and ### only; the title comes from the registry: {line!r}"
        )
    text = match.group("text").strip()
    if "**" in text or "[" in text:
        raise LegalTextError(f"Headings are plain text: {line!r}")
    if "<" in text or ">" in text:
        raise LegalTextError(f"Literal angle bracket in legal text: {text!r}")
    return Heading(level=level, text=text, anchor=anchor_for(text))


def _bullets(reader: _Reader) -> Bullets:
    items: list[list[Span]] = []
    current: str | None = None
    while (line := reader.peek()) is not None and (BULLET.match(line) or line.startswith("  ")):
        line = reader.take()
        bullet = BULLET.match(line)
        if bullet:
            if current is not None:
                items.append(parse_spans(current))
            current = bullet.group("text").strip()
        else:
            # A continuation line belongs to the bullet above it.
            if current is None:
                raise LegalTextError(f"Indented line outside a bullet: {line!r}")
            current = f"{current} {line.strip()}"
    if current is not None:
        items.append(parse_spans(current))
    return Bullets(items=items)


def _row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _plain(text: str, what: str) -> str:
    """Header cells and captions reach the client as strings, not spans.

    They therefore never pass through `parse_spans`, so none of its refusals
    apply to them. Rather than leave one unchecked path through a parser whose
    whole value is that it is fatal, hold them to the stricter rule headings
    already follow: plain text, no markup.
    """
    if "<" in text or ">" in text:
        raise LegalTextError(f"Literal angle bracket in {what}: {text!r}")
    if "**" in text or "[" in text:
        raise LegalTextError(f"Table {what} is plain text: {text!r}")
    return text


def _table(reader: _Reader, caption: str | None) -> Table:
    header_line = reader.take()
    rule = reader.peek()
    if rule is None or not TABLE_RULE.match(rule):
        raise LegalTextError(f"Table without a |---| rule after its header: {header_line!r}")
    reader.take()
    header = [_plain(cell, "header cell") for cell in _row(header_line)]
    if caption is not None:
        caption = _plain(caption, "caption")
    rows: list[list[list[Span]]] = []
    while (line := reader.peek()) is not None and line.startswith("|"):
        cells = _row(reader.take())
        if len(cells) != len(header):
            raise LegalTextError(f"Table row does not match its header: {line!r}")
        rows.append([parse_spans(cell) for cell in cells])
    if not rows:
        raise LegalTextError(f"Table with no rows: {header_line!r}")
    return Table(header=header, rows=rows, caption=caption)


def parse(text: str) -> list[Block]:
    """Every block of a document, in order. Raises on anything unrecognised."""
    reader = _Reader(lines=text.replace("\r\n", "\n").split("\n"))
    while (line := reader.peek()) is not None:
        if not line.strip():
            reader.take()
            continue
        if HEADING.match(line):
            reader.blocks.append(_heading(reader, reader.take()))
            continue
        if BULLET.match(line):
            reader.blocks.append(_bullets(reader))
            continue
        caption_match = TABLE_CAPTION.match(line)
        if caption_match:
            reader.take()
            # A blank line between the caption and its table reads better in the
            # source and means nothing here.
            while (following := reader.peek()) is not None and not following.strip():
                reader.take()
            if following is None or not following.startswith("|"):
                raise LegalTextError(f"Table caption without a table: {line!r}")
            reader.blocks.append(_table(reader, caption_match.group("caption").strip()))
            continue
        if line.startswith("|"):
            reader.blocks.append(_table(reader, None))
            continue
        paragraph: list[str] = []
        while (line := reader.peek()) is not None and line.strip() and not _starts_block(line):
            paragraph.append(reader.take().strip())
        reader.blocks.append(Paragraph(spans=parse_spans(" ".join(paragraph))))
    if not reader.blocks:
        raise LegalTextError("Legal document is empty")
    return reader.blocks


def _starts_block(line: str) -> bool:
    return bool(
        HEADING.match(line) or BULLET.match(line) or TABLE_CAPTION.match(line)
    ) or line.startswith("|")
