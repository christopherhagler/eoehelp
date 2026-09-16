import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { Router } from '@angular/router';

import { SexAtBirth } from '../../core/api-types';
import { detectTimezone } from '../../core/dates';
import { PatientService } from '../../core/patient.service';
import { Logo } from '../../shared/logo';

const MINIMUM_AGE = 18;

@Component({
  selector: 'app-welcome',
  imports: [
    FormsModule,
    Logo,
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
  private readonly router = inject(Router);

  protected readonly sexOptions: readonly { value: SexAtBirth; label: string }[] = [
    { value: 'female', label: 'Female' },
    { value: 'male', label: 'Male' },
    { value: 'intersex', label: 'Intersex' },
    { value: 'undisclosed', label: 'Prefer not to say' },
  ];

  protected readonly timezones = Intl.supportedValuesOf('timeZone');
  protected readonly currentYear = new Date().getFullYear();
  protected readonly minimumAge = MINIMUM_AGE;

  protected displayName = '';
  protected birthYear: number | null = null;
  protected sexAtBirth: SexAtBirth | null = null;
  // An <input type="month"> gives "2021-03"; the API stores the first of the
  // month, because EoE diagnosis dates are remembered as "around March" and
  // day precision would be invented.
  protected diagnosisMonth = '';
  protected timezone = detectTimezone();

  protected acceptedTerms = false;
  protected acceptedPrivacy = false;
  protected acceptedHealthData = false;

  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly showTimezonePicker = signal(false);

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
        diagnosis_month: this.diagnosisMonth ? `${this.diagnosisMonth}-01` : null,
        timezone: this.timezone,
        consents: {
          terms_of_service: this.acceptedTerms,
          privacy_policy: this.acceptedPrivacy,
          consumer_health_data: this.acceptedHealthData,
        },
      });
      void this.router.navigate(['/today']);
    } catch {
      this.error.set('We could not create your record. Please try again.');
    } finally {
      this.saving.set(false);
    }
  }
}
