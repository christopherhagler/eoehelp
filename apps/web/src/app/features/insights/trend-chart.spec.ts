import { TestBed } from '@angular/core/testing';

import { SymptomBurdenRead } from '../../core/api/api-types';
import { TrendChart } from './trend-chart';

function point(day: number, score: number | null): SymptomBurdenRead {
  return {
    period_start: `2026-08-${String(day).padStart(2, '0')}`,
    period_end: `2026-09-${String(day).padStart(2, '0')}`,
    instrument_code: 'DSQ',
    instrument_version: 'v4.0',
    days_in_window: 14,
    days_logged: score === null ? 3 : 12,
    days_scorable: score === null ? 3 : 12,
    max_score: 84,
    score,
    components: {},
  };
}

describe('TrendChart', () => {
  function render(points: SymptomBurdenRead[]): HTMLElement {
    const fixture = TestBed.createComponent(TrendChart);
    fixture.componentRef.setInput('points', points);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('breaks the line at an unscorable window instead of drawing it at zero', () => {
    const element = render([point(1, 10), point(2, 12), point(3, null), point(4, 8), point(5, 9)]);
    const paths = element.querySelectorAll('path.line');
    expect(paths.length).toBe(2);
    const baseline = Number(element.querySelector('line.baseline')?.getAttribute('y1'));
    for (const path of Array.from(paths)) {
      const ys = (path.getAttribute('d') ?? '')
        .split(/[ML]/)
        .filter((segment) => segment.trim() !== '')
        .map((segment) => Number(segment.trim().split(/\s+/)[1]));
      expect(ys.every((y) => y < baseline)).toBe(true);
    }
    // One tooltip target per scored day, none for the gap.
    expect(element.querySelectorAll('rect.hit').length).toBe(4);
  });

  it('labels the latest value and offers a table', () => {
    const element = render([point(1, 10), point(2, 21.5)]);
    expect(element.querySelector('text.end-label')?.textContent?.trim()).toBe('21.5');
    expect(element.textContent).toContain('Show as table');
  });

  it('says so when nothing can be scored yet', () => {
    const element = render([point(1, null), point(2, null)]);
    expect(element.querySelector('svg')).toBeNull();
    expect(element.textContent).toContain('No 14-day score yet');
  });
});
