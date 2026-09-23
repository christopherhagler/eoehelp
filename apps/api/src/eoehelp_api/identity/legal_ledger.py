"""Reconciling the published-revision ledger with this build's registry.

Separate from the model it reads, so that importing the ORM class — which
`identity/consent.py` must do for its composite foreign key to resolve — does
not pull in the document registry, the markdown parser and every document file
behind them.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.identity import documents
from eoehelp_api.identity.legal_document import PublishedLegalDocument


async def verify_published_revisions(session: AsyncSession) -> None:
    """The build and the ledger must agree, in both directions. Called at startup.

    Fails closed on purpose. An evidence check that an outage can skip is not a
    control, and every route except /healthz and /legal is useless without the
    database anyway.

    Messages carry version ids and digests, both of which are public, and never
    anything from `consents`.
    """
    rows = (
        await session.execute(
            select(
                PublishedLegalDocument.consent_type,
                PublishedLegalDocument.version,
                PublishedLegalDocument.content_sha256,
            )
        )
    ).all()
    in_ledger = {(consent_type, version, digest) for consent_type, version, digest in rows}
    in_registry = set(documents.published_revisions())

    unserveable = in_ledger - in_registry
    if unserveable:
        raise RuntimeError(
            "The database records legal document revisions this build cannot produce: "
            + ", ".join(f"{version} ({digest})" for _, version, digest in sorted(unserveable))
            + ". A consent row may name one of them, so serving a different text under "
            "the same id would misrepresent what a patient agreed to. Restore the file "
            "and its registry entry, or roll back to the build that published it."
        )

    unpublished = in_registry - in_ledger
    if unpublished:
        raise RuntimeError(
            "These legal document revisions are in the registry but were never published: "
            + ", ".join(f"{version} ({digest})" for _, version, digest in sorted(unpublished))
            + ". Publishing text requires a migration that inserts it into legal_documents, "
            "so that what was published is recorded somewhere a later commit cannot rewrite."
        )
