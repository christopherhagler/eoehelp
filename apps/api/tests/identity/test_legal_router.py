"""The public legal routes."""

from httpx import AsyncClient

from eoehelp_api.identity import documents

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
