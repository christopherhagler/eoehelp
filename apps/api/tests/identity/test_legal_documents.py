"""The legal document registry: integrity, required clauses, and the draft gate."""

import re

import pytest

from eoehelp_api.identity import documents
from eoehelp_api.identity.enums import ConsentType, ReviewStatus
from eoehelp_api.identity.legal_markdown import Heading

VERSION_PATTERN = re.compile(r"^[a-z]+-\d{4}-\d{2}$")

# Sections Washington's My Health My Data Act requires the consumer health data
# policy to contain. Each is asserted separately: a missing one is a separate
# failure to comply, not a stylistic difference.
MHMD_SECTIONS = (
    "collect",
    "comes from",
    "share",
    "third parties",
    "rights",
    "consent",
    "geofencing",
    "contact",
)

# The clauses the terms exist to carry. A tidy-up that drops one of these is
# what this test is for.
TOS_SECTIONS = (
    "assumption of risk",
    "disclaimer of warranties",
    "limitation of liability",
    "what this agreement does not do",
    "resolving a dispute",
)

# Phrasing that would make the product prescriptive or reassuring. A guard, not
# a proof, and cheap to keep.
FORBIDDEN = ("safe food", "is safe to eat", "you should stop", "we recommend", "diagnose")


def headings(version: str) -> list[str]:
    return [block.text.lower() for block in documents.blocks(version) if isinstance(block, Heading)]


class TestRegistry:
    def test_every_document_is_present_and_matches_its_digest(self) -> None:
        """The tamper check, and the packaging check: a wheel without the files
        fails here rather than serving nothing to a patient about to consent."""
        documents.verify_integrity()
        for document in documents.DOCUMENTS:
            assert documents.digest_of(document) == document.sha256

    def test_an_altered_document_fails_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        altered = documents.DOCUMENTS[0].__class__(
            **{**documents.DOCUMENTS[0].__dict__, "sha256": "0" * 64}
        )
        monkeypatch.setattr(documents, "DOCUMENTS", (altered,))
        with pytest.raises(RuntimeError, match="does not match its recorded digest"):
            documents.verify_integrity()

    def test_a_missing_document_fails_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        missing = documents.DOCUMENTS[0].__class__(
            **{**documents.DOCUMENTS[0].__dict__, "version": "tos-1999-01"}
        )
        monkeypatch.setattr(documents, "DOCUMENTS", (missing,))
        with pytest.raises(RuntimeError, match="is missing"):
            documents.verify_integrity()

    def test_every_required_consent_has_exactly_one_current_document(self) -> None:
        for consent_type in documents.REQUIRED_AT_ONBOARDING:
            assert documents.current_for(consent_type).consent_type is consent_type
        assert len(documents.current_documents()) == len(documents.REQUIRED_AT_ONBOARDING)

    def test_research_participation_has_no_document_yet(self) -> None:
        """Nothing can grant that consent today, and a document describing an
        export that does not exist would be untrue the day it shipped."""
        with pytest.raises(LookupError):
            documents.current_for(ConsentType.RESEARCH_PARTICIPATION)

    def test_ids_and_slugs_are_unique_and_never_collide(self) -> None:
        """The router accepts either, so the two sets must stay disjoint."""
        versions = [document.version for document in documents.DOCUMENTS]
        slugs = [document.slug for document in documents.DOCUMENTS]
        assert len(set(versions)) == len(versions)
        assert len(set(slugs)) == len(slugs)
        assert not set(versions) & set(slugs)
        assert all(VERSION_PATTERN.match(version) for version in versions)

    def test_nothing_is_superseded_yet(self) -> None:
        assert all(documents.superseded_by(d) is None for d in documents.DOCUMENTS)


class TestContent:
    @pytest.mark.parametrize("document", documents.DOCUMENTS, ids=lambda d: d.version)
    def test_every_document_parses_and_starts_at_level_two(self, document) -> None:
        blocks = documents.blocks(document.version)
        assert blocks
        first_heading = next(block for block in blocks if isinstance(block, Heading))
        assert first_heading.level == 2

    @pytest.mark.parametrize("section", MHMD_SECTIONS)
    def test_the_consumer_health_data_policy_covers_what_washington_requires(
        self, section: str
    ) -> None:
        found = headings(documents.CONSUMER_HEALTH_DATA_VERSION)
        assert any(section in heading for heading in found), f"missing section about {section}"

    @pytest.mark.parametrize("section", TOS_SECTIONS)
    def test_the_terms_carry_their_load_bearing_clauses(self, section: str) -> None:
        assert any(section in heading for heading in headings(documents.TERMS_OF_SERVICE_VERSION))

    def test_the_carve_out_names_what_cannot_be_waived(self) -> None:
        """An over-broad waiver invites a court to strike the whole section; the
        carve-out is what keeps the limits in sections 10 to 12 defensible."""
        # Line wrapping is a source detail; read it as the prose it is.
        terms = " ".join(documents.text(documents.TERMS_OF_SERVICE_VERSION).lower().split())
        for phrase in (
            "gross negligence",
            # Alabama's distinct cause of action, where its enforcement of
            # exculpatory clauses stops.
            "wantonness",
            "intentional misconduct",
            "my health my data act",
            "health breach notification rule",
        ):
            assert phrase in terms, f"the carve-out does not name {phrase}"

    def test_the_arbitration_clause_keeps_what_makes_it_enforceable(self) -> None:
        terms = documents.text(documents.TERMS_OF_SERVICE_VERSION)
        lowered = " ".join(terms.lower().split())
        # The conspicuous notice comes before section 1, not below the fold.
        assert lowered.index("individual arbitration") < lowered.index("## 1.")
        assert "opt out" in lowered
        assert "30 days" in lowered
        assert "privacy@eoehelp.org" in terms
        assert "small claims" in lowered
        assert "9 u.s.c." in lowered
        assert "federal arbitration act" in lowered

    @pytest.mark.parametrize("document", documents.DOCUMENTS, ids=lambda d: d.version)
    @pytest.mark.parametrize("phrase", FORBIDDEN)
    def test_no_document_gives_advice(self, document, phrase: str) -> None:
        assert phrase not in documents.text(document.version).lower()

    @pytest.mark.parametrize("document", documents.DOCUMENTS, ids=lambda d: d.version)
    def test_a_reviewed_document_may_not_contain_a_placeholder(self, document) -> None:
        """Drafts may; a document marked reviewed may not, because a placeholder
        means nobody filled in the operator's address or venue."""
        if document.review_status is ReviewStatus.ATTORNEY_REVIEWED:
            text = documents.text(document.version)
            assert "[POSTAL ADDRESS]" not in text
            assert "[COUNTY]" not in text
            assert "[NORTHERN" not in text


class TestReviewGate:
    def test_production_refuses_to_serve_unreviewed_drafts(self) -> None:
        with pytest.raises(RuntimeError, match="not been reviewed by an attorney"):
            documents.enforce_review_status("production")

    @pytest.mark.parametrize("environment", ["local", "staging"])
    def test_other_environments_may_serve_drafts(self, environment: str) -> None:
        documents.enforce_review_status(environment)
