"""Which days a patient may still write to, shared by every daily log.

Symptoms and food follow one rule, so that a patient catching up after a flare
can fill in both halves of the same day rather than finding one accepted and the
other refused.
"""

from datetime import date, timedelta

from eoehelp_api.core.errors import BadRequestError
from eoehelp_api.models.enums import EntryMethod

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
