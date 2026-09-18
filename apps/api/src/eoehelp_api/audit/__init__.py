"""The append-only audit trail: who touched which record, when, and how it went.

Callers write through `record`, in their own transaction, so a change and its
trail commit together or not at all.
"""

from eoehelp_api.audit.service import AuditContext, record

__all__ = ["AuditContext", "record"]
