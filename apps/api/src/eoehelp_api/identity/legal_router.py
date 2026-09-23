"""The legal documents, readable by anyone.

Unauthenticated on purpose: the terms have to be readable before an account
exists, and a patient must be able to read the version they agreed to without
signing in. Nothing here touches patient data — there is no session, no
repository, and no patient scope.
"""

from dataclasses import asdict

from fastapi import APIRouter, Path, Request, Response

from eoehelp_api.core import ratelimit
from eoehelp_api.core.errors import NotFoundError
from eoehelp_api.identity import documents
from eoehelp_api.identity.documents import LegalDocument
from eoehelp_api.identity.enums import ReviewStatus
from eoehelp_api.identity.legal_schemas import LegalDocumentRead, LegalDocumentSummary

router = APIRouter(prefix="/legal", tags=["legal"])

# Reviewed text is immutable, so it caches well. A draft changes during review,
# and a cached draft is confusing to everyone reading it.
REVIEWED_CACHE = "public, max-age=3600"
DRAFT_CACHE = "no-store"


def _summary(document: LegalDocument) -> LegalDocumentSummary:
    return LegalDocumentSummary(
        id=document.version,
        consent_type=document.consent_type,
        slug=document.slug,
        title=document.title,
        effective_on=document.effective_on,
        review_status=document.review_status,
        content_sha256=document.sha256,
        superseded_by=documents.superseded_by(document),
    )


@router.get("/documents", response_model=list[LegalDocumentSummary])
@ratelimit.route_limit(ratelimit.LEGAL_DOCUMENTS, "legal_documents")
async def list_documents(request: Request, response: Response) -> list[LegalDocumentSummary]:
    """Every document currently in force, without its text."""
    current = documents.current_documents()
    response.headers["Cache-Control"] = (
        REVIEWED_CACHE
        if all(d.review_status is ReviewStatus.ATTORNEY_REVIEWED for d in current)
        else DRAFT_CACHE
    )
    return [_summary(document) for document in current]


@router.get("/documents/{document_id}", response_model=LegalDocumentRead)
@ratelimit.route_limit(ratelimit.LEGAL_DOCUMENTS, "legal_documents")
async def read_document(
    request: Request,
    response: Response,
    # Bounded and shaped like every other path parameter in the codebase, so a
    # crafted id is refused by the contract rather than by a registry miss.
    document_id: str = Path(max_length=64, pattern=r"^[a-z0-9-]+$"),
) -> LegalDocumentRead:
    """One document by version id ("tos-2026-09"), slug ("terms"), or digest.

    A 64-character lowercase hex id names exact bytes and returns *that*
    revision, whatever has been published since. It is what a consent record
    stores, so this is the route that makes a consent legible to the person who
    gave it. A version id or a slug returns the current revision, as before.
    """
    resolved = documents.resolve(document_id)
    if resolved is None:
        raise NotFoundError("No such document.")

    document, revision = resolved.document, resolved.revision
    # The returned revision's status, not the version's: a draft is never
    # cached, including an older draft revision someone reached by digest.
    response.headers["Cache-Control"] = (
        REVIEWED_CACHE if revision.review_status is ReviewStatus.ATTORNEY_REVIEWED else DRAFT_CACHE
    )
    summary = _summary(document).model_dump()
    summary["content_sha256"] = revision.sha256
    summary["review_status"] = revision.review_status
    return LegalDocumentRead(
        **summary,
        current_content_sha256=document.sha256,
        # asdict, not __dict__: the spans inside a block are dataclasses too.
        blocks=[asdict(block) for block in documents.blocks_for(revision.sha256)],
    )
