import { Component, computed, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';

import { MedicationTodayItem } from '../../core/api/api-types';
import { MedicationService } from './medication.service';
import { frequencyLabel } from './frequency-labels';

/**
 * Dose logging on the same screen as the symptom log.
 *
 * Medications are the other thing a patient does daily, and putting them behind a
 * separate flow is how adherence data stops being collected. Tapping a row is one
 * action with an undo beside it, rather than a form.
 */
@Component({
  selector: 'app-dose-log',
  imports: [RouterLink, MatButtonModule, MatIconModule, MatProgressSpinnerModule, MatTooltipModule],
  template: `
    @if (loading()) {
      <div class="flex justify-center py-6"><mat-spinner diameter="24" /></div>
    } @else if (items().length === 0) {
      <p class="m-0 text-sm leading-relaxed text-on-surface-variant">
        No medications yet.
        <a routerLink="/medications" class="text-brand">Add what you are taking</a>
        and they will appear here to tick off.
      </p>
    } @else {
      <ul class="m-0 flex list-none flex-col gap-3 p-0">
        @for (item of items(); track item.medication_id) {
          <li
            class="flex flex-wrap items-center justify-between gap-3 rounded-xl
                   border border-outline-variant px-4 py-3"
          >
            <div class="min-w-0">
              <p class="m-0 font-medium">
                {{ item.generic_name }}
                @if (item.dose_label) {
                  <span class="text-on-surface-variant">· {{ item.dose_label }}</span>
                }
              </p>
              <p class="m-0 mt-0.5 text-xs text-on-surface-variant">
                {{ label(item) }}
              </p>
            </div>

            <div class="flex shrink-0 items-center gap-1">
              @if (item.doses_today.length > 0) {
                <button
                  mat-icon-button
                  type="button"
                  [matTooltip]="'Undo the last entry'"
                  [attr.aria-label]="'Undo the last entry for ' + item.generic_name"
                  (click)="undo(item)"
                >
                  <mat-icon>undo</mat-icon>
                </button>
              }
              <button
                mat-button
                type="button"
                class="!min-h-tap"
                [disabled]="busy() === item.medication_id"
                (click)="skip(item)"
              >
                Skipped
              </button>
              <button
                mat-flat-button
                type="button"
                class="!min-h-tap"
                [disabled]="busy() === item.medication_id"
                (click)="take(item)"
              >
                <mat-icon>check</mat-icon>
                Took it
              </button>
            </div>
          </li>
        }
      </ul>
    }
  `,
})
export class DoseLog {
  /** Defaults to the patient's today, resolved server-side. */
  readonly onDate = input<string | undefined>(undefined);

  private readonly medications = inject(MedicationService);

  protected readonly loading = signal(true);
  protected readonly busy = signal<string | null>(null);
  private readonly today = signal<MedicationTodayItem[]>([]);

  protected readonly items = computed(() => this.today());

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    try {
      const view = await this.medications.today(this.onDate());
      this.today.set(view.items);
    } finally {
      this.loading.set(false);
    }
  }

  protected takenCount(item: MedicationTodayItem): number {
    // A skip is recorded but is not a dose taken, so it does not count here.
    return item.doses_today.filter((d) => d.status !== 'skipped').length;
  }

  protected label(item: MedicationTodayItem): string {
    const frequency = frequencyLabel(item.frequency);
    const taken = this.takenCount(item);
    if (item.expected_today === null) {
      // As-needed: there is no denominator, so counting against one would invent
      // an expectation the patient never had.
      return taken > 0 ? `${frequency} · ${taken} logged today` : frequency;
    }
    return `${frequency} · ${taken} of ${item.expected_today} today`;
  }

  protected async take(item: MedicationTodayItem): Promise<void> {
    await this.record(item, 'taken');
  }

  protected async skip(item: MedicationTodayItem): Promise<void> {
    await this.record(item, 'skipped');
  }

  private async record(item: MedicationTodayItem, status: 'taken' | 'skipped'): Promise<void> {
    this.busy.set(item.medication_id);
    try {
      await this.medications.logDose(item.medication_id, { status });
      await this.load();
    } finally {
      this.busy.set(null);
    }
  }

  protected async undo(item: MedicationTodayItem): Promise<void> {
    // Any entry, a skip included: a mistaken "Skipped" tap needs undoing as much
    // as a mistaken "Took it", or it sits in the adherence record for good.
    const last = [...item.doses_today].sort((a, b) => a.taken_at.localeCompare(b.taken_at)).pop();
    if (!last) return;

    this.busy.set(item.medication_id);
    try {
      await this.medications.undoDose(last.id);
      await this.load();
    } finally {
      this.busy.set(null);
    }
  }
}
