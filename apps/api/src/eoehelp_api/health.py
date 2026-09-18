from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api import __version__
from eoehelp_api.deps import get_session

router = APIRouter(tags=["health"])


@router.get("/healthz", status_code=status.HTTP_200_OK)
async def liveness() -> dict[str, str]:
    """Liveness only. Deliberately does not touch the database: the load balancer
    should not cycle healthy application containers because Postgres is briefly
    unreachable."""
    return {"status": "ok", "version": __version__}


@router.get("/readyz", status_code=status.HTTP_200_OK)
async def readiness(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    """Readiness: checks the dependency the app cannot serve traffic without."""
    await session.execute(text("SELECT 1"))
    return {"status": "ready"}
