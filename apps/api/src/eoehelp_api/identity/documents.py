"""Versioned legal documents the patient agrees to.

"The patient consented" is not a defensible record on its own — consented to
*what text* is the question a regulator or a plaintiff asks. Every consent row
stores one of these version strings, so the exact wording in force at the time
can be reproduced.

Bumping a version here means existing patients are no longer covered by the
current document and must be re-prompted. That is the intended friction: a
silent edit to the privacy policy would leave every stored consent attesting to
something nobody read.
"""

from typing import Final

from eoehelp_api.identity.enums import ConsentType

TERMS_OF_SERVICE_VERSION: Final = "tos-2026-09"
PRIVACY_POLICY_VERSION: Final = "privacy-2026-09"

# Washington's My Health My Data Act requires a separate, specific consumer
# health data disclosure with its own affirmative consent. It cannot be bundled
# into the privacy policy, and WA carries a private right of action, so this is
# tracked as its own document rather than a clause in another one.
CONSUMER_HEALTH_DATA_VERSION: Final = "chd-2026-09"

RESEARCH_PARTICIPATION_VERSION: Final = "research-2026-09"

CURRENT_VERSIONS: Final[dict[ConsentType, str]] = {
    ConsentType.TERMS_OF_SERVICE: TERMS_OF_SERVICE_VERSION,
    ConsentType.PRIVACY_POLICY: PRIVACY_POLICY_VERSION,
    ConsentType.CONSUMER_HEALTH_DATA: CONSUMER_HEALTH_DATA_VERSION,
    ConsentType.RESEARCH_PARTICIPATION: RESEARCH_PARTICIPATION_VERSION,
}

# Required to hold an account. Research participation is deliberately absent: it
# is a separate, specific, reversible decision and must never be a condition of
# using the product.
REQUIRED_AT_ONBOARDING: Final[tuple[ConsentType, ...]] = (
    ConsentType.TERMS_OF_SERVICE,
    ConsentType.PRIVACY_POLICY,
    ConsentType.CONSUMER_HEALTH_DATA,
)

# v1 is adults-only. Under-13 accounts trigger COPPA and verifiable parental
# consent, and 13-17 raises its own questions, so the launch gate is 18+. A
# pediatric module is a deliberate later milestone with PEESS® permission and a
# revisit of the birth_year precision decision.
MINIMUM_AGE_YEARS: Final = 18
