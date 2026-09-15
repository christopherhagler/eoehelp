"""PHI must never reach logs or error tracking.

This is a launch-gate requirement, not a style preference: structured logs ship
to CloudWatch and exceptions to an external tracker, so a symptom note or email
address appearing here is a disclosure.
"""

import pytest

from eoehelp_api.observability import PHI_FIELD_NAMES, REDACTED, scrub_event
from eoehelp_api.services.audit import _safe_metadata


@pytest.mark.parametrize("field", sorted(PHI_FIELD_NAMES))
def test_every_declared_phi_field_is_redacted(field: str) -> None:
    scrubbed = scrub_event(None, "info", {"event": "test", field: "sensitive-value"})
    assert scrubbed[field] == REDACTED
    assert "sensitive-value" not in str(scrubbed)


def test_nested_structures_are_scrubbed() -> None:
    event = {
        "event": "http.request",
        "payload": {
            "email": "patient@example.com",
            "entry": {"notes": "burning after swallowing bread", "severity": 2},
        },
        "items": [{"display_name": "Jane Doe"}],
    }
    scrubbed = str(scrub_event(None, "info", event))

    assert "patient@example.com" not in scrubbed
    assert "burning after swallowing bread" not in scrubbed
    assert "Jane Doe" not in scrubbed
    # Non-PHI clinical values must survive, or the logs lose diagnostic value.
    assert "'severity': 2" in scrubbed


def test_substring_matched_fields_are_redacted() -> None:
    event = {
        "notes_encrypted": b"ciphertext",
        "jwt_secret": "supersecret",
        "pathologist_note_encrypted": b"blob",
    }
    scrubbed = scrub_event(None, "info", event)

    assert scrubbed["notes_encrypted"] == REDACTED
    assert scrubbed["jwt_secret"] == REDACTED
    assert scrubbed["pathologist_note_encrypted"] == REDACTED


def test_scrubbing_terminates_on_deeply_nested_input() -> None:
    event: dict[str, object] = {"event": "deep"}
    cursor = event
    for _ in range(50):
        nxt: dict[str, object] = {}
        cursor["child"] = nxt
        cursor = nxt
    cursor["email"] = "patient@example.com"

    # Must not recurse without bound; depth beyond the cap is left untouched
    # rather than crashing the logger, which would take the request down with it.
    scrub_event(None, "info", event)


def test_audit_metadata_never_carries_phi_values() -> None:
    cleaned = _safe_metadata(
        {
            "changed_fields": ["dysphagia_severity", "notes"],
            "notes": "stuck on steak",
            "email": "patient@example.com",
            "entry_count": 14,
        }
    )
    assert cleaned is not None
    assert cleaned["notes"] == REDACTED
    assert cleaned["email"] == REDACTED
    # Field *names* are the point of the audit trail and must survive.
    assert cleaned["changed_fields"] == ["dysphagia_severity", "notes"]
    assert cleaned["entry_count"] == 14
    assert "stuck on steak" not in str(cleaned)
