import { Component, computed, input, model, signal } from '@angular/core';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';

const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

/**
 * Month and year as two selects, emitting an ISO date on the first of the month.
 *
 * Replaces `<input type="month">`, which Firefox and desktop Safari do not
 * implement — they fall back to a plain text box, so whatever the patient typed
 * was concatenated with "-01" and sent to the API as a malformed date. That is a
 * 422 the patient cannot diagnose and cannot work around.
 *
 * Two selects also suit the data better: EoE diagnosis dates are remembered as
 * "some time in spring 2019", and a calendar picker invites false precision that
 * the API discards anyway.
 */
@Component({
  selector: 'app-month-picker',
  imports: [MatFormFieldModule, MatSelectModule],
  template: `
    <div class="grid gap-4 sm:grid-cols-2">
      <mat-form-field appearance="outline">
        <mat-label>{{ monthLabel() }}</mat-label>
        <mat-select [value]="month()" (valueChange)="setMonth($event)">
          <mat-option [value]="null">Not sure</mat-option>
          @for (name of months; track name; let index = $index) {
            <mat-option [value]="index + 1">{{ name }}</mat-option>
          }
        </mat-select>
      </mat-form-field>

      <mat-form-field appearance="outline">
        <mat-label>{{ yearLabel() }}</mat-label>
        <mat-select [value]="year()" (valueChange)="setYear($event)">
          <mat-option [value]="null">Not sure</mat-option>
          @for (option of years(); track option) {
            <mat-option [value]="option">{{ option }}</mat-option>
          }
        </mat-select>
      </mat-form-field>
    </div>
  `,
})
export class MonthPicker {
  readonly monthLabel = input('Month');
  readonly yearLabel = input('Year');
  readonly earliestYear = input(1950);

  /** ISO date on the first of the month, or null. */
  readonly value = model<string | null>(null);

  protected readonly months = MONTHS;
  protected readonly month = signal<number | null>(null);
  protected readonly year = signal<number | null>(null);

  protected readonly years = computed(() => {
    const current = new Date().getFullYear();
    const years: number[] = [];
    for (let y = current; y >= this.earliestYear(); y -= 1) {
      years.push(y);
    }
    return years;
  });

  protected setMonth(month: number | null): void {
    this.month.set(month);
    this.emit();
  }

  protected setYear(year: number | null): void {
    this.year.set(year);
    this.emit();
  }

  private emit(): void {
    const month = this.month();
    const year = this.year();
    // Both or neither. A year without a month would have to guess January, which
    // would be a date the patient never gave.
    const iso =
      month !== null && year !== null
        ? `${year}-${`${month}`.padStart(2, '0')}-01`
        : null;
    this.value.set(iso);
  }
}
