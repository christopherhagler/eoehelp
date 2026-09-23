"""Rate limits must count a route, not the URL that happened to be requested.

slowapi's `Limiter.limit()` leaves its scope unset and then falls back to
`request.url.path` — the resolved path. On any route with a path parameter that
makes the counter per-URL: the limit is bypassed by varying the parameter, and
every distinct value mints another counter in Redis. Filling a `noeviction`
Redis disables every limiter in the process, including the one protecting
magic-link email, so this is not only a limit that fails to bind.

`ratelimit.route_limit` exists to make that impossible to reintroduce; these
tests are what keep it that way.
"""

import ast
from pathlib import Path

import pytest
from httpx import AsyncClient

from eoehelp_api.core import ratelimit

SOURCE = Path(__file__).parents[2] / "src" / "eoehelp_api"


def _decorators() -> list[tuple[str, str]]:
    """Every rate-limit decorator in the codebase, as (file, source)."""
    found: list[tuple[str, str]] = []
    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                text = ast.unparse(decorator)
                if "limiter.limit" in text or "route_limit" in text:
                    found.append((str(path.relative_to(SOURCE)), text))
    return found


def test_no_route_uses_the_unscoped_limiter() -> None:
    unscoped = [(path, text) for path, text in _decorators() if "route_limit" not in text]
    assert not unscoped, (
        "these routes would be counted per-URL rather than per-route; "
        f"use ratelimit.route_limit instead: {unscoped}"
    )


def test_every_rate_limited_route_is_scoped() -> None:
    decorators = _decorators()
    assert decorators, "expected to find rate-limited routes"
    for path, text in decorators:
        # route_limit(limit, "scope") — the scope is the second argument.
        call = ast.parse(text, mode="eval").body
        assert isinstance(call, ast.Call)
        assert len(call.args) == 2, f"{path}: {text} has no explicit scope"
        assert isinstance(call.args[1], ast.Constant), f"{path}: scope must be a literal"


class TestTheLimitBindsAcrossUrls:
    async def test_exhausting_one_document_limits_the_others(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regression test for the defect itself: /terms and /privacy share
        one counter, and an unknown id cannot mint a fresh one."""
        if not ratelimit.limiter.enabled:
            pytest.skip("rate limits are disabled in this environment")

        limit = int(ratelimit.LEGAL_DOCUMENTS.split("/")[0])
        for _ in range(limit):
            await client.get("/api/v1/legal/documents/terms")

        for path in ("/api/v1/legal/documents/terms", "/api/v1/legal/documents/privacy"):
            response = await client.get(path)
            assert response.status_code == 429, f"{path} should share the exhausted counter"
