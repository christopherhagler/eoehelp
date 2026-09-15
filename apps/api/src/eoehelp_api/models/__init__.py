"""SQLAlchemy models.

Imported for their side effect of registering with Base.metadata, which Alembic
autogenerate reads. A model not imported here is silently invisible to migrations.
"""

from eoehelp_api.models.audit import AuditLog
from eoehelp_api.models.auth import MagicLinkToken, RefreshToken
from eoehelp_api.models.consent import Consent, ResearchConsentScope
from eoehelp_api.models.patient import Patient
from eoehelp_api.models.user import User

__all__ = [
    "AuditLog",
    "Consent",
    "MagicLinkToken",
    "Patient",
    "RefreshToken",
    "ResearchConsentScope",
    "User",
]
