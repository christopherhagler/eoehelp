"""A patient's days: which one is today, and which ones may still be written to.

Symptoms and food follow one rule, so that a patient catching up after a flare
can fill in both halves of the same day rather than finding one accepted and the
other refused.
"""

import enum
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from eoehelp_api.core.errors import BadRequestError


class EntryMethod(enum.StrEnum):
    """Whether the entry was logged on the day it describes.

    Research weights same-day entries more heavily than recalled ones, and this
    is derived server-side from the patient's own timezone rather than trusted
    from the client.
    """

    SAME_DAY = "same_day"
    BACKFILL = "backfill"


def patient_today(timezone: str) -> date:
    """Today in the patient's own timezone, which is the only "today" that counts.

    Taken in UTC, an evening entry in Seattle lands on tomorrow and is recorded
    as a backfill of a day that has not happened.
    """
    return datetime.now(ZoneInfo(timezone)).date()


# A week of catch-up covers a holiday or a flare that made logging impossible,
# while keeping entries close enough to the day to be worth something. Anything
# older is recall, and the plan would rather have a gap than fiction.
MAX_BACKFILL_DAYS = 7


def classify(entry_date: date, *, today: date) -> EntryMethod:
    """How an entry for `entry_date` is being captured, or refuse it.

    `today` is the patient's today, in their own timezone; the caller owns that.
    """
    if entry_date > today:
        raise BadRequestError("That day has not happened yet in your timezone.")
    if entry_date < today - timedelta(days=MAX_BACKFILL_DAYS):
        raise BadRequestError(
            f"Entries can be added up to {MAX_BACKFILL_DAYS} days late. "
            "Older days are left blank rather than recalled."
        )
    return EntryMethod.SAME_DAY if entry_date == today else EntryMethod.BACKFILL
