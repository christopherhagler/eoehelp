"""Legal document DTOs.

The documents are served as typed blocks rather than markdown or HTML, so the
web app renders them without `innerHTML`, a sanitiser, or a markdown
dependency. The structure is part of the API contract, which also lets tests
assert that a statutorily required heading exists.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from eoehelp_api.identity.enums import ConsentType, ReviewStatus


class LegalSpan(BaseModel):
    text: str
    bold: bool = False
    # https://, mailto:, or an internal path. Restricted when the document is
    # parsed, so no other scheme can reach a client.
    href: str | None = None


class LegalHeading(BaseModel):
    kind: Literal["heading"]
    level: int
    text: str
    # Stable id, for the table of contents and for linking to a clause.
    anchor: str


class LegalParagraph(BaseModel):
    kind: Literal["paragraph"]
    spans: list[LegalSpan]


class LegalBullets(BaseModel):
    kind: Literal["bullets"]
    items: list[list[LegalSpan]]


class LegalTable(BaseModel):
    kind: Literal["table"]
    caption: str | None = None
    header: list[str]
    rows: list[list[list[LegalSpan]]]


LegalBlock = Annotated[
    LegalHeading | LegalParagraph | LegalBullets | LegalTable,
    Field(discriminator="kind"),
]


class LegalDocumentSummary(BaseModel):
    # The version, e.g. "tos-2026-09": what a consent row stores.
    id: str
    consent_type: ConsentType
    slug: str
    title: str
    effective_on: date
    review_status: ReviewStatus
    content_sha256: str
    # The id of a newer version of the same document, so a patient following a
    # link to what they agreed to is told it is no longer current.
    superseded_by: str | None = None


class LegalDocumentRead(LegalDocumentSummary):
    blocks: list[LegalBlock]
