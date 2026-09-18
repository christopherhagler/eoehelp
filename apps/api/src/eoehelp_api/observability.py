"""Structured logging with PHI scrubbing.

Anything logged here may reach CloudWatch and an external error tracker, so the
redaction below is a security control rather than tidiness: a symptom note or an
email address in a log line is a disclosure. Field names are denied by name, and
`scrub_event` is exercised directly by tests/test_phi_scrubbing.py.
"""

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from structlog.types import EventDict

# Denied by exact key name anywhere in a log event. Keep in sync with any new
# free-text or identifying column; the test suite asserts each one redacts.
PHI_FIELD_NAMES = frozenset(
    {
        "email",
        "display_name",
        "notes",
        "notes_encrypted",
        "password",
        "password_hash",
        "token",
        "refresh_token",
        "access_token",
        "magic_link_token",
        "pathologist_note",
        "prescriber_note",
        "performing_facility",
        "facility",
        "food_freetext",
        # What someone searched for, or scanned, is what they are eating.
        "q",
        "query",
        "search",
        "barcode",
        "indication",
        "ip_address",
        "user_agent",
        "authorization",
        "cookie",
        "set-cookie",
    }
)

# Substring match, for keys we cannot enumerate ahead of time.
PHI_FIELD_SUBSTRINGS = ("_encrypted", "secret", "passwd")

REDACTED = "[redacted]"


def _is_phi_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in PHI_FIELD_NAMES or any(s in lowered for s in PHI_FIELD_SUBSTRINGS)


def _scrub_value(value: Any, depth: int) -> Any:
    # Bounded depth: a logger that recurses without limit takes the request down
    # with it, which is a worse outcome than leaving deep structures untouched.
    if depth > 6:
        return value
    if isinstance(value, MutableMapping):
        return {
            key: (REDACTED if _is_phi_key(str(key)) else _scrub_value(item, depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(_scrub_value(item, depth + 1) for item in value)
    return value


def scrub_event(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    """Recursively redact PHI-bearing keys from a log event."""
    scrubbed: EventDict = {
        key: (REDACTED if _is_phi_key(str(key)) else _scrub_value(value, 1))
        for key, value in event_dict.items()
    }
    return scrubbed


def configure_logging(*, environment: str, debug: bool) -> None:
    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer()
        if environment == "local"
        else structlog.processors.JSONRenderer()
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG if debug else logging.INFO,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            scrub_event,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if debug else logging.INFO
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
