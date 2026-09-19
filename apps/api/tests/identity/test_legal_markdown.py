"""The legal markdown grammar: what it accepts, and what it refuses."""

import pytest

from eoehelp_api.identity.legal_markdown import (
    Bullets,
    Heading,
    LegalTextError,
    Paragraph,
    Table,
    parse,
    parse_spans,
)


class TestBlocks:
    def test_headings_carry_a_level_and_an_anchor(self) -> None:
        blocks = parse("## 1. Who runs eoehelp\n\n### 18.7 Opting out\n")
        assert [(b.level, b.anchor) for b in blocks if isinstance(b, Heading)] == [
            (2, "1-who-runs-eoehelp"),
            (3, "18-7-opting-out"),
        ]

    def test_a_paragraph_joins_its_lines(self) -> None:
        [block] = parse("One line\nand the next.\n")
        assert isinstance(block, Paragraph)
        assert block.spans[0].text == "One line and the next."

    def test_bullets_take_their_continuation_lines(self) -> None:
        [block] = parse("- first item\n  continued here\n- second item\n")
        assert isinstance(block, Bullets)
        assert [span.text for item in block.items for span in item] == [
            "first item continued here",
            "second item",
        ]

    def test_a_table_with_a_caption(self) -> None:
        [block] = parse("Table: What is stored\n\n| A | B |\n|---|---|\n| one | two |\n")
        assert isinstance(block, Table)
        assert block.caption == "What is stored"
        assert block.header == ["A", "B"]
        assert block.rows[0][0][0].text == "one"

    def test_a_table_without_a_caption(self) -> None:
        [block] = parse("| A | B |\n|---|---|\n| one | two |\n")
        assert isinstance(block, Table)
        assert block.caption is None


class TestSpans:
    def test_bold_and_links(self) -> None:
        spans = parse_spans("Read the **terms** at [privacy](/privacy) or [site](https://x.test).")
        assert [(s.text, s.bold, s.href) for s in spans] == [
            ("Read the ", False, None),
            ("terms", True, None),
            (" at ", False, None),
            ("privacy", False, "/privacy"),
            (" or ", False, None),
            ("site", False, "https://x.test"),
            (".", False, None),
        ]

    def test_a_mailto_link_is_allowed(self) -> None:
        [span] = parse_spans("[write](mailto:privacy@eoehelp.org)")
        assert span.href == "mailto:privacy@eoehelp.org"


class TestRefusals:
    @pytest.mark.parametrize(
        ("source", "reason"),
        [
            ("# Title\n", "a level-1 heading: the title comes from the registry"),
            ("#### Too deep\n", "a level-4 heading"),
            ("Unbalanced **bold\n", "an unbalanced emphasis marker"),
            ("[x](javascript:alert(1))\n", "a script link"),
            ("[x](http://insecure.test)\n", "a plain http link"),
            ("A literal < bracket\n", "raw markup"),
            ("## Heading with <b>\n", "raw markup in a heading"),
            ("| A | B |\n| one | two |\n", "a table with no rule row"),
            ("Table: Orphan\n\nNot a table\n", "a caption with no table"),
            ("| A | B |\n|---|---|\n", "a table with no rows"),
            ("", "an empty document"),
        ],
    )
    def test_the_grammar_refuses(self, source: str, reason: str) -> None:
        with pytest.raises(LegalTextError):
            parse(source)
