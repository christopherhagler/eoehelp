import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';

import { describeApiError } from '../../core/api-errors';
import {
  AdherenceRead,
  DoseFrequency,
  MedicationCatalogItem,
  MedicationRead,
  MedicationStopReason,
} from '../../core/api-types';
import { todayIso } from '../../core/dates';
import { MedicationService } from '../../core/medication.service';
import { FREQUENCY_LABELS, STOP_REASON_LABELS, frequencyLabel } from '../../shared/frequency-labels';

@Component({
  selector: 'app-medications',
  imports: [
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatProgressSpinnerModule,
    MatSelectModule,
  ],
  templateUrl: './medications.html',
})
export class Medications {
  private readonly medications = inject(MedicationService);

  protected readonly frequencies = Object.entries(FREQUENCY_LABELS) as [DoseFrequency, string][];
  protected readonly stopReasons = Object.entries(STOP_REASON_LABELS) as [
    MedicationStopReason,
    string,
  ][];

  protected readonly loading = signal(true);
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly catalog = signal<MedicationCatalogItem[]>([]);
  protected readonly all = signal<MedicationRead[]>([]);
  protected readonly adherence = signal<AdherenceRead[]>([]);
  protected readonly showForm = signal(false);
  protected readonly stopping = signal<string | null>(null);

  protected readonly active = computed(() => this.all().filter((m) => m.is_active));
  protected readonly past = computed(() => this.all().filter((m) => !m.is_active));

  // New medication form.
  protected medicationCode = '';
  protected doseAmount: number | null = null;
  protected doseUnit = '';
  protected frequency: DoseFrequency | '' = '';
  protected startedOn = todayIso();
  protected prescriberNote = '';

  // Stop form.
  protected endedOn = todayIso();
  protected stopReason: MedicationStopReason | '' = '';

  protected readonly today = todayIso();
  protected readonly frequencyLabel = frequencyLabel;

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    try {
      const [catalog, list, adherence] = await Promise.all([
        this.medications.catalog(),
        this.medications.list(true),
        this.medications.adherence(),
      ]);
      this.catalog.set(catalog);
      this.all.set(list);
      this.adherence.set(adherence.medications);
    } finally {
      this.loading.set(false);
    }
  }

  protected catalogEntry(code: string): MedicationCatalogItem | undefined {
    return this.catalog().find((c) => c.code === code);
  }

  protected adherenceFor(medicationId: string): AdherenceRead | undefined {
    return this.adherence().find((a) => a.medication_id === medicationId);
  }

  /** Prefills the unit from the catalog, since patients know the number not the unit. */
  protected onMedicationChosen(): void {
    this.doseUnit = this.catalogEntry(this.medicationCode)?.default_unit ?? '';
  }

  protected canAdd(): boolean {
    return this.medicationCode !== '' && this.frequency !== '' && this.startedOn !== '';
  }

  protected async add(): Promise<void> {
    if (!this.canAdd() || this.frequency === '') return;
    this.saving.set(true);
    this.error.set(null);
    try {
      await this.medications.add({
        medication_code: this.medicationCode,
        dose_amount: this.doseAmount === null ? null : String(this.doseAmount),
        dose_unit: this.doseUnit || null,
        frequency: this.frequency,
        started_on: this.startedOn,
        prescriber_note: this.prescriberNote.trim() || null,
      });
      this.resetForm();
      this.showForm.set(false);
      await this.load();
    } catch (failure: unknown) {
      this.error.set(
        describeApiError(failure, 'We could not add that. Check the dates and try again.'),
      );
    } finally {
      this.saving.set(false);
    }
  }

  private resetForm(): void {
    this.medicationCode = '';
    this.doseAmount = null;
    this.doseUnit = '';
    this.frequency = '';
    this.startedOn = todayIso();
    this.prescriberNote = '';
  }

  protected beginStop(medication: MedicationRead): void {
    this.stopping.set(medication.id);
    this.endedOn = todayIso();
    this.stopReason = '';
  }

  protected async confirmStop(medication: MedicationRead): Promise<void> {
    if (this.stopReason === '') return;
    this.saving.set(true);
    this.error.set(null);
    try {
      await this.medications.stop(medication.id, {
        ended_on: this.endedOn,
        stop_reason: this.stopReason,
      });
      this.stopping.set(null);
      await this.load();
    } catch (failure: unknown) {
      this.error.set(
        describeApiError(failure, 'We could not stop that. Check the end date and try again.'),
      );
    } finally {
      this.saving.set(false);
    }
  }

  /**
   * Only offered before any dose exists. Afterwards the API refuses, because the
   * course is the history a symptom trend was recorded against.
   */
  protected async remove(medication: MedicationRead): Promise<void> {
    this.error.set(null);
    try {
      await this.medications.remove(medication.id);
      await this.load();
    } catch (failure: unknown) {
      this.error.set(
        describeApiError(
          failure,
          'Doses have been logged against this, so it is part of your history. Stop it instead.',
        ),
      );
    }
  }

  protected stopReasonLabel(reason: MedicationStopReason | null): string {
    return reason ? STOP_REASON_LABELS[reason] : '';
  }
}
