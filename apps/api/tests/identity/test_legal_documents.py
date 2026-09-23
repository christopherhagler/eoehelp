"""The legal document registry: integrity, required clauses, and the draft gate."""

import importlib.util
import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from eoehelp_api.identity import documents
from eoehelp_api.identity.documents import TERMS_OF_SERVICE_VERSION
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
FORBIDDEN = (
    "safe food",
    "is safe to eat",
    "you should stop",
    "we recommend",
    "diagnose",
    # Prescriptive: telling someone to avoid a food is advice, not a description
    # of their own record.
    "avoid ",
)


def revision_of(version: str) -> str:
    """The current revision's digest for a version id, for readability below."""
    document = documents.by_id(version)
    assert document is not None
    return document.sha256


def headings(version: str) -> list[str]:
    return [
        block.text.lower()
        for block in documents.blocks_for(revision_of(version))
        if isinstance(block, Heading)
    ]


class TestRegistry:
    def test_every_document_is_present_and_matches_its_digest(self) -> None:
        """The tamper check, and the packaging check: a wheel without the files
        fails here rather than serving nothing to a patient about to consent."""
        documents.verify_integrity()
        for document in documents.DOCUMENTS:
            for revision in document.revisions:
                path = document.path_for(revision.sha256)
                assert documents.digest_of_path(path) == revision.sha256

    def test_an_altered_document_fails_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The file no longer hashes to what the registry records."""
        # The file for revision 1 exists; only the recorded digest is wrong, so
        # this reaches the digest comparison rather than the missing-file branch.
        document = documents.DOCUMENTS[0]
        altered = replace(
            document,
            revisions=(
                replace(document.revisions[0], sha256="0" * 64),
                *document.revisions[1:],
            ),
        )
        monkeypatch.setattr(documents, "DOCUMENTS", (altered,))
        with pytest.raises(RuntimeError, match="does not match its recorded digest"):
            documents.verify_integrity()

    def test_a_missing_document_fails_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        missing = replace(documents.DOCUMENTS[0], version="tos-1999-01")
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
        """The router accepts either, so the two sets must stay disjoint.

        Slugs are deliberately *not* unique across the registry: every version
        of the terms shares the slug "terms", because that is the public URL
        and it has to keep meaning "the one in force". What must hold is that
        one consent type never carries two different slugs, which would leave
        the footer and the onboarding dialog pointing at different documents.
        """
        versions = [document.version for document in documents.DOCUMENTS]
        slugs = {document.slug for document in documents.DOCUMENTS}
        assert len(set(versions)) == len(versions)
        assert not set(versions) & slugs
        assert all(VERSION_PATTERN.match(version) for version in versions)

        by_type: dict[ConsentType, set[str]] = {}
        for document in documents.DOCUMENTS:
            by_type.setdefault(document.consent_type, set()).add(document.slug)
        assert all(len(found) == 1 for found in by_type.values()), by_type

    def test_a_slug_always_resolves_to_the_document_in_force(self) -> None:
        """The failure this guards is subtle and expensive: a patient reads the
        superseded wording at /terms while onboarding records the digest of the
        new one against their consent."""
        superseded = replace(
            documents.current_for(ConsentType.TERMS_OF_SERVICE),
            version="tos-2020-01",
            effective_on=date(2020, 1, 1),
        )
        registry = (superseded, *documents.DOCUMENTS)

        with patch.object(documents, "DOCUMENTS", registry):
            in_force = documents.by_id("terms")
            assert in_force is not None
            assert in_force.version == TERMS_OF_SERVICE_VERSION

            # The version id stays a permanent link to the exact old wording.
            by_version = documents.by_id("tos-2020-01")
            assert by_version is not None
            assert by_version.version == "tos-2020-01"

            assert documents.superseded_by(superseded) == TERMS_OF_SERVICE_VERSION

    def test_nothing_is_superseded_yet(self) -> None:
        assert all(documents.superseded_by(d) is None for d in documents.DOCUMENTS)


class TestRevisions:
    """A revision is the unit of evidence: (consent_type, version, digest).

    These assert the properties `verify_integrity` enforces, so a failure names
    the specific rule that broke rather than "startup raised".
    """

    def test_digests_are_unique_across_the_whole_registry(self) -> None:
        """A digest is what a consent row stores, so it must name one revision."""
        digests = [
            revision.sha256 for document in documents.DOCUMENTS for revision in document.revisions
        ]
        assert len(set(digests)) == len(digests)

    def test_every_document_has_at_least_one_revision(self) -> None:
        assert all(document.revisions for document in documents.DOCUMENTS)

    def test_the_current_revision_is_the_newest_one(self) -> None:
        for document in documents.DOCUMENTS:
            assert document.sha256 == document.revisions[-1].sha256
            assert document.review_status == document.revisions[-1].review_status

    def test_the_file_name_carries_the_revision_number(self) -> None:
        for document in documents.DOCUMENTS:
            assert document.path.name == f"{document.version}.r{len(document.revisions)}.md"

    def test_a_reviewed_revision_may_not_be_superseded_under_the_same_id(self) -> None:
        """Publishing rule 3. Reviewed bytes are frozen: revising them under an
        id patients already agreed to is the failure this whole change exists
        to prevent, so it must stop the boot."""
        document = documents.current_for(ConsentType.TERMS_OF_SERVICE)
        revised = replace(
            document,
            revisions=(
                documents.Revision(sha256="a" * 64, review_status=ReviewStatus.ATTORNEY_REVIEWED),
                *document.revisions,
            ),
        )
        with (
            patch.object(documents, "DOCUMENTS", (revised,)),
            pytest.raises(RuntimeError, match="frozen"),
        ):
            documents.verify_integrity()


class TestResolve:
    def test_a_slug_and_a_version_give_the_current_revision(self) -> None:
        terms = documents.current_for(ConsentType.TERMS_OF_SERVICE)
        for document_id in (terms.slug, terms.version):
            resolved = documents.resolve(document_id)
            assert resolved is not None
            assert resolved.revision.sha256 == terms.sha256

    def test_a_digest_gives_exactly_that_revision(self) -> None:
        terms = documents.current_for(ConsentType.TERMS_OF_SERVICE)
        resolved = documents.resolve(terms.sha256)
        assert resolved is not None
        assert resolved.document.version == terms.version
        assert resolved.revision.sha256 == terms.sha256

    @pytest.mark.parametrize(
        "document_id",
        [
            "nope",
            "f" * 64,
            # Uppercase: every producer emits lowercase, and accepting both
            # would make a digest two ids for one revision.
            "450B7D1254EC252DCD2D11023EC6A4CC3B6312E0C05F5EB8FD5B3F6B9D9FBD34",
        ],
    )
    def test_an_unknown_id_resolves_to_nothing(self, document_id: str) -> None:
        assert documents.resolve(document_id) is None


class TestContent:
    @pytest.mark.parametrize(
        ("version", "digest"),
        [
            (document.version, revision.sha256)
            for document in documents.DOCUMENTS
            for revision in document.revisions
        ],
        ids=lambda value: value[:12],
    )
    def test_every_revision_parses_and_starts_at_level_two(self, version: str, digest: str) -> None:
        blocks = documents.blocks_for(digest)
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
        terms = " ".join(
            documents.text_for(documents.current_for(ConsentType.TERMS_OF_SERVICE).sha256)
            .lower()
            .split()
        )
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
        terms = documents.text_for(documents.current_for(ConsentType.TERMS_OF_SERVICE).sha256)
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
        assert phrase not in documents.text_for(document.sha256).lower()

    @pytest.mark.parametrize("document", documents.DOCUMENTS, ids=lambda d: d.version)
    def test_a_reviewed_document_may_not_contain_a_placeholder(self, document) -> None:
        """Drafts may; a document marked reviewed may not, because a placeholder
        means nobody filled in the operator's address or venue."""
        if document.review_status is ReviewStatus.ATTORNEY_REVIEWED:
            text = "\n".join(documents.text_for(revision.sha256) for revision in document.revisions)
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


