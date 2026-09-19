import { FoodPatternRead } from '../../core/api/api-types';
import { patternText } from './pattern-text';

function pattern(overrides: Partial<FoodPatternRead>): FoodPatternRead {
  return {
    key: 'milk',
    label: 'Milk',
    status: 'cant_tell',
    exposed_days: 14,
    exposed_symptom_days: 9,
    unexposed_days: 40,
    unexposed_symptom_days: 3,
    explained_by: null,
    often_with: null,
    same_day_only: false,
    risk_difference: null,
    q_value: null,
    ...overrides,
  };
}

const text = (overrides: Partial<FoodPatternRead>) =>
  patternText(pattern(overrides), 'milk', (group) => group.replace('_', ' '));

// The wording is fixed in the approved plan and pending clinical and legal
// sign-off, so these assertions are verbatim on purpose.
describe('patternText', () => {
  it('flagged', () => {
    expect(text({ status: 'flagged' })).toEqual({
      statement:
        'Symptom days were more common after milk: 9 of 14 days, compared with 3 of 40 other days.',
      notes: [],
    });
  });

  it('flagged, may be explained by another group', () => {
    expect(text({ status: 'flagged', explained_by: 'wheat' }).notes).toEqual([
      'Milk was usually eaten with wheat, which may account for this.',
    ]);
  });

  it('flagged, often eaten with another group', () => {
    expect(text({ status: 'flagged', often_with: 'egg' }).notes).toEqual([
      "Milk was often eaten with egg, so this log can't yet tell which of the two goes with the symptom days.",
    ]);
  });

  it('flagged, same day only', () => {
    expect(text({ status: 'flagged', same_day_only: true }).notes).toEqual([
      'This only shows up when counting food from the same day, which can happen when softer foods are chosen on bad days.',
    ]);
  });

  it('no pattern', () => {
    expect(text({ status: 'no_pattern' }).statement).toBe(
      'No pattern seen across 14 days you ate milk.',
    );
  });

  it("can't tell", () => {
    expect(text({ status: 'cant_tell' }).statement).toBe(
      "Can't tell yet. Symptom days after milk: 9 of 14. Other days: 3 of 40. More days are needed to see a pattern either way.",
    );
  });

  it('not enough data', () => {
    expect(text({ status: 'not_enough_data', exposed_days: 2 }).statement).toBe(
      'Not enough data yet: milk was eaten on 2 logged days.',
    );
  });

  it('no baseline', () => {
    expect(text({ status: 'no_baseline' }).statement).toBe(
      "Milk was in almost every day's food, so there are no days without it to compare.",
    );
  });

  it('counts only carries no verdict', () => {
    expect(text({ status: 'counts_only' })).toEqual({
      statement: 'Symptom days after milk: 9 of 14. Other days: 3 of 40.',
      notes: [],
    });
  });

  it('never calls a food safe or advises anything', () => {
    const all = (
      [
        'flagged',
        'no_pattern',
        'cant_tell',
        'not_enough_data',
        'no_baseline',
        'counts_only',
      ] as const
    ).flatMap((status) => {
      const t = text({ status, explained_by: 'wheat', same_day_only: true });
      return [t.statement, ...t.notes];
    });
    for (const sentence of all) {
      expect(sentence).not.toMatch(/\b(safe|avoid|stop eating|should)\b/i);
    }
  });
});
