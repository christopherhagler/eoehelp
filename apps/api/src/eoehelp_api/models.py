"""SQLAlchemy models.

Imported for their side effect of registering with Base.metadata, which Alembic
autogenerate reads. A model not imported here is silently invisible to migrations.
"""

from eoehelp_api.audit.models import AuditLog
from eoehelp_api.food.models import (
    CatalogIngredient,
    CustomIngredient,
    FoodLogItem,
    FoodLogItemIngredient,
    FoodProduct,
)
from eoehelp_api.identity.consent import Consent, ResearchConsentScope
from eoehelp_api.identity.legal_document import PublishedLegalDocument
from eoehelp_api.identity.patient import Patient
from eoehelp_api.identity.tokens import MagicLinkToken, RefreshToken
from eoehelp_api.identity.user import User
from eoehelp_api.medications.models import Medication, MedicationCatalogEntry, MedicationDose
from eoehelp_api.procedures.models import Biopsy, Dilation, Endoscopy
from eoehelp_api.symptoms.models import ClinicalInstrument, SymptomEntry

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
    "FoodProduct",
    "MagicLinkToken",
    "Medication",
    "MedicationCatalogEntry",
    "MedicationDose",
    "Patient",
    "PublishedLegalDocument",
    "RefreshToken",
    "ResearchConsentScope",
    "SymptomEntry",
    "User",
]
