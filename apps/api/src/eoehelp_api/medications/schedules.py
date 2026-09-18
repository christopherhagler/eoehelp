"""Dosing schedules, expressed as iCal recurrence rules.

Patients choose from a fixed list; the rule is built here. The client never
supplies RRULE text, for two reasons.

**Safety.** An arbitrary rule is an expansion primitive — `FREQ=SECONDLY` over a
year is tens of millions of occurrences, and the counting below would happily
walk all of them. Generating the rule server-side means the grammar a caller can
reach is this enum, not iCal.

**Usability.** Nobody is typing `FREQ=WEEKLY;INTERVAL=2` into a health app. The
column stays a standard RRULE so a genuinely custom schedule can be added later
without a migration, and so the value means something to anyone reading the
database.
"""

import enum
from datetime import UTC, date, datetime, timedelta
from typing import Final

from dateutil.rrule import rrulestr


class DoseFrequency(enum.StrEnum):
    """The regimens EoE treatment actually uses.

    AS_NEEDED is not a frequency but the absence of one, and is handled as such:
    there is no expected-dose count, so adherence is reported as unknown rather
    than invented.
    """

    ONCE_DAILY = "once_daily"
    TWICE_DAILY = "twice_daily"
    THREE_TIMES_DAILY = "three_times_daily"
    EVERY_OTHER_DAY = "every_other_day"
    WEEKLY = "weekly"
    EVERY_TWO_WEEKS = "every_two_weeks"
    EVERY_FOUR_WEEKS = "every_four_weeks"
    AS_NEEDED = "as_needed"


# The hours are nominal and exist only so the rule yields the right number of
# occurrences per day — BYHOUR is how an RRULE expresses "twice daily" at all.
# They are not reminder times; when reminders land they will use the patient's own
# meal times, and these will stay the counting mechanism.
_RRULES: Final[dict[DoseFrequency, str]] = {
    DoseFrequency.ONCE_DAILY: "FREQ=DAILY;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
    DoseFrequency.TWICE_DAILY: "FREQ=DAILY;BYHOUR=9,21;BYMINUTE=0;BYSECOND=0",
    DoseFrequency.THREE_TIMES_DAILY: "FREQ=DAILY;BYHOUR=8,14,20;BYMINUTE=0;BYSECOND=0",
    DoseFrequency.EVERY_OTHER_DAY: "FREQ=DAILY;INTERVAL=2;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
    DoseFrequency.WEEKLY: "FREQ=WEEKLY;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
    DoseFrequency.EVERY_TWO_WEEKS: "FREQ=WEEKLY;INTERVAL=2;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
    DoseFrequency.EVERY_FOUR_WEEKS: "FREQ=WEEKLY;INTERVAL=4;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
}

_BY_RRULE: Final[dict[str, DoseFrequency]] = {rule: freq for freq, rule in _RRULES.items()}

# A ceiling on how many occurrences will ever be counted for one window. Every
# rule reachable through DoseFrequency stays far below it; the cap is here so that
# a hand-edited database row cannot turn an adherence request into an unbounded
# loop.
MAX_OCCURRENCES: Final = 5000


def rrule_for(frequency: DoseFrequency) -> str | None:
    """The stored rule for a frequency, or None for as-needed."""
    return _RRULES.get(frequency)


def frequency_of(rrule: str | None) -> DoseFrequency | None:
    """Recover the frequency from a stored rule.

    Returns None for as-needed *and* for a rule this version did not generate, so
    a future custom schedule degrades to "we cannot name this" rather than being
    mislabelled as something it is not.
    """
    if rrule is None:
        return DoseFrequency.AS_NEEDED
    return _BY_RRULE.get(rrule)


def expected_doses(
    *,
    rrule: str | None,
    started_on: date,
    ended_on: date | None,
    window_start: date,
    window_end: date,
) -> int | None:
    """How many doses the schedule expected inside the window.

    The adherence denominator, and the reason a fortnightly injection is not
    judged like a twice-daily pill.

    Clipped to the course's own dates at both ends: a medication started on
    Wednesday is not expected to have been taken on Monday, and one stopped last
    week is not accruing missed doses since.

    Returns None when there is no schedule to measure against.
    """
    if rrule is None:
        return None

    effective_start = max(started_on, window_start)
    effective_end = min(ended_on, window_end) if ended_on is not None else window_end
    if effective_end < effective_start:
        return 0

    # DTSTART is the course start, not the window start: the recurrence has to be
    # phased from when the medication actually began, or an every-other-day rule
    # counts the wrong days and a fortnightly one lands in the wrong week.
    dtstart = datetime.combine(started_on, datetime.min.time(), tzinfo=UTC)
    rule = rrulestr(rrule, dtstart=dtstart)

    span_start = datetime.combine(effective_start, datetime.min.time(), tzinfo=UTC)
    span_end = datetime.combine(
        effective_end + timedelta(days=1), datetime.min.time(), tzinfo=UTC
    ) - timedelta(microseconds=1)

    occurrences = rule.between(span_start, span_end, inc=True)
    return min(len(occurrences), MAX_OCCURRENCES)
