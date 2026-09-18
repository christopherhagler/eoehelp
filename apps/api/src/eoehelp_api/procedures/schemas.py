"""Endoscopy, biopsy, and dilation DTOs.

An endoscopy is written as one document, as it arrives on paper: the procedure,
its EREFS findings, the biopsy results, and any dilation. Biopsy results often
come a week after the scope, so a PUT replaces the whole document.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eoehelp_api.procedures import erefs
from eoehelp_api.procedures.enums import (
    BiopsyLocation,
    DilationComplication,
    DilatorType,
    EndoscopyIndication,
    EosComparator,
    ErefsVersion,
    HistologyStatus,
)


class ErefsInput(BaseModel):
    """EREFS as the report states it. Features the report omits stay null."""

    model_config = ConfigDict(extra="forbid")

    version: ErefsVersion
    edema: int | None = Field(default=None, ge=0)
    rings: int | None = Field(default=None, ge=0)
    exudates: int | None = Field(default=None, ge=0)
    furrows: int | None = Field(default=None, ge=0)
    stricture: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _valid_for_version(self) -> "ErefsInput":
        scores = self.model_dump(exclude={"version"})
        if all(value is None for value in scores.values()):
            raise ValueError("Give at least one EREFS feature, or leave EREFS out entirely.")
        bad = erefs.out_of_range(self.version, scores)
        if bad:
            maxima = erefs.SCALES[self.version].maxima
            detail = ", ".join(f"{feature} (0-{maxima[feature]})" for feature in bad)
            raise ValueError(f"Out of range for the {self.version.value} grading: {detail}.")
        return self


class ErefsRead(BaseModel):
    version: ErefsVersion
    edema: int | None
    rings: int | None
    exudates: int | None
    furrows: int | None
    stricture: int | None
    # Null unless all five features were recorded; see services/erefs.total.
    total: int | None
    max_total: int


class BiopsyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: BiopsyLocation
    peak_eos_per_hpf: int = Field(ge=0, le=1000)
    peak_eos_comparator: EosComparator = EosComparator.EXACT
    basal_zone_hyperplasia: bool | None = None
    lamina_propria_fibrosis: bool | None = None


class BiopsyRead(BiopsyInput):
    # Against <15 eos/hpf.
    histology: HistologyStatus
    # Against ≤6 eos/hpf (deep remission).
    deep_histology: HistologyStatus


class DilationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dilator_type: DilatorType = DilatorType.UNKNOWN
    pre_diameter_mm: Decimal | None = Field(default=None, ge=5, le=25, decimal_places=1)
    final_diameter_mm: Decimal | None = Field(default=None, ge=5, le=25, decimal_places=1)
    complication: DilationComplication | None = None

    @model_validator(mode="after")
    def _widens(self) -> "DilationInput":
        if (
            self.pre_diameter_mm is not None
            and self.final_diameter_mm is not None
            and self.final_diameter_mm < self.pre_diameter_mm
        ):
            raise ValueError("final_diameter_mm cannot be smaller than pre_diameter_mm.")
        return self


class DilationRead(DilationInput):
    pass


class EndoscopyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    performed_on: date
    indication: EndoscopyIndication
    facility: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)
    erefs: ErefsInput | None = None
    biopsies: list[BiopsyInput] = Field(default_factory=list, max_length=len(BiopsyLocation))
    dilation: DilationInput | None = None

    @model_validator(mode="after")
    def _one_result_per_site(self) -> "EndoscopyInput":
        locations = [biopsy.location for biopsy in self.biopsies]
        if len(locations) != len(set(locations)):
            raise ValueError("Give one peak count per biopsy site.")
        return self


class PeakCount(BaseModel):
    """The procedure's highest reported count, with how it was stated."""

    value: int
    comparator: EosComparator
    location: BiopsyLocation


class EndoscopyRead(BaseModel):
    id: uuid.UUID
    performed_on: date
    indication: EndoscopyIndication
    facility: str | None
    notes: str | None
    erefs: ErefsRead | None
    biopsies: list[BiopsyRead]
    dilation: DilationRead | None
    peak: PeakCount | None
    # Null when no biopsies were reported, which is not the same as indeterminate.
    histology: HistologyStatus | None
    # The same reading against the deep-remission cut-off.
    deep_histology: HistologyStatus | None
    remission_threshold_eos_per_hpf: int
    deep_remission_max_eos_per_hpf: int
    created_at: datetime
    updated_at: datetime


class ErefsScaleRead(BaseModel):
    version: ErefsVersion
    label: str
    maxima: dict[str, int]
    max_total: int
