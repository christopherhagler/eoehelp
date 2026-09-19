import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { Router } from '@angular/router';

import { describeApiError } from '../../core/api/api-errors';
import { LegalDocumentSummary, SexAtBirth } from '../../core/api/api-types';
import { detectTimezone } from '../../core/dates';
import { LegalDialog } from '../legal/legal-dialog';
import { LegalService } from '../legal/legal.service';
import { PatientService } from '../../core/patient.service';
import { ReferenceService } from '../../core/reference.service';
import { MonthPicker } from '../../shared/month-picker';

const MINIMUM_AGE = 18;

@Component({
  selector: 'app-welcome',
  imports: [
    FormsModule,
    MonthPicker,
    MatButtonModule,
    MatCardModule,
    MatCheckboxModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatSelectModule,
  ],
  templateUrl: './welcome.html',
})
export class Welcome {
  private readonly patients = inject(PatientService);
  private readonly reference = inject(ReferenceService);
  private readonly router = inject(Router);

  protected readonly sexOptions: readonly { value: SexAtBirth; label: string }[] = [
    { value: 'female', label: 'Female' },
    { value: 'male', label: 'Male' },
    { value: 'intersex', label: 'Intersex' },
    { value: 'undisclosed', label: 'Prefer not to say' },
  ];

  // Populated from the API, so every option is one the server accepts. The
  // browser's own list can contain zones the server's tz database lacks, and
  // offering one of those is a dead end on this form.
  protected readonly timezones = signal<string[]>([]);
  protected readonly currentYear = new Date().getFullYear();
  protected readonly minimumAge = MINIMUM_AGE;

  protected displayName = '';
  protected birthYear: number | null = null;
  protected sexAtBirth: SexAtBirth | null = null;
  // Already an ISO date on the first of the month, produced by MonthPicker. The
  // previous version concatenated an <input type="month"> value with "-01",
  // which Firefox and desktop Safari turned into a malformed date because
  // neither implements that input type.
  protected diagnosisMonth: string | null = null;
  protected timezone = detectTimezone();

  protected acceptedTerms = false;
  protected acceptedPrivacy = false;
  protected acceptedHealthData = false;

  protected readonly saving = signal(false);
  private readonly legal = inject(LegalService);
  private readonly dialog = inject(MatDialog);
  private readonly documents = signal<LegalDocumentSummary[]>([]);

  /** The version ids being agreed to, so the record is legible as it is made. */
  protected readonly versions = computed(() =>
    this.documents()
      .map((document) => document.id)
      .join(', '),
  );

  protected readonly anyDraft = computed(() =>
    this.documents().some((document) => document.review_status === 'draft'),
  );

  /**
   * Open a document without leaving the page.
   *
   * `stopPropagation` matters as much as `preventDefault`: a link inside a
   * checkbox label otherwise toggles the checkbox too, which would record
   * agreement because someone clicked to read. The href stays real so
   * middle-click and "open in new tab" work.
   */
  protected openDocument(event: MouseEvent, slug: string): void {
    event.preventDefault();
    event.stopPropagation();
    this.dialog.open(LegalDialog, { data: slug, maxWidth: '44rem', width: '92vw' });
  }
  protected readonly error = signal<string | null>(null);
  protected readonly showTimezonePicker = signal(false);

  constructor() {
    void this.loadDocuments();
    void this.loadTimezones();
  }

  private async loadTimezones(): Promise<void> {
    try {
      const zones = await this.reference.timezones();
      this.timezones.set(zones);
      // Keep the detected zone only if the server recognises it; otherwise make
      // the patient choose rather than submitting something that will be refused.
      if (!zones.includes(this.timezone)) {
        this.timezone = zones.includes('UTC') ? 'UTC' : (zones[0] ?? 'UTC');
        this.showTimezonePicker.set(true);
      }
    } catch {
      // Not fatal: the detected zone is usually right, and the server validates.
      this.timezones.set([this.timezone]);
    }
  }

  protected canSubmit(): boolean {
    return (
      this.birthYear !== null &&
      this.currentYear - this.birthYear >= MINIMUM_AGE &&
      this.acceptedTerms &&
      this.acceptedPrivacy &&
      this.acceptedHealthData
    );
  }

  protected async submit(): Promise<void> {
    if (!this.canSubmit() || this.birthYear === null) return;
    this.saving.set(true);
    this.error.set(null);
    try {
      await this.patients.completeOnboarding({
        display_name: this.displayName.trim() || null,
        birth_year: this.birthYear,
        sex_at_birth: this.sexAtBirth,
        diagnosis_month: this.diagnosisMonth,
        timezone: this.timezone,
        consents: {
          terms_of_service: this.acceptedTerms,
          privacy_policy: this.acceptedPrivacy,
          consumer_health_data: this.acceptedHealthData,
        },
      });
      void this.router.navigate(['/today']);
    } catch (failure: unknown) {
      // Pass the API's own field-level message through. The first version showed
      // a generic line here, which left a patient stuck on the form with no idea
      // which answer was the problem.
      this.error.set(
        describeApiError(failure, 'We could not create your record. Please try again.'),
      );
    } finally {
      this.saving.set(false);
    }
  }

  private async loadDocuments(): Promise<void> {
    try {
      this.documents.set(await this.legal.list());
    } catch {
      // The versions caption and the draft notice are context, not a gate: a
      // failure here must not stop someone signing up.
      this.documents.set([]);
    }
  }
}
