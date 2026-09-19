import { TestBed } from '@angular/core/testing';

import { FoodPatternRead, FoodPatternReport, SymptomBurdenTrend } from '../../core/api/api-types';
import { SymptomService } from '../symptoms/symptom.service';
import { Insights } from './insights';
import { InsightsService } from './insights.service';
import { STRATIFICATION_NOTE } from './pattern-text';

function row(key: string, status: FoodPatternRead['status'], exposed: number): FoodPatternRead {
  return {
    key,
    label: key,
    status,
    exposed_days: exposed,
    exposed_symptom_days: 1,
    unexposed_days: 50,
    unexposed_symptom_days: 5,
    explained_by: null,
    often_with: null,
    same_day_only: false,
    risk_difference: null,
    q_value: null,
  };
}

function report(overrides: Partial<FoodPatternReport> = {}): FoodPatternReport {
  return {
    method_version: 'fp-1',
    window_start: '2025-03-01',
    window_end: '2026-09-01',
    lag_days: 2,
    analyzable_days: 120,
    symptom_days: 30,
    logged_days: 140,
    complete_window_share: 0.8,
    logging_gap: 0,
    groups: [row('milk', 'flagged', 20), row('egg', 'cant_tell', 12)],
    // Already sorted by the API, most eaten first; the screen must keep that order.
    ingredients: [row('Oats', 'counts_only', 40), row('Rice', 'counts_only', 12)],
    additives: [row('preservative', 'counts_only', 9)],
    ...overrides,
  };
}

class StubInsights {
  calls: number[] = [];
  next = report();
  /** When set, each call waits to be resolved by hand, to test out-of-order responses. */
  pending: ((value: FoodPatternReport) => void)[] | null = null;
  async foodPatterns(lag = 2): Promise<FoodPatternReport> {
    this.calls.push(lag);
    if (this.pending) {
      return new Promise((resolve) => this.pending?.push(resolve));
    }
    return this.next;
  }
}

class StubSymptoms {
  async burdenTrend(): Promise<SymptomBurdenTrend> {
    return { points: [] };
  }
}

type Internals = {
  level: { set(value: 'groups' | 'ingredients' | 'additives'): void };
  setLag(lag: number): void;
};

describe('Insights', () => {
  let insights: StubInsights;

  beforeEach(async () => {
    insights = new StubInsights();
    await TestBed.configureTestingModule({
      imports: [Insights],
      providers: [
        { provide: InsightsService, useValue: insights },
        { provide: SymptomService, useValue: new StubSymptoms() },
      ],
    }).compileComponents();
  });

  async function render() {
    const fixture = TestBed.createComponent(Insights);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    return {
      fixture,
      element: fixture.nativeElement as HTMLElement,
      screen: fixture.componentInstance as unknown as Internals,
    };
  }

  it('gives every tested group a status label, not just a colour', async () => {
    const { element } = await render();
    const statuses = Array.from(element.querySelectorAll('li .status')).map((s) =>
      s.textContent?.trim(),
    );
    expect(statuses).toEqual(['trending_up More symptom days after', "help Can't tell yet"]);
  });

  it('shows counts-only rows without any verdict, in the order they were eaten most', async () => {
    const { fixture, element, screen } = await render();
    screen.level.set('ingredients');
    fixture.detectChanges();
    expect(element.querySelectorAll('li .status').length).toBe(0);
    expect(
      Array.from(element.querySelectorAll('li .row-title')).map((t) => t.textContent?.trim()),
    ).toEqual(['Oats', 'Rice']);
    expect(element.textContent).toContain('Counts only.');
    // The 4-week comparison is not true of untested counts, so it is not claimed.
    expect(element.textContent).not.toContain(STRATIFICATION_NOTE);
  });

  it('refetches when the lag changes', async () => {
    const { fixture, screen } = await render();
    screen.setLag(0);
    await fixture.whenStable();
    expect(insights.calls).toEqual([2, 0]);
  });

  it("never shows one lag's results under another when responses arrive out of order", async () => {
    const { fixture, element, screen } = await render();
    insights.pending = [];
    screen.setLag(0);
    screen.setLag(3);
    const [forLagZero, forLagThree] = insights.pending;
    forLagThree(report({ lag_days: 3, analyzable_days: 99 }));
    await fixture.whenStable();
    forLagZero(report({ lag_days: 0, analyzable_days: 11 }));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(element.textContent).toContain('From 99 days');
    expect(element.textContent).not.toContain('From 11 days');
  });

  it('says when a tab has nothing in it', async () => {
    insights.next = report({ additives: [] });
    const { fixture, element, screen } = await render();
    screen.level.set('additives');
    fixture.detectChanges();
    expect(element.textContent).toContain('Nothing logged here yet.');
  });

  it('asks for more logging when there is too little to go on', async () => {
    insights.next = report({ analyzable_days: 12 });
    const { element } = await render();
    expect(element.textContent).toContain('Log food and symptoms for a few more weeks.');
    expect(element.textContent).toContain('You have 12 so far.');
  });

  it('says plainly when nothing stands out', async () => {
    insights.next = report({ groups: [row('egg', 'no_pattern', 30)] });
    const { element } = await render();
    expect(element.textContent).toContain('No food stands out in your log so far.');
  });

  it('always carries the caveat', async () => {
    const { element } = await render();
    expect(element.textContent).toContain('These are patterns in your own log, not a diagnosis.');
  });
});
