"""Versioned legal documents the patient agrees to, and their text.

"The patient consented" is not a defensible record on its own — consented to
*what text* is the question a regulator or a plaintiff asks. Every consent row
stores a version string from this registry **and the sha256 of the text**, so
the exact wording in force at the time can be reproduced years later.

The unit of evidence is a **revision**: `(consent_type, version, sha256)`. A
revision is published by a migration inserting it into the `legal_documents`
ledger, and `consents` carries a foreign key to that ledger, so a consent row
can only ever name bytes the database has on record as published.

Four publishing rules, and the code enforces them:

1. **A material change is a new version id.** New rights or obligations, or
   wording with a different meaning: `tos-2026-09` becomes `tos-2027-03`.
   Existing patients are no longer covered and must be re-prompted. That is the
   intended friction.
2. **A correction to a draft is a new revision of the same version id.** A
   draft is corrected constantly while it is being reviewed, and churning the
   public id for each typo would churn ids patients see. Each revision has its
   own file, its own digest and its own ledger row, and a consent pinned to an
   earlier revision keeps resolving to that revision's bytes.
3. **A reviewed revision is frozen.** Once a revision is attorney-reviewed no
   further revision may be added under that version id; rule 1 applies instead.
   `verify_integrity` checks this, because a reviewed revision that is not the
   newest means reviewed bytes were replaced under an id patients already
   agreed to.
4. **Retention.** A reviewed revision's file stays here permanently. A draft
   revision's file may be retired only when no consent references it, which the
   foreign key makes a fact rather than a promise.

To publish: add the file, add the `Revision`, add a migration that inserts the
ledger row, and run it. `verify_integrity` catches a file that does not match
its recorded digest; `verify_published_revisions` catches a build whose registry
disagrees with the ledger, which is the failure the digest alone cannot see —
editing a file and its recorded digest in the same commit.

The documents in this package are **drafts written in-house**, not reviewed by
a lawyer. `enforce_review_status` refuses to start in production while that is
still true, which is how the launch gate ("attorney-reviewed terms, privacy
policy, and consumer health data disclosure") becomes something the deploy
checks rather than something we remember.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Final

from eoehelp_api.identity.enums import ConsentType, ReviewStatus
from eoehelp_api.identity.legal_markdown import Block, parse

LEGAL_DIRECTORY: Final = Path(__file__).parent / "legal"


@dataclass(frozen=True)
class Revision:
    """One published set of bytes for a version.

    Review status belongs here rather than on the document: an attorney reviews
    particular words, and a patient reading an earlier revision should see the
    notice that was true of the bytes in front of them.
    """

    # Of the file's bytes, lowercase hex. Pinned so an edit is detectable.
    sha256: str
    review_status: ReviewStatus


@dataclass(frozen=True)
class LegalDocument:
    """One published version of one document, with every revision of it."""

    consent_type: ConsentType
    # The public id, and what a consent row stores: "tos-2026-09".
    version: str
    # The stable public URL segment: "terms".
    slug: str
    title: str
    effective_on: date
    # Oldest first, never empty. The last entry is the current text; earlier
    # ones are bytes a consent row may still name.
    revisions: tuple[Revision, ...]

    @property
    def current(self) -> Revision:
        return self.revisions[-1]

    @property
    def sha256(self) -> str:
        """The current revision's digest, which is what onboarding records."""
        return self.current.sha256

    @property
    def review_status(self) -> ReviewStatus:
        return self.current.review_status

    def path_for(self, sha256: str) -> Path:
        """The file holding one revision's bytes: <version>.r<n>.md, n from 1."""
        for index, revision in enumerate(self.revisions, start=1):
            if revision.sha256 == sha256:
                return LEGAL_DIRECTORY / f"{self.version}.r{index}.md"
        raise LookupError(f"{self.version} has no revision {sha256!r}.")

    @property
    def path(self) -> Path:
        return self.path_for(self.sha256)


@dataclass(frozen=True)
class ResolvedRevision:
    """A document and the particular revision of it that was asked for."""

    document: LegalDocument
    revision: Revision


TERMS_OF_SERVICE_VERSION: Final = "tos-2026-09"
PRIVACY_POLICY_VERSION: Final = "privacy-2026-09"

# Washington's My Health My Data Act requires a separate, specific consumer
# health data disclosure with its own affirmative consent. It cannot be bundled
# into the privacy policy, and WA carries a private right of action, so this is
# tracked as its own document rather than a clause in another one.
CONSUMER_HEALTH_DATA_VERSION: Final = "chd-2026-09"

