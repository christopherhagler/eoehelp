import { Component, computed, inject, signal } from '@angular/core';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';

import { describeApiError } from '../../core/api/api-errors';
import {
  AllergenGroup,
  FoodPatternRead,
  FoodPatternReport,
  SymptomBurdenRead,
} from '../../core/api/api-types';
import { ADDITIVE_LABELS, ALLERGEN_LABELS } from '../food/food-labels';
import { SymptomService } from '../symptoms/symptom.service';
import { DEFAULT_LAG, InsightsService, LAG_OPTIONS } from './insights.service';
import {
  ALWAYS_SHOWN,
  COUNTS_ONLY_INTRO,
  STATUS_LOOK,
  STRATIFICATION_NOTE,
  StatusLook,
  patternText,
} from './pattern-text';
import { TrendChart } from './trend-chart';

type Level = 'groups' | 'ingredients' | 'additives';

/** Below this many analyzable days, the screen asks for more logging first. */
const MIN_ANALYZABLE_DAYS = 30;
const TREND_DAYS = 90;

const LAG_LABELS: Record<number, string> = {
  0: 'The same day',
  1: 'Up to 1 day before',
  2: 'Up to 2 days before',
  3: 'Up to 3 days before',
};

interface Row {
  readonly key: string;
  readonly title: string;
  readonly look: StatusLook | null;
  readonly flagged: boolean;
  readonly statement: string;
  readonly notes: readonly string[];
  readonly exposed: Meter;
  readonly other: Meter;
}

interface Meter {
  readonly days: number;
  readonly symptomDays: number;
  readonly percent: number;
}

function meter(symptomDays: number, days: number): Meter {
  return { days, symptomDays, percent: days > 0 ? (symptomDays / days) * 100 : 0 };
}

/**
 * The patient's trend and the food patterns in their own log.
 *
 * Descriptive only, by design and by regulation: every sentence comes from
 * `pattern-text.ts`, and nothing on this screen advises a change.
 */
@Component({
  selector: 'app-insights',
  imports: [
    MatButtonToggleModule,
    MatCardModule,
    MatFormFieldModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatSelectModule,
    TrendChart,
  ],
  templateUrl: './insights.html',
  styles: `
    .levels {
      --mat-button-toggle-height: 2.75rem;
    }
    .levels ::ng-deep .mat-button-toggle {
      font-size: 0.875rem;
    }
    .levels ::ng-deep .mat-button-toggle-label-content {
      padding: 0 0.25rem;
    }
    .meter {
      height: 0.5rem;
      border-radius: 999px;
      background: var(--eo-card);
      overflow: hidden;
    }
    .meter > div {
      height: 100%;
      border-radius: 999px;
    }
    .fill-exposed {
      background: var(--eo-symptom);
    }
    .fill-other {
      background: var(--eo-teal);
    }
    .fill-neutral {
      background: var(--eo-muted);
    }
    .flag-chip {
      background: var(--eo-allergen-bg);
      color: var(--eo-allergen-text);
    }
    details > summary {
      cursor: pointer;
      min-height: 2.75rem;
      display: flex;
      align-items: center;
    }
  `,
})
export class Insights {
  private readonly insights = inject(InsightsService);
  private readonly symptoms = inject(SymptomService);

  protected readonly alwaysShown = ALWAYS_SHOWN;
  protected readonly countsOnlyIntro = COUNTS_ONLY_INTRO;
  protected readonly stratificationNote = STRATIFICATION_NOTE;
  protected readonly lagOptions = LAG_OPTIONS;
  protected readonly lagLabels = LAG_LABELS;
  protected readonly minAnalyzable = MIN_ANALYZABLE_DAYS;

  protected readonly trend = signal<readonly SymptomBurdenRead[] | null>(null);
  protected readonly trendError = signal<string | null>(null);

  protected readonly report = signal<FoodPatternReport | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly lag = signal(DEFAULT_LAG);
  protected readonly level = signal<Level>('groups');
  private generation = 0;

  protected readonly announcement = computed(() => {
    if (this.loading() || this.error()) return '';
    const report = this.report();
    return report
      ? `Food patterns updated, counting foods from ${LAG_LABELS[report.lag_days].toLowerCase()}.`
      : '';
  });

  protected readonly rows = computed<Row[]>(() => {
    const report = this.report();
    if (!report) return [];
    return report[this.level()].map((pattern) => this.row(pattern));
  });

  protected readonly tooLittle = computed(
    () => (this.report()?.analyzable_days ?? 0) < MIN_ANALYZABLE_DAYS,
  );

  protected readonly nothingFlagged = computed(
    () => !this.tooLittle() && !(this.report()?.groups ?? []).some((g) => g.status === 'flagged'),
  );

  constructor() {
    void this.loadTrend();
    void this.loadPatterns();
  }

  protected setLag(lag: number): void {
    this.lag.set(lag);
    void this.loadPatterns();
  }

  private async loadTrend(): Promise<void> {
    try {
      this.trend.set((await this.symptoms.burdenTrend(TREND_DAYS)).points);
    } catch (failure: unknown) {
      this.trendError.set(describeApiError(failure, 'Your trend could not be loaded.'));
    }
  }

  private async loadPatterns(): Promise<void> {
    // Responses can arrive out of order when the lag changes quickly; only the
    // newest request may land, or one lag's counts would show under another.
    const generation = ++this.generation;
    this.loading.set(true);
    this.error.set(null);
    try {
      const report = await this.insights.foodPatterns(this.lag());
      if (generation !== this.generation) return;
      this.report.set(report);
    } catch (failure: unknown) {
      if (generation !== this.generation) return;
      // Clear the old report: its counts belong to the previous lag.
      this.report.set(null);
      this.error.set(describeApiError(failure, 'Food patterns could not be loaded. Try again.'));
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }

  private row(pattern: FoodPatternRead): Row {
    const level = this.level();
    const { title, name } = this.names(pattern, level);
    const text = patternText(pattern, name, (group) => this.groupName(group));
    return {
      key: pattern.key,
      title,
      look: pattern.status === 'counts_only' ? null : STATUS_LOOK[pattern.status],
      flagged: pattern.status === 'flagged',
      statement: text.statement,
      notes: text.notes,
      exposed: meter(pattern.exposed_symptom_days, pattern.exposed_days),
      other: meter(pattern.unexposed_symptom_days, pattern.unexposed_days),
    };
  }

  /** The row's heading, and the food as it reads mid-sentence. */
  private names(pattern: FoodPatternRead, level: Level): { title: string; name: string } {
    if (level === 'groups') {
      const label = ALLERGEN_LABELS[pattern.key as AllergenGroup] ?? pattern.label;
      return { title: label, name: label.toLowerCase() };
    }
    if (level === 'additives') {
      const label = ADDITIVE_LABELS[pattern.key] ?? pattern.label;
      const plural = `${label}s`;
      return { title: plural.charAt(0).toUpperCase() + plural.slice(1), name: plural };
    }
    return { title: pattern.label, name: pattern.label.toLowerCase() };
  }

  private groupName(group: AllergenGroup): string {
    return ALLERGEN_LABELS[group].toLowerCase();
  }
}
