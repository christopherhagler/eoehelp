"""Synthetic patient histories for load tests, golden files, staging seeds, and demos.

Real patient data can serve none of those, and a generator built late is a
generator that never gets built. See generator.py for what makes these histories
worth having: they are correlated, they span timezones, and they are deterministic.
"""

from eoehelp_api.synthetic.generator import HistoryGenerator
from eoehelp_api.synthetic.plans import (
    DayPlan,
    DosePlan,
    EpochPlan,
    HistoryPlan,
    MedicationPlan,
    ProfilePlan,
)
from eoehelp_api.synthetic.writer import (
    SyntheticDataRefusedError,
    SyntheticWriter,
    WrittenHistory,
    assert_writable,
    write_history,
)

__all__ = [
    "DayPlan",
    "DosePlan",
    "EpochPlan",
    "HistoryGenerator",
    "HistoryPlan",
    "MedicationPlan",
    "ProfilePlan",
    "SyntheticDataRefusedError",
    "SyntheticWriter",
    "WrittenHistory",
    "assert_writable",
    "write_history",
]
