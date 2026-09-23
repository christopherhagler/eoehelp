"""Rate limits for the endpoints an unauthenticated caller can reach or abuse.

What each limit protects:

- **Magic-link request**: someone else's inbox (email bombing), our sending
  reputation (which is our only way in), and the users table (accounts are
  created on first request).
- **Magic-link verify** and **refresh**: guessing, and replay loops.
- **Product lookups**: the Open Food Facts and USDA quotas every patient shares.
- **Legal documents**: public, unauthenticated reads; the limit keeps them
  from being a cheap way to make the API do work.
- **Insights**: the food-pattern analysis reads up to 18 months of a patient's
  log and runs exact tests, far more work than a list read, so one client
  cannot tie up an API task by refreshing it.

Counters live in Redis wherever more than one API task runs, since per-process
counters would let each task grant the whole limit. Production refuses to start
without it (config.enforce_production_safety).

Keyed on the client address. Behind the load balancer that is only correct if
uvicorn trusts the balancer's X-Forwarded-For (``--proxy-headers`` with
``--forwarded-allow-ips`` set to the balancer's subnet); otherwise every patient
shares one counter. The deployment ADR records this.
"""

from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from eoehelp_api.config import get_settings
from eoehelp_api.observability import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

MAGIC_LINK_REQUEST = "5/15 minutes"
MAGIC_LINK_VERIFY = "10/minute"
SESSION_REFRESH = "30/minute"
PRODUCT_LOOKUP = "60/minute"
# The food-pattern analysis costs more than a list read.
INSIGHTS = "30/minute"
LEGAL_DOCUMENTS = "60/minute"

# Per address, independent of the caller: enforced in the auth service against
# the tokens table, so it holds even when requests arrive from many addresses.
MAGIC_LINKS_PER_EMAIL = 3
MAGIC_LINK_EMAIL_WINDOW_MINUTES = 15


def _client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _build() -> Limiter:
    settings = get_settings()
    return Limiter(
        key_func=_client_address,
        storage_uri=settings.redis_url or "memory://",
        enabled=settings.rate_limits_enabled,
        strategy="moving-window",
    )


limiter = _build()


def route_limit(limit_value: str, scope: str) -> Callable[[F], F]:
    """Rate limit a route, keyed on the route rather than the URL that was hit.

    `limiter.limit()` leaves slowapi's scope unset, and slowapi then falls back
    to `request.url.path` — the *resolved* path. On a route with a path
    parameter that makes the counter per-URL, so the limit is bypassed simply
    by varying the parameter, and every distinct value mints another counter in
    a Redis configured `noeviction`. Filling that store disables every limiter
    in the process, including the one protecting magic-link email.

    Passing an explicit scope is the whole fix, so it is done here rather than
    at each call site: a new route cannot forget what it does not choose.
    """
    return limiter.shared_limit(limit_value, scope=scope)


async def rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    # The route template, not the path, and never the address: the log store is
    # not the place for a record of who was throttled.
    route = request.scope.get("route")
    logger.warning(
        "http.rate_limited",
        path=getattr(route, "path", None),
        limit=str(exc.limit.limit) if exc.limit else None,
    )
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please wait a few minutes and try again."},
        headers={"Retry-After": "60"},
    )
