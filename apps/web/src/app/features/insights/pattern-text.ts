import { AllergenGroup, FoodPatternRead, PatternStatus } from '../../core/api/api-types';

/**
 * Everything the Insights screen may say about a food.
 *
 * These sentences are the complete set, fixed in the approved plan
 * (docs/plans/2026-09-19-insights-food-patterns.md) and pending clinical and legal
 * sign-off. They describe the patient's own log and never advise: nothing here
 * calls a food safe or suggests eating or avoiding anything. Change the wording
 * only through that plan.
 */
export const ALWAYS_SHOWN =
  "These are patterns in your own log, not a diagnosis. Symptoms don't always follow " +
  'inflammation, so a food with no pattern here can still matter. Talk to your ' +
  'gastroenterologist before changing what you eat.';

export const COUNTS_ONLY_INTRO =
  'Counts only. There are too many ingredients to test reliably from a diary, so these ' +
  'show what happened without a verdict.';

export const STRATIFICATION_NOTE =
  'Totals over the last 18 months, or your whole log if it is shorter. The comparison is ' +
  "made within each 4-week stretch, so a treatment change doesn't distort it.";

export interface PatternText {
  readonly statement: string;
  readonly notes: readonly string[];
}

export interface StatusLook {
  readonly label: string;
  readonly icon: string;
}

/** A short label and an icon per status, so colour is never the only signal. */
export const STATUS_LOOK: Record<Exclude<PatternStatus, 'counts_only'>, StatusLook> = {
  flagged: { label: 'More symptom days after', icon: 'trending_up' },
  no_pattern: { label: 'No pattern seen', icon: 'horizontal_rule' },
  cant_tell: { label: "Can't tell yet", icon: 'help' },
  not_enough_data: { label: 'Not enough data yet', icon: 'hourglass_empty' },
  no_baseline: { label: 'Eaten almost every day', icon: 'all_inclusive' },
};

function sentenceCase(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * The statement and any notes for one row.
 *
 * `name` is the food as it reads mid-sentence ("milk", "soybean oil",
 * "preservatives"); `groupName` names another allergen group the same way.
 */
export function patternText(
  pattern: FoodPatternRead,
  name: string,
  groupName: (group: AllergenGroup) => string,
): PatternText {
  const a = pattern.exposed_symptom_days;
  const n1 = pattern.exposed_days;
  const c = pattern.unexposed_symptom_days;
  const n0 = pattern.unexposed_days;

  switch (pattern.status) {
    case 'flagged': {
      const notes: string[] = [];
      if (pattern.explained_by) {
        notes.push(
          `${sentenceCase(name)} was usually eaten with ${groupName(pattern.explained_by)}, ` +
            'which may account for this.',
        );
      } else if (pattern.often_with) {
        notes.push(
          `${sentenceCase(name)} was often eaten with ${groupName(pattern.often_with)}, so this ` +
            "log can't yet tell which of the two goes with the symptom days.",
        );
      }
      if (pattern.same_day_only) {
        notes.push(
          'This only shows up when counting food from the same day, which can happen when ' +
            'softer foods are chosen on bad days.',
        );
      }
      return {
        statement:
          `Symptom days were more common after ${name}: ${a} of ${n1} days, ` +
          `compared with ${c} of ${n0} other days.`,
        notes,
      };
    }
    case 'no_pattern':
      return { statement: `No pattern seen across ${n1} days you ate ${name}.`, notes: [] };
    case 'cant_tell':
      return {
        statement:
          `Can't tell yet. Symptom days after ${name}: ${a} of ${n1}. Other days: ${c} of ${n0}. ` +
          'More days are needed to see a pattern either way.',
        notes: [],
      };
    case 'not_enough_data':
      return {
        statement: `Not enough data yet: ${name} was eaten on ${n1} logged days.`,
        notes: [],
      };
    case 'no_baseline':
      return {
        statement:
          `${sentenceCase(name)} was in almost every day's food, so there are no days ` +
          'without it to compare.',
        notes: [],
      };
    case 'counts_only':
      return {
        statement: `Symptom days after ${name}: ${a} of ${n1}. Other days: ${c} of ${n0}.`,
        notes: [],
      };
  }
}
