import { Component, computed, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';

import { SymptomBurdenRead } from '../../core/api/api-types';

const WIDTH = 600;
const HEIGHT = 140;
const PAD_TOP = 12;
const PAD_BOTTOM = 8;
const PAD_RIGHT = 44;
// Room for the axis labels, so they never collide with the end label.
const PAD_LEFT = 24;

interface Plotted {
  readonly x: number;
  readonly y: number;
  readonly point: SymptomBurdenRead;
}

/**
 * The 14-day DSQ score over time, one point per day, drawn on the hero band.
 *
 * A window that cannot be scored (too few answered days) is a gap, never a
 * zero: a missing week drawn as zero would read as remission. Each point has a
 * native tooltip, and a table view lists every value, so the chart is never
 * the only way to read the numbers.
 */
@Component({
  selector: 'app-trend-chart',
  imports: [MatButtonModule],
  template: `
    @if (scored().length === 0) {
      <p class="hero-muted m-0 text-sm">
        No 14-day score yet. It appears once a fortnight has at least 7 answered days.
      </p>
    } @else if (showTable()) {
      <div class="max-h-72 overflow-y-auto rounded-2xl bg-white/10">
        <table class="w-full text-left text-sm">
          <caption class="visually-hidden">
            14-day symptom score by day
          </caption>
          <thead class="hero-muted">
            <tr>
              <th scope="col" class="px-3 py-2 font-semibold">Window ending</th>
              <th scope="col" class="px-3 py-2 font-semibold">Score (of 84)</th>
            </tr>
          </thead>
          <tbody>
            @for (point of points(); track point.period_end) {
              <tr class="border-t border-white/10">
                <td class="px-3 py-1.5 tabular-nums">{{ point.period_end }}</td>
                <td class="px-3 py-1.5 tabular-nums">{{ point.score ?? 'Not enough days' }}</td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    } @else {
      <svg
        class="block w-full"
        [attr.viewBox]="'0 0 ' + width + ' ' + height"
        role="img"
        [attr.aria-label]="summary()"
      >
        <line
          class="baseline"
          [attr.x1]="padLeft"
          [attr.x2]="width - padRight"
          [attr.y1]="baseline"
          [attr.y2]="baseline"
        />
        <text class="axis" x="0" [attr.y]="baseline">0</text>
        <text class="axis" x="0" [attr.y]="padTop + 4">
          {{ yMax() }}
        </text>
        @for (run of runs(); track $index) {
          <path class="line" [attr.d]="pathOf(run)" />
        }
        @if (last(); as end) {
          <circle class="end" [attr.cx]="end.x" [attr.cy]="end.y" r="4" />
          <text class="end-label" [attr.x]="end.x + 8" [attr.y]="end.y + 4">
            {{ end.point.score }}
          </text>
        }
        @for (p of plotted(); track p.point.period_end) {
          <rect
            class="hit"
            [attr.x]="p.x - step() / 2"
            y="0"
            [attr.width]="step()"
            [attr.height]="height"
          >
            <title>{{ p.point.period_end }}: {{ p.point.score }} of 84</title>
          </rect>
        }
      </svg>
    }
    @if (scored().length > 0) {
      <button
        mat-button
        type="button"
        class="!mt-1 !min-h-tap !px-2 !text-mint"
        (click)="showTable.set(!showTable())"
      >
        {{ showTable() ? 'Show as chart' : 'Show as table' }}
      </button>
    }
  `,
  styles: `
    .baseline {
      stroke: rgba(255, 255, 255, 0.25);
      stroke-width: 1;
    }
    .axis {
      fill: var(--eo-hero-muted);
      font-size: 12px;
    }
    .line {
      fill: none;
      stroke: var(--eo-mint);
      stroke-width: 2;
      stroke-linejoin: round;
      stroke-linecap: round;
    }
    .end {
      fill: var(--eo-mint);
      stroke: #0f3c3f;
      stroke-width: 2;
    }
    .end-label {
      fill: #ffffff;
      font-size: 14px;
      font-weight: 700;
    }
    .hit {
      fill: transparent;
    }
  `,
})
export class TrendChart {
  /** Oldest first, one per day, as the API returns them. */
  readonly points = input.required<readonly SymptomBurdenRead[]>();

  protected readonly width = WIDTH;
  protected readonly height = HEIGHT;
  protected readonly padRight = PAD_RIGHT;
  protected readonly padTop = PAD_TOP;
  protected readonly padLeft = PAD_LEFT;
  protected readonly baseline = HEIGHT - PAD_BOTTOM;
  protected readonly showTable = signal(false);

  protected readonly scored = computed(() => this.points().filter((p) => p.score !== null));

  /** Round up to a multiple of 21 (a quarter of the scale), and never below 21. */
  protected readonly yMax = computed(() => {
    const highest = Math.max(0, ...this.scored().map((p) => p.score ?? 0));
    return Math.max(21, Math.ceil(highest / 21) * 21);
  });

  protected readonly step = computed(
    () => (WIDTH - PAD_LEFT - PAD_RIGHT) / Math.max(this.points().length - 1, 1),
  );

  protected readonly plotted = computed<Plotted[]>(() => {
    const span = this.baseline - PAD_TOP;
    return this.points()
      .map((point, index) => ({ point, index }))
      .filter(({ point }) => point.score !== null)
      .map(({ point, index }) => ({
        x: PAD_LEFT + index * this.step(),
        y: this.baseline - ((point.score ?? 0) / this.yMax()) * span,
        point,
      }));
  });

  /** Consecutive scored days; an unscored day ends a run instead of dipping to zero. */
  protected readonly runs = computed<Plotted[][]>(() => {
    const runs: Plotted[][] = [];
    let current: Plotted[] = [];
    let previousIndex = -2;
    for (const plotted of this.plotted()) {
      const index = this.points().indexOf(plotted.point);
      if (index !== previousIndex + 1 && current.length > 0) {
        runs.push(current);
        current = [];
      }
      current.push(plotted);
      previousIndex = index;
    }
    if (current.length > 0) runs.push(current);
    return runs;
  });

  protected readonly last = computed(() => this.plotted().at(-1) ?? null);

  protected readonly summary = computed(() => {
    const scored = this.scored();
    const latest = scored.at(-1);
    // "Latest", with its date: the most recent windows may be unscorable, so the
    // last score can be weeks old.
    return latest
      ? `14-day symptom score over ${this.points().length} days: latest ${latest.score} of 84, ` +
          `for the window ending ${latest.period_end}, from ${scored.length} scored days. ` +
          'Lower is better.'
      : 'No 14-day score yet.';
  });

  protected pathOf(run: readonly Plotted[]): string {
    if (run.length === 1) {
      const [only] = run;
      return `M ${only.x - 1} ${only.y} L ${only.x + 1} ${only.y}`;
    }
    return run.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
  }
}
