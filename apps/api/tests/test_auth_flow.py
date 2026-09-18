"""Authentication behaviour, including the properties that carry security weight."""

import asyncio
import re

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.models.audit import AuditLog
from eoehelp_api.models.auth import RefreshToken
from eoehelp_api.models.user import User

AUTH = "/api/v1/auth"
TOKEN_RE = re.compile(r"token=([A-Za-z0-9_-]+)")


async def _request_link(client: AsyncClient, monkeypatch, email: str) -> str:
    """Request a magic link, capturing it instead of sending mail."""
    captured: list[str] = []

    async def fake_send(self, *, to: str, link: str, ttl_minutes: int) -> None:
        captured.append(link)

    monkeypatch.setattr("eoehelp_api.services.email.EmailSender.send_magic_link", fake_send)
    response = await client.post(f"{AUTH}/magic-link", json={"email": email})
    assert response.status_code == 202
    match = TOKEN_RE.search(captured[0])
    assert match is not None
    return match.group(1)


async def _sign_in(client: AsyncClient, monkeypatch, email: str) -> str:
    token = await _request_link(client, monkeypatch, email)
    response = await client.post(f"{AUTH}/magic-link/verify", json={"token": token})
    assert response.status_code == 200
    return str(response.json()["access_token"])


class TestMagicLink:
    async def test_first_request_creates_account_and_signs_in(
        self, client: AsyncClient, monkeypatch, session: AsyncSession
    ) -> None:
        access = await _sign_in(client, monkeypatch, "new@example.com")

        response = await client.get(
            f"{AUTH}/session", headers={"Authorization": f"Bearer {access}"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["email"] == "new@example.com"
        assert body["role"] == "patient"
        # Clicking the link proves inbox possession, so it doubles as verification.
        assert body["email_verified"] is True

        user = (
            await session.execute(select(User).where(User.email == "new@example.com"))
        ).scalar_one()
        assert user.email_verified_at is not None

    async def test_response_is_identical_for_unknown_and_known_addresses(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        """The endpoint must not reveal whether an address has an account.

        On this product that would disclose who has an EoE diagnosis.
        """
        await _sign_in(client, monkeypatch, "existing@example.com")

        known = await client.post(f"{AUTH}/magic-link", json={"email": "existing@example.com"})
        unknown = await client.post(f"{AUTH}/magic-link", json={"email": "stranger@example.com"})

        assert known.status_code == unknown.status_code == 202
        assert known.json() == unknown.json()

    async def test_token_cannot_be_replayed(self, client: AsyncClient, monkeypatch) -> None:
        token = await _request_link(client, monkeypatch, "once@example.com")

        assert (
            await client.post(f"{AUTH}/magic-link/verify", json={"token": token})
        ).status_code == 200
        replay = await client.post(f"{AUTH}/magic-link/verify", json={"token": token})
        assert replay.status_code == 400

    async def test_simultaneous_clicks_sign_in_once(self, client: AsyncClient, monkeypatch) -> None:
        token = await _request_link(client, monkeypatch, "double@example.com")
        results = await asyncio.gather(
            *(client.post(f"{AUTH}/magic-link/verify", json={"token": token}) for _ in range(4))
        )
        assert sorted(r.status_code for r in results) == [200, 400, 400, 400]

    async def test_repeated_requests_stop_sending_mail_but_answer_the_same(
        self, client: AsyncClient, monkeypatch, session: AsyncSession
    ) -> None:
        """Someone else's inbox is protected even when requests come from many
        addresses, and the caller still cannot tell anything happened."""
        sent: list[str] = []

        async def fake_send(self, *, to: str, link: str, ttl_minutes: int) -> None:
            sent.append(link)

        monkeypatch.setattr("eoehelp_api.services.email.EmailSender.send_magic_link", fake_send)
        responses = [
            await client.post(f"{AUTH}/magic-link", json={"email": "victim@example.com"})
            for _ in range(5)
        ]
        assert {r.status_code for r in responses} == {202}
        assert len({r.text for r in responses}) == 1
        assert len(sent) == 3

    async def test_unknown_token_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post(
            f"{AUTH}/magic-link/verify", json={"token": "not-a-real-token-value"}
        )
        assert response.status_code == 400


class TestRefreshTokens:
    async def test_refresh_cookie_is_httponly_and_path_scoped(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        token = await _request_link(client, monkeypatch, "cookie@example.com")
        response = await client.post(f"{AUTH}/magic-link/verify", json={"token": token})

        cookie_header = response.headers["set-cookie"]
        assert "httponly" in cookie_header.lower()
        assert "samesite=strict" in cookie_header.lower()
        # Must match where the router is actually mounted, or the browser never
        # sends it back and refresh silently fails for every user.
        assert f"Path={AUTH}" in cookie_header

    async def test_rotation_issues_a_new_token(self, client: AsyncClient, monkeypatch) -> None:
        await _sign_in(client, monkeypatch, "rotate@example.com")
        first = client.cookies.get("eoehelp_refresh")

        response = await client.post(f"{AUTH}/refresh")
        assert response.status_code == 200
        assert client.cookies.get("eoehelp_refresh") != first

    async def test_reuse_revokes_the_entire_family_and_is_audited(
        self, client: AsyncClient, monkeypatch, session: AsyncSession
    ) -> None:
        """A replayed refresh token means the cookie leaked.

        The whole lineage must die — including the currently-valid token — so the
        attacker's copy is useless and the real user is forced to re-authenticate.
        The revocation must also survive the failed request's rollback.
        """
        await _sign_in(client, monkeypatch, "stolen@example.com")
        stolen = client.cookies.get("eoehelp_refresh")

        assert (await client.post(f"{AUTH}/refresh")).status_code == 200
        current = client.cookies.get("eoehelp_refresh")
        assert current != stolen

        # Replayed well after the rotation, which is what a thief's use looks like.
        await session.execute(
            text("UPDATE refresh_tokens SET rotated_at = rotated_at - interval '5 minutes'")
        )
        await session.commit()

        replay = await client.post(f"{AUTH}/refresh", cookies={"eoehelp_refresh": stolen})
        assert replay.status_code == 400

        follow_up = await client.post(f"{AUTH}/refresh", cookies={"eoehelp_refresh": current})
        assert follow_up.status_code == 400, "family revocation did not persist"

        live = (
            (await session.execute(select(RefreshToken).where(RefreshToken.revoked_at.is_(None))))
            .scalars()
            .all()
        )
        assert live == []

        audited = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "auth.refresh.reuse_detected")
                )
            )
            .scalars()
            .all()
        )
        assert audited, "token reuse must leave an audit trail"

    async def test_an_immediate_reuse_is_refused_without_signing_everyone_out(
        self, client: AsyncClient, monkeypatch, session: AsyncSession
    ) -> None:
        """Two tabs refreshing at once present the same token twice within
        seconds. Treating that as theft would sign the patient out everywhere."""
        await _sign_in(client, monkeypatch, "tabs@example.com")
        shared = client.cookies.get("eoehelp_refresh")

        first = await client.post(f"{AUTH}/refresh", cookies={"eoehelp_refresh": shared})
        assert first.status_code == 200
        winner = client.cookies.get("eoehelp_refresh")

        second = await client.post(f"{AUTH}/refresh", cookies={"eoehelp_refresh": shared})
        assert second.status_code == 400

        still_valid = await client.post(f"{AUTH}/refresh", cookies={"eoehelp_refresh": winner})
        assert still_valid.status_code == 200
        reuse = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "auth.refresh.reuse_detected")
                )
            )
            .scalars()
            .all()
        )
        assert reuse == []

    async def test_concurrent_refreshes_rotate_exactly_once(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        await _sign_in(client, monkeypatch, "race@example.com")
        shared = client.cookies.get("eoehelp_refresh")
        results = await asyncio.gather(
            *(client.post(f"{AUTH}/refresh", cookies={"eoehelp_refresh": shared}) for _ in range(5))
        )
        assert sorted(r.status_code for r in results) == [200, 400, 400, 400, 400]

    async def test_refresh_without_cookie_is_rejected(self, client: AsyncClient) -> None:
        assert (await client.post(f"{AUTH}/refresh")).status_code == 400

    async def test_sign_out_revokes_the_session(self, client: AsyncClient, monkeypatch) -> None:
        await _sign_in(client, monkeypatch, "signout@example.com")
        assert (await client.post(f"{AUTH}/sign-out")).status_code == 204
        assert (await client.post(f"{AUTH}/refresh")).status_code == 400


class TestAccessTokens:
    async def test_session_requires_a_token(self, client: AsyncClient) -> None:
        assert (await client.get(f"{AUTH}/session")).status_code == 401

    @pytest.mark.parametrize(
        "header",
        ["Bearer not-a-jwt", "Basic abc123", "", "bearer", "Bearer "],
    )
    async def test_malformed_credentials_are_rejected(
        self, client: AsyncClient, header: str
    ) -> None:
        response = await client.get(f"{AUTH}/session", headers={"Authorization": header})
        assert response.status_code == 401

    async def test_token_signed_with_another_key_is_rejected(self, client: AsyncClient) -> None:
        import jwt

        forged = jwt.encode(
            {
                "sub": "00000000-0000-0000-0000-000000000000",
                "role": "admin",
                "iat": 0,
                "exp": 9999999999,
            },
            "attacker-key",
            algorithm="HS256",
        )
        response = await client.get(
            f"{AUTH}/session", headers={"Authorization": f"Bearer {forged}"}
        )
        assert response.status_code == 401


class TestAuditLog:
    async def test_audit_log_rejects_update_and_delete_by_app_role(
        self, session: AsyncSession
    ) -> None:
        """The application must not be able to erase its own trail.

        Skipped where the app_runtime role is absent (some local databases); the
        grant is asserted in CI, where migrations create it.
        """
        role_exists = (
            await session.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime'"))
        ).scalar_one_or_none()
        if not role_exists:
            pytest.skip("app_runtime role not present in this database")

        for privilege in ("UPDATE", "DELETE"):
            granted = (
                await session.execute(
                    text("SELECT has_table_privilege('app_runtime', 'audit_log', :priv)"),
                    {"priv": privilege},
                )
            ).scalar_one()
            assert granted is False, f"app_runtime must not hold {privilege} on audit_log"

        assert (
            await session.execute(
                text("SELECT has_table_privilege('app_runtime', 'audit_log', 'INSERT')")
            )
        ).scalar_one() is True