# Oldest first per consent type. Research participation deliberately has no
# document: nothing can grant that consent yet, and the export it would describe
# is a later milestone, so `current_for` raises for it.
DOCUMENTS: Final[tuple[LegalDocument, ...]] = (
    LegalDocument(
        consent_type=ConsentType.TERMS_OF_SERVICE,
        version=TERMS_OF_SERVICE_VERSION,
        slug="terms",
        title="Terms of service",
        effective_on=date(2026, 9, 19),
        revisions=(
            Revision(
                sha256="450b7d1254ec252dcd2d11023ec6a4cc3b6312e0c05f5eb8fd5b3f6b9d9fbd34",
                review_status=ReviewStatus.DRAFT,
            ),
        ),
    ),
    LegalDocument(
        consent_type=ConsentType.PRIVACY_POLICY,
        version=PRIVACY_POLICY_VERSION,
        slug="privacy",
        title="Privacy policy",
        effective_on=date(2026, 9, 19),
        revisions=(
            Revision(
                sha256="6eb6642accabc882a2373c72ec44091983c4ba5abde130e7490940529430f41e",
                review_status=ReviewStatus.DRAFT,
            ),
        ),
    ),
    LegalDocument(
        consent_type=ConsentType.CONSUMER_HEALTH_DATA,
        version=CONSUMER_HEALTH_DATA_VERSION,
        slug="health-data",
        title="Consumer Health Data Privacy Policy",
        effective_on=date(2026, 9, 19),
        revisions=(
            Revision(
                sha256="188a1cc1575cab899b2b9cec222a030592ebacf9d10015d1bf3a3be9cb648a9c",
                review_status=ReviewStatus.DRAFT,
            ),
        ),
    ),
)

# Required to hold an account. Research participation is deliberately absent: it
# is a separate, specific, reversible decision and must never be a condition of
# using the product.
REQUIRED_AT_ONBOARDING: Final[tuple[ConsentType, ...]] = (
    ConsentType.TERMS_OF_SERVICE,
    ConsentType.PRIVACY_POLICY,
    ConsentType.CONSUMER_HEALTH_DATA,
)

# v1 is adults-only. Under-13 accounts trigger COPPA and verifiable parental
# consent, and 13-17 raises its own questions, so the launch gate is 18+. A
# pediatric module is a deliberate later milestone with PEESS® permission and a
# revisit of the birth_year precision decision.
MINIMUM_AGE_YEARS: Final = 18


def current_for(consent_type: ConsentType) -> LegalDocument:
    """The document in force for a consent type, newest by effective date.

    Raises for a type with no document, rather than inventing a version: the
    first attempt to record a research consent must fail loudly until the
    research document exists.
    """
    documents = [d for d in DOCUMENTS if d.consent_type is consent_type]
    if not documents:
        raise LookupError(f"No legal document exists for {consent_type.value}.")
    return max(documents, key=lambda document: document.effective_on)


def current_documents() -> tuple[LegalDocument, ...]:
    """One document per type that has one, in registry order."""
    types = dict.fromkeys(document.consent_type for document in DOCUMENTS)
    return tuple(current_for(consent_type) for consent_type in types)


def by_id(document_id: str) -> LegalDocument | None:
    """A document by version id, or the current document for a slug.

    The two halves mean different things and must not be collapsed into one
    scan of the registry. A version id is a permanent link to exact wording:
    it is what a consent record names, and it keeps resolving to the same
    bytes forever. A slug is the public URL behind the footer, the sign-in
    page and the onboarding dialog, and it has to mean "whatever is in force
    now" — otherwise the moment a second version is published, a patient reads
    superseded wording while `current_for` records the new digest against
    their consent.

    Registry order therefore decides nothing here; effective date does.
    """
    for document in DOCUMENTS:
        if document_id == document.version:
            return document

    for consent_type in dict.fromkeys(document.consent_type for document in DOCUMENTS):
        current = current_for(consent_type)
        if document_id == current.slug:
            return current
    return None


def superseded_by(document: LegalDocument) -> str | None:
    """The newer version of the same document, if this one is no longer current."""
    current = current_for(document.consent_type)
    return None if current.version == document.version else current.version


DIGEST_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")


