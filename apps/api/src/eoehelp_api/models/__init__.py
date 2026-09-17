"""SQLAlchemy models.

Imported for their side effect of registering with Base.metadata, which Alembic
autogenerate reads. A model not imported here is silently invisible to migrations.
"""

from eoehelp_api.models.audit import AuditLog
from eoehelp_api.models.auth import MagicLinkToken, RefreshToken
from eoehelp_api.models.clinical import ClinicalInstrument, SymptomEntry
from eoehelp_api.models.consent import Consent, ResearchConsentScope
from eoehelp_api.models.food import (
    CatalogIngredient,
    CustomIngredient,
    FoodLogItem,
    FoodLogItemIngredient,
)
from eoehelp_api.models.medication import (
    Medication,
    MedicationCatalogEntry,
    MedicationDose,
)
from eoehelp_api.models.patient import Patient
from eoehelp_api.models.procedures import Biopsy, Dilation, Endoscopy
from eoehelp_api.models.user import User

__all__ = [
    "AuditLog",
    "Biopsy",
    "CatalogIngredient",
    "ClinicalInstrument",
    "Consent",
    "CustomIngredient",
    "Dilation",
    "Endoscopy",
    "FoodLogItem",
    "FoodLogItemIngredient",
    "MagicLinkToken",
    "Medication",
    "MedicationCatalogEntry",
    "MedicationDose",
    "Patient",
    "RefreshToken",
    "ResearchConsentScope",
    "SymptomEntry",
    "User",
]
