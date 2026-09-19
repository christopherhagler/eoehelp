"""FastAPI application entrypoint."""

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from eoehelp_api import __version__, health
from eoehelp_api.config import get_settings
from eoehelp_api.core.ratelimit import limiter, rate_limit_exceeded
from eoehelp_api.db.session import dispose_engine
from eoehelp_api.deps import API_V1_PREFIX
from eoehelp_api.food import router as food_router
from eoehelp_api.identity import auth_router, me_router
from eoehelp_api.insights import router as insights_router
from eoehelp_api.medications import router as medications_router
from eoehelp_api.observability import configure_logging, get_logger
from eoehelp_api.procedures import router as procedures_router
from eoehelp_api.reference import router as reference_router
from eoehelp_api.symptoms import router as symptoms_router

# Every versioned router, one per line so a new area is one visible addition.
# Catalog routers serve reference data under /api/v1/<area>; the others are the
# patient's own data under /api/v1/me.
V1_ROUTERS = (
    auth_router.router,
    me_router.router,
    reference_router.router,
    medications_router.catalog_router,
    medications_router.router,
    symptoms_router.router,
    food_router.catalog_router,
    food_router.router,
    procedures_router.router,
    insights_router.router,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(environment=settings.environment, debug=settings.debug)
    logger.info("api.startup", environment=settings.environment, version=__version__)
    yield
    await dispose_engine()
    logger.info("api.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="eoehelp API",
        version=__version__,
        description=(
            "Patient-owned EoE symptom tracking and clinical reporting. "
            "Personal health record; not a medical record system, and not medical advice."
        ),
        lifespan=lifespan,
        # Interactive docs expose the full surface; keep them off in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded)  # type: ignore[arg-type]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # required for the refresh cookie
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["x-request-id"] = request_id
        logger.info(
            "http.request",
            method=request.method,
            # Route template, not the resolved path: a raw path can carry a
            # share-link token or record id into the log store.
            path=request.scope.get("route").path  # type: ignore[union-attr]
            if request.scope.get("route")
            else request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        if get_settings().is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload"
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Log which fields failed validation, never what was in them.

        Without this a 422 leaves no server-side trace of the cause, and the only
        way to find out is to reproduce it by hand — which is exactly how a
        misbehaving client field goes undiagnosed. Field *locations* are safe to
        log; the submitted values are PHI and stay out, which is why `input` is
        dropped from the response body too.
        """
        fields = [".".join(str(part) for part in error["loc"]) for error in exc.errors()]
        logger.warning(
            "http.validation_failed",
            path=request.scope.get("route").path  # type: ignore[union-attr]
            if request.scope.get("route")
            else request.url.path,
            fields=fields,
            error_types=[error["type"] for error in exc.errors()],
        )
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {
                        "loc": list(error["loc"]),
                        "msg": error["msg"],
                        "type": error["type"],
                    }
                    for error in exc.errors()
                ]
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        # Log the type but never the message: exception text on this codebase can
        # contain row values, which means PHI.
        # The route template when one matched: a resolved path can carry an id.
        route = request.scope.get("route")
        logger.error(
            "http.unhandled_exception",
            exc_type=type(exc).__name__,
            path=getattr(route, "path", None),
        )
        return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred."})

    app.include_router(health.router)
    for router in V1_ROUTERS:
        app.include_router(router, prefix=API_V1_PREFIX)

    return app


app = create_app()