def resolve(document_id: str) -> ResolvedRevision | None:
    """A document id, which may name a version, a slug, or exact bytes.

    A 64-character lowercase hex id is a content digest and resolves to *that*
    revision, whatever has been published since. Anything else goes through
    `by_id`, whose version-versus-slug distinction is unchanged, and yields the
    current revision. A version id or slug that was itself 64 lowercase hex
    characters would be shadowed by the digest branch; nothing enforces that it
    is not, because nothing would name a document that way.

    This is what makes a consent record legible: the digest it stores is a URL
    that returns the words that were on the screen.
    """
    if DIGEST_PATTERN.match(document_id):
        for document in DOCUMENTS:
            for revision in document.revisions:
                if revision.sha256 == document_id:
                    return ResolvedRevision(document=document, revision=revision)
        return None

    found = by_id(document_id)
    return None if found is None else ResolvedRevision(found, found.current)


def published_revisions() -> tuple[tuple[ConsentType, str, str], ...]:
    """Every revision this build can serve, as the ledger records them."""
    return tuple(
        (document.consent_type, document.version, revision.sha256)
        for document in DOCUMENTS
        for revision in document.revisions
    )


@cache
def text_for(sha256: str) -> str:
    """One revision's bytes, keyed by digest rather than by version.

    Keying by version was part of the original defect: it left the bytes
    un-nameable, so there was no way to ask for the text a consent row records.
    """
    # The digest lookup directly, not through `resolve`: `resolve` also accepts
    # a slug or a version id, and passing one here would find a document and
    # then fail inside `path_for` with a message about a revision that was never
    # asked for.
    for document in DOCUMENTS:
        for revision in document.revisions:
            if revision.sha256 == sha256:
                return document.path_for(sha256).read_text(encoding="utf-8")
    raise LookupError(f"No legal document revision with digest {sha256!r}.")


@cache
def blocks_for(sha256: str) -> tuple[Block, ...]:
    """The parsed revision. Immutable, so parsed once per process."""
    return tuple(parse(text_for(sha256)))


def digest_of_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_integrity() -> None:
    """Every revision exists, matches its digest, and parses. Called at startup.

    This is also the packaging check: the runtime image installs a wheel, and a
    missing `[tool.setuptools.package-data]` entry would ship without the
    documents while tests still pass from the source tree.

    What it cannot catch is a file edited together with the digest recorded
    here, because both travel in the same commit. That is what the ledger and
    `verify_published_revisions` are for.
    """
    # Registry shape first, before any file is read: these are statements about
    # what was published, and they should fail on their own terms rather than
    # as a confusing digest mismatch.
    seen: dict[str, str] = {}
    for document in DOCUMENTS:
        if not document.revisions:
            raise RuntimeError(f"Legal document {document.version} has no revisions.")

        for index, revision in enumerate(document.revisions):
            if revision.sha256 in seen:
                raise RuntimeError(
                    f"Two registry entries share the digest {revision.sha256}: "
                    f"{seen[revision.sha256]} and {document.version}. A digest must name "
                    "exactly one revision, because that is what a consent row stores."
                )
            seen[revision.sha256] = document.version

            # Publishing rule 3: reviewed bytes are frozen. A reviewed revision
            # that is not the newest means text an attorney signed off was
            # replaced under an id patients had already agreed to.
            is_newest = index == len(document.revisions) - 1
            if revision.review_status is ReviewStatus.ATTORNEY_REVIEWED and not is_newest:
                raise RuntimeError(
                    f"{document.version} has a reviewed revision ({revision.sha256}) that is "
                    "not its newest. A reviewed revision is frozen: publish a new version id "
                    "instead of revising it."
                )

    for document in DOCUMENTS:
        for revision in document.revisions:
            path = document.path_for(revision.sha256)
            if not path.is_file():
                raise RuntimeError(
                    f"Legal document {document.version} is missing at {path}. "
                    "Check [tool.setuptools.package-data] in pyproject.toml."
                )
            actual = digest_of_path(path)
            if actual != revision.sha256:
                raise RuntimeError(
                    f"Legal document {document.version} does not match its recorded digest "
                    f"({actual} != {revision.sha256}). A published revision's text must "
                    "never change: publish a new revision instead."
                )
            blocks_for(revision.sha256)


def enforce_review_status(environment: str) -> None:
    """Refuse to serve unreviewed drafts to real patients.

    Launch gate item 5 requires attorney-reviewed terms, privacy policy, and
    consumer health data disclosure. A checklist is not a control; this is.
    """
    if environment != "production":
        return
    drafts = [
        current_for(consent_type).version
        for consent_type in REQUIRED_AT_ONBOARDING
        if current_for(consent_type).review_status is ReviewStatus.DRAFT
    ]
    if drafts:
        raise RuntimeError(
            "These legal documents have not been reviewed by an attorney and cannot be "
            f"served in production: {', '.join(drafts)}. See docs/adr/0011-legal-documents.md."
        )
