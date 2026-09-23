"""The public legal routes."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from httpx import AsyncClient

from eoehelp_api.identity import documents
from eoehelp_api.identity.documents import LegalDocument, Revision
from eoehelp_api.identity.enums import ConsentType, ReviewStatus


def _as_reviewed(document: LegalDocument) -> LegalDocument:
    """The same bytes, marked reviewed.

    Review status lives on the revision now, because an attorney reviews
    particular words — so flipping it means replacing the revision, not the
    document.
    """
    return replace(
        document,
        revisions=tuple(
            replace(revision, review_status=ReviewStatus.ATTORNEY_REVIEWED)
            for revision in document.revisions
        ),
    )


LEGAL = "/api/v1/legal/documents"


class TestListing:
    async def test_anyone_can_read_the_current_documents(self, client: AsyncClient) -> None:
        """No Authorization header: the terms must be readable before an account
        exists, and afterwards without signing in."""
        response = await client.get(LEGAL)
        assert response.status_code == 200
        body = response.json()
        assert {document["id"] for document in body} == {
            documents.TERMS_OF_SERVICE_VERSION,
            documents.PRIVACY_POLICY_VERSION,
            documents.CONSUMER_HEALTH_DATA_VERSION,
        }
        assert all("blocks" not in document for document in body)
        assert all(document["superseded_by"] is None for document in body)
        assert "set-cookie" not in response.headers

    async def test_drafts_are_not_cached(self, client: AsyncClient) -> None:
        """A draft changes during review, so a cached copy misleads everyone."""
        response = await client.get(LEGAL)
        assert response.headers["cache-control"] == "no-store"


class TestDocument:
    async def test_a_slug_and_a_version_return_the_same_document(self, client: AsyncClient) -> None:
        by_slug = await client.get(f"{LEGAL}/terms")
        by_version = await client.get(f"{LEGAL}/{documents.TERMS_OF_SERVICE_VERSION}")
        assert by_slug.status_code == by_version.status_code == 200
        assert by_slug.json() == by_version.json()
        assert by_slug.json()["id"] == documents.TERMS_OF_SERVICE_VERSION

    async def test_the_document_carries_its_text_as_typed_blocks(self, client: AsyncClient) -> None:
        body = (await client.get(f"{LEGAL}/privacy")).json()
        kinds = {block["kind"] for block in body["blocks"]}
        assert {"heading", "paragraph", "table"} <= kinds
        assert body["review_status"] == "draft"
        assert (
            body["content_sha256"]
            == documents.current_for(documents.ConsentType.PRIVACY_POLICY).sha256
        )

    async def test_an_unknown_document_is_a_plain_404(self, client: AsyncClient) -> None:
        response = await client.get(f"{LEGAL}/nope")
        assert response.status_code == 404
        assert response.json()["detail"] == "No such document."


class TestCaching:
    """The reviewed branch is the one that runs in production, and until now it
    had never executed: every test ran against drafts, which are `no-store`.

    It also interacts with the `Vary: Origin` header, which exists precisely
    because a `public` directive lets a shared cache store a copy fetched
    without an Origin and then hand it to the browser, which fails CORS and
    blanks the page.
    """

    async def test_a_reviewed_document_is_cacheable_and_varies_on_origin(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reviewed = tuple(_as_reviewed(document) for document in documents.DOCUMENTS)
        monkeypatch.setattr(documents, "DOCUMENTS", reviewed)

        for path in (LEGAL, f"{LEGAL}/terms"):
            response = await client.get(path)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "public, max-age=3600"
            assert response.headers["vary"] == "Origin"

    async def test_one_unreviewed_document_keeps_the_listing_uncacheable(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mixed state is the realistic one during review, and a cached list
        naming a draft as current is how a stale version reaches onboarding."""
        mixed = (_as_reviewed(documents.DOCUMENTS[0]), *documents.DOCUMENTS[1:])
        monkeypatch.setattr(documents, "DOCUMENTS", mixed)

        response = await client.get(LEGAL)
        assert response.headers["cache-control"] == "no-store"


@pytest.fixture(autouse=True)
def _clear_document_caches():
    """`text_for` and `blocks_for` are process-global caches.

    A test that points LEGAL_DIRECTORY at a tmp_path populates them with bytes
    read from a directory that will not exist afterwards. Clearing in the test
    body only works when every assertion above it passes, so it belongs in a
    fixture that runs either way.
    """
    documents.text_for.cache_clear()
    documents.blocks_for.cache_clear()
    yield
    documents.text_for.cache_clear()
    documents.blocks_for.cache_clear()


class TestReadingByDigest:
    """A consent row stores a digest; this is the route that turns it back into
    the words that were on the screen."""

    async def test_the_current_revisions_digest_returns_the_same_document(
        self, client: AsyncClient
    ) -> None:
        terms = documents.current_for(ConsentType.TERMS_OF_SERVICE)
        by_slug = (await client.get(f"{LEGAL}/{terms.slug}")).json()
        by_digest = (await client.get(f"{LEGAL}/{terms.sha256}")).json()

        assert by_digest == by_slug
        assert by_digest["content_sha256"] == terms.sha256
        # Equal by definition when the current revision is the one requested,
        # which is what the page uses to decide whether to warn the reader.
        assert by_digest["current_content_sha256"] == terms.sha256

    async def test_an_older_revision_returns_its_own_bytes_and_says_so(
        self, client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point: older bytes stay readable, and the response carries
        enough for the page to say they are not current."""
        terms = documents.current_for(ConsentType.TERMS_OF_SERVICE)
        older_text = "## 1. An earlier wording\n\nThis is what it used to say.\n"
        older_digest = hashlib.sha256(older_text.encode()).hexdigest()

        for index, revision in enumerate((older_digest, terms.sha256), start=1):
            target = tmp_path / f"{terms.version}.r{index}.md"
            if revision == older_digest:
                target.write_text(older_text, encoding="utf-8")
            else:
                target.write_text(terms.path.read_text(encoding="utf-8"), encoding="utf-8")

        two_revisions = replace(
            terms,
            revisions=(
                Revision(sha256=older_digest, review_status=ReviewStatus.DRAFT),
                *terms.revisions,
            ),
        )
        monkeypatch.setattr(documents, "LEGAL_DIRECTORY", tmp_path)
        monkeypatch.setattr(documents, "DOCUMENTS", (two_revisions, *documents.DOCUMENTS[1:]))
        older = (await client.get(f"{LEGAL}/{older_digest}")).json()
        assert older["content_sha256"] == older_digest
        assert older["current_content_sha256"] == terms.sha256
        assert older["blocks"][0]["text"] == "1. An earlier wording"

        current = (await client.get(f"{LEGAL}/{terms.slug}")).json()
        assert current["content_sha256"] == terms.sha256
        assert current["current_content_sha256"] == terms.sha256

    async def test_an_unknown_digest_is_a_plain_404(self, client: AsyncClient) -> None:
        """Same body as an unknown slug: the response says nothing about which
        digests exist."""
        unknown = (await client.get(f"{LEGAL}/{'f' * 64}")).json()
        assert unknown == (await client.get(f"{LEGAL}/nope")).json()
