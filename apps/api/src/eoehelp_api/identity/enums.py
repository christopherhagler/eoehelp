"""Database enums for this area.

Each is created as a native Postgres type. Adding a value later needs an
explicit ALTER TYPE in a migration, which is the intended friction: these
encode clinical and legal vocabulary that should not drift silently.
"""

import enum


class UserRole(enum.StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    RESEARCHER = "researcher"
    ADMIN = "admin"


class UserStatus(enum.StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class SexAtBirth(enum.StrEnum):
    FEMALE = "female"
    MALE = "male"
    INTERSEX = "intersex"
    UNDISCLOSED = "undisclosed"


class ReviewStatus(enum.StrEnum):
    """Whether a legal document has been through attorney review.

    `DRAFT` means written in-house and not yet read by a lawyer. The API
    refuses to start in production while a document required at onboarding is
    still a draft (identity/documents.enforce_review_status).
    """

    DRAFT = "draft"
    ATTORNEY_REVIEWED = "attorney_reviewed"


class ConsentType(enum.StrEnum):
    TERMS_OF_SERVICE = "terms_of_service"
    PRIVACY_POLICY = "privacy_policy"
    # Washington My Health My Data Act requires a separate, specific consumer
    # health data disclosure — it cannot be folded into the general privacy policy.
    CONSUMER_HEALTH_DATA = "consumer_health_data"
    RESEARCH_PARTICIPATION = "research_participation"


class ResearchScope(enum.StrEnum):
    SYMPTOMS = "symptoms"
    DIET = "diet"
    MEDICATIONS = "medications"
    ENDOSCOPY = "endoscopy"
    DEMOGRAPHICS = "demographics"
