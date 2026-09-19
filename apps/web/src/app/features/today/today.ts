import { Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';

import {
  AdherenceRead,
  AllergenGroup,
  FoodItemRead,
  SymptomBurdenRead,
  SymptomEntryRead,
} from '../../core/api/api-types';
import { AuthService } from '../../core/auth/auth.service';
import { addDays, formatDayLabel, todayIso } from '../../core/dates';
import { PatientService } from '../../core/patient.service';
import { ALLERGEN_GROUPS, ALLERGEN_LABELS } from '../food/food-labels';
import { FoodService } from '../food/food.service';
import { MedicationService } from '../medications/medication.service';
import { SymptomService } from '../symptoms/symptom.service';

/** One cell of the fortnight strip. */
interface DayCell {
  readonly date: string;
  readonly label: string;
  readonly score: number | null;
  readonly logged: boolean;
  readonly scorable: boolean;
  readonly withinBackfillWindow: boolean;
  readonly description: string;
}

const WINDOW_DAYS = 14;
const BACKFILL_DAYS = 7;

@Component({
  selector: 'app-today',
  imports: [
    RouterLink,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
  ],
  templateUrl: './today.html',
  styles: `
    /* The one hero figure on the screen: large, in the body sans, with
       proportional digits so a number like 12.5 does not look loose. */
    .hero-figure {
      font-size: 4.5rem;
      font-weight: 600;
      line-height: 0.9;
      letter-spacing: -0.03em;
    }
    .stat-value {
      font-size: 2.5rem;
      font-weight: 600;
      line-height: 1;
      letter-spacing: -0.02em;
    }

    /* Fourteen columns from one baseline. Each slot is the hover target, so
       it is taller and wider than the mark it holds. */
    .day-bars {
      display: grid;
      grid-template-columns: repeat(14, minmax(0, 1fr));
      gap: 0.3rem;
      height: 3.25rem;
      align-items: end;
    }
    .bar-slot {
      display: flex;
      height: 100%;
      align-items: flex-end;
      justify-content: center;
    }
    .bar {
      width: 100%;
      max-width: 1.5rem;
      border-radius: 4px 4px 0 0;
    }
    .bar-symptom {
      background: var(--eo-symptom);
    }
    .bar-clear {
      background: rgba(255, 255, 255, 0.4);
    }
    .bar-no-solid {
      background: rgba(255, 255, 255, 0.16);
    }
    .bar-missing {
      border: 1.5px dashed rgba(255, 255, 255, 0.35);
      border-bottom: 0;
    }
    .bar-today {
      border-color: var(--eo-mint);
    }
  `,
})
export class Today {
  protected readonly auth = inject(AuthService);
  private readonly patients = inject(PatientService);
  private readonly symptoms = inject(SymptomService);
  private readonly medications = inject(MedicationService);
  private readonly foods = inject(FoodService);

  protected readonly loading = signal(true);
  protected readonly entries = signal<readonly SymptomEntryRead[]>([]);
  protected readonly burden = signal<SymptomBurdenRead | null>(null);
  protected readonly adherence = signal<AdherenceRead | null>(null);
  protected readonly foodsToday = signal<readonly FoodItemRead[]>([]);

  protected readonly today = todayIso();
  protected readonly todayLabel = new Intl.DateTimeFormat(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  }).format(new Date());

  protected readonly profile = this.patients.profile;

  protected readonly todaysEntry = computed(
    () => this.entries().find((e) => e.entry_date === this.today) ?? null,
  );

  /** The fortnight, oldest first, with a cell for every day including gaps. */
  protected readonly days = computed<DayCell[]>(() => {
    const byDate = new Map(this.entries().map((e) => [e.entry_date, e]));
    const earliestBackfill = addDays(this.today, -BACKFILL_DAYS);

    return Array.from({ length: WINDOW_DAYS }, (_, index) => {
      const date = addDays(this.today, index - (WINDOW_DAYS - 1));
      const entry = byDate.get(date);
      const score = entry?.daily_score ?? null;
      return {
        date,
        label: formatDayLabel(date, this.today),
        score,
        logged: entry !== undefined,
        scorable: score !== null,
        withinBackfillWindow: date >= earliestBackfill,
        description: this.describe(date, entry),
      };
    });
  });

  protected readonly missedDays = computed(() =>
    this.days().filter((d) => !d.logged && d.withinBackfillWindow && d.date !== this.today),
  );

  protected readonly loggedInWindow = computed(() => this.days().filter((d) => d.logged).length);

  /** How many more scorable days before a 14-day score can be produced. */
  protected readonly daysUntilScorable = computed(() => {
    const current = this.burden();
    if (current === null || current.score !== null) return 0;
    const minimum = Number(current.components['minimum_scorable_days'] ?? 7);
    return Math.max(minimum - current.days_scorable, 0);
  });

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    try {
      // The tiles are extras: if either fails, the symptom view still loads.
      const [list, burden, adherence, foods] = await Promise.all([
        this.symptoms.list(addDays(this.today, -(WINDOW_DAYS - 1)), this.today),
        this.symptoms.burden(),
        this.medications.adherence().catch(() => null),
        this.foods.forDay(this.today).catch(() => []),
      ]);
      this.entries.set(list.entries);
      this.burden.set(burden);
      const rows = adherence?.medications ?? [];
      this.adherence.set(rows.find((row) => row.percentage !== null) ?? rows[0] ?? null);
      this.foodsToday.set(foods);
      if (this.patients.profile() === null) {
        await this.patients.loadProfile();
      }
    } finally {
      this.loading.set(false);
    }
  }

  private describe(date: string, entry: SymptomEntryRead | undefined): string {
    const label = formatDayLabel(date, this.today);
    if (!entry) return `${label}: not logged`;
    if (!entry.ate_solid_food) return `${label}: no solid food, so not scored`;
    return `${label}: ${entry.daily_score} out of 6`;
  }

  /** Greeting name, falling back to nothing rather than to an email address. */
  protected readonly greeting = computed(() => {
    const name = this.profile()?.display_name?.trim();
    return name ? `Hello, ${name}` : 'Hello';
  });

  /** Every allergen group today's food touched: declared or in the ingredients. */
  protected readonly groupsToday = computed(() => {
    const present = new Set<AllergenGroup>();
    for (const item of this.foodsToday()) {
      item.product?.declared_allergens.forEach((group) => present.add(group));
      item.ingredients.forEach((row) => row.allergen_groups.forEach((g) => present.add(g)));
    }
    return ALLERGEN_GROUPS.filter((group) => present.has(group));
  });

  protected groupLabel(group: AllergenGroup): string {
    return ALLERGEN_LABELS[group].toLowerCase();
  }

  protected rounded(value: number): number {
    return Math.round(value);
  }

  /** Bar height in px: a score of 6 fills the strip; the rest is a stub or outline. */
  protected barHeight(day: DayCell): number {
    if (!day.logged) return 10;
    if (day.score === null) return 5;
    return 8 + (day.score / 6) * 44;
  }
}