class TestArbitrationClause:
    """Section 18 is enforceable only as a whole.

    Each sub-clause is a separate reason a court would refuse the section: drop
    the fee allocation or the severance mechanics and what survives is worse
    than having written nothing. A tidy-up is exactly how one goes missing, so
    each is asserted on its own.
    """

    SUBCLAUSES = (
        "18.1",
        "18.2",
        "18.3",
        "18.4",
        "18.5",
        "18.6",
        "18.7",
        "18.8",
        "18.9",
    )

    @pytest.mark.parametrize("subclause", SUBCLAUSES)
    def test_every_sub_clause_has_its_own_heading(self, subclause: str) -> None:
        """Asserted against parsed headings, not the raw text.

        A substring check does not bind: five of these numbers also appear in
        cross-references inside other sub-sections — 18.6 names 18.4 twice, for
        instance — so deleting the class-action waiver outright would leave a
        substring assertion green. The two clauses the plan calls load-bearing
        are exactly the two that were unguarded.
        """
        found = headings(documents.TERMS_OF_SERVICE_VERSION)
        assert any(heading.startswith(f"{subclause} ") for heading in found), (
            f"section {subclause} has no heading of its own in the terms"
        )


class TestRegistryMatchesTheMigration:
    def test_published_revisions_match_migration_0006(self) -> None:
        """The registry and the migration are two records of the same fact.

        `verify_integrity` catches a document edited without its digest. It
        cannot catch a document edited *together with* its digest under the
        same id — which is precisely what re-points existing consent rows at
        wording nobody agreed to. The migration's literals are the independent
        copy, and at runtime the ledger rows it wrote are the durable one.
        """
        spec = importlib.util.spec_from_file_location(
            "migration_0006",
            Path(__file__).parents[2] / "alembic" / "versions" / "0006_consent_document_digest.py",
        )
        assert spec is not None
        assert spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        # This direction only: every revision the migration published must
        # still mean the same bytes in this build. The reverse would force a
        # document published in 2027 into a migration that ran years earlier.
        published = {
            (consent_type.value, version, digest)
            for consent_type, version, digest in documents.published_revisions()
        }
        for consent_type, version, digest, _published_on in migration.PUBLISHED_REVISIONS:
            if not any(version == known for _, known, _ in published):
                continue  # superseded and removed from the registry
            assert (consent_type, version, digest) in published, (
                f"{version} differs between the registry and migration 0006. If the "
                "text changed, publish a new revision rather than editing one patients "
                "have already agreed to."
            )
