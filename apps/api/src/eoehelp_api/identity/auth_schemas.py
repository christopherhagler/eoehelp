from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class MagicLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class MagicLinkRequestAccepted(BaseModel):
    """Deliberately uniform response.

    Always reports that a link was sent, whether or not the address has an
    account, so the endpoint cannot be used to enumerate registered patients —
    which for this product would disclose who has an EoE diagnosis.
    """

    detail: str = "If that address can receive mail, a sign-in link is on its way."


class MagicLinkVerify(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=16, max_length=512)


class AccessTokenResponse(BaseModel):
    """The refresh token is intentionally absent: it is set as an httpOnly cookie
    and must never be readable by JavaScript."""

    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime


class SessionUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    role: str
    email_verified: bool
    patient_id: str | None = None
    onboarding_complete: bool = False
