"""Reference data the client needs in order to submit valid requests.

Timezones live here rather than being taken from the browser because the two do
not agree. `Intl.supportedValuesOf('timeZone')` reflects the browser's ICU data,
which moves independently of the server's tz database, and a patient whose
browser offers a zone this API has never heard of would be stuck on the
onboarding form with no way forward. Serving the list the validator itself uses
makes every option in the UI one the API accepts by construction.
"""

import zoneinfo

from fastapi import APIRouter, Depends

from eoehelp_api.core.deps import Principal, get_principal

router = APIRouter(prefix="/reference", tags=["reference"])


@router.get("/timezones", response_model=list[str])
def list_timezones(_principal: Principal = Depends(get_principal)) -> list[str]:
    """Every IANA zone this server will accept, sorted.

    Authenticated, like the medication catalog: it discloses nothing about the
    reader, but there is no reason to serve it to anyone who is not signed in.
    """
    return sorted(zoneinfo.available_timezones())
