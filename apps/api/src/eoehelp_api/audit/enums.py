"""Database enums for this area.

Each is created as a native Postgres type. Adding a value later needs an
explicit ALTER TYPE in a migration, which is the intended friction: these
encode clinical and legal vocabulary that should not drift silently.
"""

import enum


class AuditOutcome(enum.StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    ERROR = "error"
