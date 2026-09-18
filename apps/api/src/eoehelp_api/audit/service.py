"""Audit trail writes.

`record` takes the caller's session on purpose: the audit row must commit in the
same transaction as the change it describes. Queuing it or opening a second
session would allow data to land without its trail during a crash, which is
exactly when the trail matters.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from eoehelp_api.audit.enums import AuditOutcome
from eoehelp_api.audit.models import AuditLog
from eoehelp_api.observability import PHI_FIELD_NAMES


class AuditContext:
    """Request-derived attribution for audit rows."""

    def __init__(
        self,
        *,
        actor_user_id: uuid.UUID | None = None,
        actor_role: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.actor_user_id = actor_user_id
        self.actor_role = actor_role
        self.ip_address = ip_address
        self.user_agent = user_agent


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip PHI values, keeping only field names and non-sensitive scalars.

    The audit log records *that* a field changed, never what it changed to.
    """
    if not metadata:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in metadata.items():
        lowered = key.lower()
        if lowered in PHI_FIELD_NAMES or "_encrypted" in lowered:
            cleaned[key] = "[redacted]"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            cleaned[key] = value
        elif isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
            cleaned[key] = list(value)
        else:
            cleaned[key] = "[omitted]"
    return cleaned


async def record(
    session: AsyncSession,
    *,
    action: str,
    resource_type: str,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    context: AuditContext | None = None,
    resource_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    ctx = context or AuditContext()
    session.add(
        AuditLog(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            patient_id=patient_id,
            actor_user_id=ctx.actor_user_id,
            actor_role=ctx.actor_role,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            outcome=outcome,
            metadata_=_safe_metadata(metadata),
        )
    )
    await session.flush()
