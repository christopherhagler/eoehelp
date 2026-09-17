import { AllergenGroup, FoodDataSource, Meal } from '../core/api-types';

/** One place for these, so the log, the editor, and the eventual insight and
 * report screens cannot name the same group two ways. */
export const ALLERGEN_LABELS: Record<AllergenGroup, string> = {
  milk: 'Milk',
  wheat: 'Wheat',
  egg: 'Egg',
  soy: 'Soy',
  peanut: 'Peanut',
  tree_nut: 'Tree nut',
  fish: 'Fish',
  shellfish: 'Shellfish',
  sesame: 'Sesame',
};

/** Declaration order from the API, which is also the order groups are stored in. */
export const ALLERGEN_GROUPS = Object.keys(ALLERGEN_LABELS) as AllergenGroup[];

export const MEAL_LABELS: Record<Meal, string> = {
  breakfast: 'Breakfast',
  lunch: 'Lunch',
  dinner: 'Dinner',
  snack: 'Snack',
};

export const MEALS = Object.keys(MEAL_LABELS) as Meal[];

export const SOURCE_LABELS: Record<FoodDataSource, string> = {
  open_food_facts: 'Open Food Facts',
  usda_fdc: 'USDA',
};

/** Additive classes as the API names them. Unknown classes fall back to the raw name. */
export const ADDITIVE_LABELS: Record<string, string> = {
  preservative: 'preservative',
  antioxidant: 'antioxidant',
  emulsifier: 'emulsifier',
  thickener: 'thickener',
  colour: 'colour',
  sweetener: 'sweetener',
  flavour_enhancer: 'flavour enhancer',
  acidity_regulator: 'acidity regulator',
  raising_agent: 'raising agent',
  anti_caking: 'anti-caking agent',
  humectant: 'humectant',
  glazing: 'glazing agent',
};

export function allergenSummary(groups: readonly AllergenGroup[]): string {
  return groups.map((group) => ALLERGEN_LABELS[group]).join(', ');
}

/**
 * The meal a patient is most likely logging right now. Only a default: the
 * editor shows it selected, and changing it is one tap.
 */
export function mealForTime(date = new Date()): Meal {
  const hour = date.getHours();
  if (hour < 11) return 'breakfast';
  if (hour < 16) return 'lunch';
  if (hour < 21) return 'dinner';
  return 'snack';
}
