"""The legal documents, readable by anyone.

Unauthenticated on purpose: the terms have to be readable before an account
exists, and a patient must be able to read the version they agreed to without
signing in. Nothing here touches patient data — there is no session, no
repository, and no patient scope.
"""

from dataclasses import asdict

from fastapi import APIRouter, Request, Response

from eoehelp_api.core import ratelimit
from eoehelp_api.core.errors import NotFoundError
from eoehelp_api.core.ratelimit import limiter
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
@limiter.limit(ratelimit.LEGAL_DOCUMENTS)
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
@limiter.limit(ratelimit.LEGAL_DOCUMENTS)
async def read_document(
    request: Request, response: Response, document_id: str
) -> LegalDocumentRead:
    """One document by version id ("tos-2026-09") or by slug ("terms")."""
    document = documents.by_id(document_id)
    if document is None:
        raise NotFoundError("No such document.")
    response.headers["Cache-Control"] = (
        REVIEWED_CACHE if document.review_status is ReviewStatus.ATTORNEY_REVIEWED else DRAFT_CACHE
    )
    return LegalDocumentRead(
        **_summary(document).model_dump(),
        # asdict, not __dict__: the spans inside a block are dataclasses too.
        blocks=[asdict(block) for block in documents.blocks(document.version)],
    )
