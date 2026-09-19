"""Versioned legal documents the patient agrees to, and their text.

"The patient consented" is not a defensible record on its own — consented to
*what text* is the question a regulator or a plaintiff asks. Every consent row
stores a version string from this registry **and the sha256 of the text**, so
the exact wording in force at the time can be reproduced years later.

Two rules follow, and the code enforces both:

1. **A published document's bytes never change.** A correction is a new file
   with a new version id. `verify_integrity` compares each file against the
   digest recorded here at startup, so editing a published document is a boot
   failure rather than a silent rewrite of what people agreed to.
2. **Bumping a version means existing patients are no longer covered** by the
   current document and must be re-prompted. That is the intended friction.

The documents in this package are **drafts written in-house**, not reviewed by
a lawyer. `enforce_review_status` refuses to start in production while that is
still true, which is how the launch gate ("attorney-reviewed terms, privacy
policy, and consumer health data disclosure") becomes something the deploy
checks rather than something we remember.
"""

import hashlib
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Final

from eoehelp_api.identity.enums import ConsentType, ReviewStatus
from eoehelp_api.identity.legal_markdown import Block, parse

LEGAL_DIRECTORY: Final = Path(__file__).parent / "legal"


@dataclass(frozen=True)
class LegalDocument:
    """One published version of one document."""

    consent_type: ConsentType
    # The public id, and what a consent row stores: "tos-2026-09".
    version: str
    # The stable public URL segment: "terms".
    slug: str
    title: str
    effective_on: date
    review_status: ReviewStatus
    # Of the file's bytes, lowercase hex. Pinned here so an edit is detectable.
    sha256: str

    @property
    def path(self) -> Path:
        return LEGAL_DIRECTORY / f"{self.version}.md"


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
        review_status=ReviewStatus.DRAFT,
        sha256="450b7d1254ec252dcd2d11023ec6a4cc3b6312e0c05f5eb8fd5b3f6b9d9fbd34",
    ),
    LegalDocument(
        consent_type=ConsentType.PRIVACY_POLICY,
        version=PRIVACY_POLICY_VERSION,
        slug="privacy",
        title="Privacy policy",
        effective_on=date(2026, 9, 19),
        review_status=ReviewStatus.DRAFT,
        sha256="6eb6642accabc882a2373c72ec44091983c4ba5abde130e7490940529430f41e",
    ),
    LegalDocument(
        consent_type=ConsentType.CONSUMER_HEALTH_DATA,
        version=CONSUMER_HEALTH_DATA_VERSION,
        slug="health-data",
        title="Consumer Health Data Privacy Policy",
        effective_on=date(2026, 9, 19),
        review_status=ReviewStatus.DRAFT,
        sha256="188a1cc1575cab899b2b9cec222a030592ebacf9d10015d1bf3a3be9cb648a9c",
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
    """A document by version id or by slug; ids and slugs are disjoint by test."""
    for document in DOCUMENTS:
        if document_id in (document.version, document.slug):
            return document
    return None


def superseded_by(document: LegalDocument) -> str | None:
    """The newer version of the same document, if this one is no longer current."""
    current = current_for(document.consent_type)
    return None if current.version == document.version else current.version


@cache
def text(version: str) -> str:
    document = by_id(version)
    if document is None:
        raise LookupError(f"No legal document with id {version!r}.")
    return document.path.read_text(encoding="utf-8")


@cache
def blocks(version: str) -> tuple[Block, ...]:
    """The parsed document. Immutable, so parsed once per process."""
    return tuple(parse(text(version)))


def digest_of(document: LegalDocument) -> str:
    return hashlib.sha256(document.path.read_bytes()).hexdigest()


def verify_integrity() -> None:
    """Every document exists, matches its digest, and parses. Called at startup.

    This is also the packaging check: the runtime image installs a wheel, and a
    missing `[tool.setuptools.package-data]` entry would ship without the
    documents while tests still pass from the source tree.
    """
    for document in DOCUMENTS:
        if not document.path.is_file():
            raise RuntimeError(
                f"Legal document {document.version} is missing at {document.path}. "
                "Check [tool.setuptools.package-data] in pyproject.toml."
            )
        actual = digest_of(document)
        if actual != document.sha256:
            raise RuntimeError(
                f"Legal document {document.version} does not match its recorded digest "
                f"({actual} != {document.sha256}). A published document's text must never "
                "change: publish a new version instead."
            )
        blocks(document.version)


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
