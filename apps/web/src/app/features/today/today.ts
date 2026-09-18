import { Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';

import { SymptomBurdenRead, SymptomEntryRead } from '../../core/api/api-types';
import { AuthService } from '../../core/auth/auth.service';
import { addDays, formatDayLabel, todayIso } from '../../core/dates';
import { PatientService } from '../../core/patient.service';
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
    MatProgressBarModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
  ],
  templateUrl: './today.html',
  styles: `
    .day-strip {
      display: grid;
      grid-template-columns: repeat(7, minmax(0, 1fr));
      gap: 0.5rem;
    }
    @media (min-width: 640px) {
      .day-strip {
        grid-template-columns: repeat(14, minmax(0, 1fr));
      }
    }
  `,
})
export class Today {
  protected readonly auth = inject(AuthService);
  private readonly patients = inject(PatientService);
  private readonly symptoms = inject(SymptomService);

  protected readonly loading = signal(true);
  protected readonly entries = signal<readonly SymptomEntryRead[]>([]);
  protected readonly burden = signal<SymptomBurdenRead | null>(null);

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
      const [list, burden] = await Promise.all([
        this.symptoms.list(addDays(this.today, -(WINDOW_DAYS - 1)), this.today),
        this.symptoms.burden(),
      ]);
      this.entries.set(list.entries);
      this.burden.set(burden);
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
}
