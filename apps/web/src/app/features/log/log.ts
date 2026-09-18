import { Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';

import { describeApiError } from '../../core/api/api-errors';
import { DysphagiaRelief, SymptomEntryInput } from '../../core/api/api-types';
import { addDays, formatDayLabel, todayIso } from '../../core/dates';
import { DoseLog } from '../medications/dose-log';
import { FoodLog } from '../food/food-log';
import { SymptomService } from '../symptoms/symptom.service';

interface ReliefChoice {
  readonly value: DysphagiaRelief;
  readonly label: string;
}

@Component({
  selector: 'app-log',
  imports: [
    DoseLog,
    FoodLog,
    FormsModule,
    RouterLink,
    MatButtonModule,
    MatButtonToggleModule,
    MatCardModule,
    MatCheckboxModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
  ],
  templateUrl: './log.html',
  styles: `
    /* Material's toggle buttons are sized for dense toolbars. On a flare day the
       user may be one-handed and tired, so every choice here is a large target
       well above the 44px WCAG 2.2 minimum. */
    mat-button-toggle-group.answer {
      width: 100%;
      --mat-standard-button-toggle-height: 3.25rem;
    }
    mat-button-toggle-group.answer mat-button-toggle {
      flex: 1;
      font-size: 1rem;
    }
    mat-button-toggle-group.stacked {
      flex-direction: column;
      width: 100%;
      --mat-standard-button-toggle-height: auto;
    }
    mat-button-toggle-group.stacked mat-button-toggle {
      width: 100%;
      text-align: left;
    }
    /* Material keeps toggle labels on one line, which cuts off a full answer on
       a phone. Answers here are sentences, so they wrap. */
    mat-button-toggle-group.stacked ::ng-deep .mat-button-toggle-label-content {
      white-space: normal;
      line-height: 1.35;
      padding-block: 0.75rem;
    }
  `,
})
export class Log {
  private readonly symptoms = inject(SymptomService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);

  /**
   * DSQ question 3's answers, in the instrument's order and close to its
   * wording. The order is the score (0-4), so it must not be rearranged.
   */
  protected readonly reliefChoices: readonly ReliefChoice[] = [
    { value: 'cleared_on_its_own', label: 'Nothing, it cleared on its own' },
    { value: 'drank_liquid', label: 'I drank liquid' },
    { value: 'coughed_or_gagged', label: 'I coughed or gagged' },
    { value: 'vomited', label: 'I vomited' },
    { value: 'sought_medical_attention', label: 'I needed medical attention' },
  ];

  protected readonly painLevels = [
    { value: 1, label: 'Mild' },
    { value: 2, label: 'Moderate' },
    { value: 3, label: 'Severe' },
  ];

  protected readonly entryDate = signal(todayIso());
  protected readonly loading = signal(true);
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly alreadyLogged = signal(false);

  // Tri-state on purpose: null is "not answered yet", which is what drives the
  // progressive disclosure below. A default of false would silently record a
  // symptom-free day for someone who never answered.
  protected readonly ateSolidFood = signal<boolean | null>(null);
  protected readonly dysphagia = signal<boolean | null>(null);
  protected readonly relief = signal<DysphagiaRelief | null>(null);
  protected readonly erVisit = signal(false);
  protected readonly pain = signal<boolean | null>(null);
  protected readonly painSeverity = signal<number | null>(null);

  protected readonly avoidedFoods = signal(false);
  protected readonly modifiedFoods = signal(false);
  protected readonly ateSlowly = signal(false);
  protected notes = '';

  protected readonly showExtras = signal(false);
  protected readonly showNotes = signal(false);

  protected readonly dayLabel = computed(() => formatDayLabel(this.entryDate()));
  protected readonly isBackfill = computed(() => this.entryDate() !== todayIso());

  /**
   * The minimum answer set. A symptom-free day is two taps and this goes true
   * after the second — if completing a day took longer than about a minute,
   * patients stop logging and every downstream feature loses its input.
   */
  protected readonly canSave = computed(() => {
    const ate = this.ateSolidFood();
    if (ate === null) return false;
    if (!ate) return true;
    const stuck = this.dysphagia();
    if (stuck === null) return false;
    if (stuck && this.relief() === null) return false;
    if (this.pain() === true && this.painSeverity() === null) return false;
    return true;
  });

  constructor() {
    const dateParam = this.route.snapshot.paramMap.get('entryDate');
    const today = todayIso();
    // Silently clamp rather than error: a stale bookmark or a link followed after
    // midnight should land on today, not on a rejected request.
    this.entryDate.set(dateParam && dateParam <= today ? dateParam : today);
    void this.load();
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    const existing = await this.symptoms.get(this.entryDate());
    if (existing) {
      this.alreadyLogged.set(true);
      this.ateSolidFood.set(existing.ate_solid_food);
      this.dysphagia.set(existing.dysphagia_occurred);
      this.relief.set(existing.dysphagia_relief);
      this.erVisit.set(existing.food_impaction_er_visit);
      this.pain.set(existing.odynophagia);
      this.painSeverity.set(existing.odynophagia_severity);
      this.avoidedFoods.set(existing.avoided_foods_today);
      this.modifiedFoods.set(existing.modified_foods_today);
      this.ateSlowly.set(existing.ate_unusually_slowly);
      this.notes = existing.notes ?? '';
      this.showNotes.set(existing.notes !== null);
      this.showExtras.set(
        existing.avoided_foods_today ||
          existing.modified_foods_today ||
          existing.ate_unusually_slowly,
      );
    }
    this.loading.set(false);
  }

  protected setAteSolidFood(value: boolean): void {
    this.ateSolidFood.set(value);
    if (!value) {
      // The instrument cannot ask about swallowing food on a day without any, and
      // the API rejects the combination outright. Clearing here keeps the screen
      // from holding answers it is about to be told are invalid.
      this.dysphagia.set(null);
      this.relief.set(null);
      this.erVisit.set(false);
    }
  }

  protected setDysphagia(value: boolean): void {
    this.dysphagia.set(value);
    if (!value) {
      this.relief.set(null);
      this.erVisit.set(false);
    }
  }

  protected setPain(value: boolean): void {
    this.pain.set(value);
    if (!value) {
      this.painSeverity.set(null);
    }
  }

  protected setRelief(value: DysphagiaRelief): void {
    this.relief.set(value);
    // An emergency visit is a kind of medical attention; the API rejects the
    // flag with any other answer.
    if (value !== 'sought_medical_attention') this.erVisit.set(false);
  }

  protected async save(): Promise<void> {
    if (!this.canSave()) return;
    this.saving.set(true);
    this.error.set(null);
    try {
      await this.symptoms.save(this.entryDate(), this.buildEntry());
      this.snackBar.open(`${this.dayLabel()} saved.`, undefined, { duration: 2500 });
      void this.router.navigate(['/today']);
    } catch (failure: unknown) {
      this.error.set(
        describeApiError(failure, 'That did not save. Your answers are still here — try again.'),
      );
    } finally {
      this.saving.set(false);
    }
  }

  private buildEntry(): SymptomEntryInput {
    const ate = this.ateSolidFood() === true;
    const stuck = ate ? this.dysphagia() : null;
    const relief = stuck ? this.relief() : null;

    return {
      ate_solid_food: ate,
      dysphagia_occurred: stuck,
      dysphagia_relief: relief,
      food_impaction_er_visit: relief === 'sought_medical_attention' && this.erVisit(),
      odynophagia: this.pain(),
      odynophagia_severity: this.pain() === true ? this.painSeverity() : null,
      avoided_foods_today: this.avoidedFoods(),
      modified_foods_today: this.modifiedFoods(),
      ate_unusually_slowly: this.ateSlowly(),
      notes: this.notes.trim() === '' ? null : this.notes.trim(),
    };
  }

  protected previousDay(): string {
    return addDays(this.entryDate(), -1);
  }
}
