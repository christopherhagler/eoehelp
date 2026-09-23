"""Structured logging with PHI scrubbing.

Anything logged here may reach CloudWatch and an external error tracker, so the
redaction below is a security control rather than tidiness: a symptom note or an
email address in a log line is a disclosure. Field names are denied by name, and
`scrub_event` is exercised directly by tests/core/test_phi_scrubbing.py.
"""

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, Final

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

    _silence_path_loggers()


# Two loggers print the resolved request path, which the privacy policy says is
# not recorded: it promises "the route pattern rather than the address you
# visited". A resolved path is a patient's symptom date or a row id, and it is
# percent-decoded before either logger sees it, so an unauthenticated caller
# can put newlines in one and forge whole log lines — corrupting the record
# that exists to answer "was my data accessed".
#
# Silenced outright: every line it emits is a request line carrying the path
# and the client address, and main.py's middleware already logs each request
# with the route template.
_ACCESS_LOGGERS: Final = ("uvicorn.access",)

# Filtered rather than silenced: slowapi's only routine message is "ratelimit
# ... (<client ip>) exceeded at endpoint: <resolved path>", which duplicates
# what rate_limit_exceeded already logs without the address. Disabling the
# logger would also hide a rate-limit storage failure — a Redis outage is
# something the operator needs to see.
_PATH_LOGGERS: Final = ("slowapi", "slowapi.extension")


class _DropRequestPaths(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "exceeded at endpoint" not in record.getMessage()


def _silence_path_loggers() -> None:
    for name in _ACCESS_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = False
        logger.disabled = True

    for name in _PATH_LOGGERS:
        logger = logging.getLogger(name)
        # Explicitly enabled, not merely left alone: anything that has already
        # called logging.config.fileConfig or dictConfig — alembic does, with
        # disable_existing_loggers defaulting to True — will have switched this
        # logger off, and a storage failure would then be invisible. State the
        # wanted result rather than assuming it.
        logger.disabled = False
        if not any(isinstance(existing, _DropRequestPaths) for existing in logger.filters):
            logger.addFilter(_DropRequestPaths())


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
