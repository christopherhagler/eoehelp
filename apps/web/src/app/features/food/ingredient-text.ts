import { Component, computed, input } from '@angular/core';

import { AllergenGroup } from '../../core/api/api-types';
import { ADDITIVE_LABELS, allergenSummary } from './food-labels';

/** One ingredient as a label lists it, from a lookup or a stored snapshot. */
export interface IngredientLine {
  readonly name: string;
  /** 0 for a top-level ingredient, 1 for one inside it, and so on. */
  readonly depth: number;
  readonly recognized: boolean;
  readonly note: string | null;
  readonly additiveClass: string | null;
  readonly groups: readonly AllergenGroup[];
}

export type IngredientSegment =
  | { readonly kind: 'text'; readonly text: string }
  | { readonly kind: 'ingredient'; readonly line: IngredientLine };

/**
 * Lay a nested ingredient list back out the way a label prints it:
 * "mayonnaise (soybean oil, egg yolk), mustard".
 *
 * Depth only ever steps in by one; a jump of several levels (a parser slip)
 * is treated as one, so the parentheses always balance.
 */
export function ingredientSegments(lines: readonly IngredientLine[]): IngredientSegment[] {
  const segments: IngredientSegment[] = [];
  let depth = 0;
  lines.forEach((line, index) => {
    const level = index === 0 ? 0 : Math.max(0, Math.min(line.depth, depth + 1));
    if (index > 0) {
      if (level > depth) {
        segments.push({ kind: 'text', text: ' (' });
      } else {
        segments.push({ kind: 'text', text: ')'.repeat(depth - level) + ', ' });
      }
    }
    depth = level;
    segments.push({ kind: 'ingredient', line });
  });
  if (depth > 0) segments.push({ kind: 'text', text: ')'.repeat(depth) });
  return segments;
}

/**
 * Every ingredient, in label order, as running text.
 *
 * Every piece of text is its own element: a bare text node next to template
 * line breaks keeps a space, which would print "oats , milk".
 *
 * Nothing is cut short: an ingredient that matters to one patient is buried in
 * the middle of the list as often as at the start. Ingredients in an allergen
 * group are set in bold and named in the accessible text, additives carry their
 * class, and anything the vocabulary does not recognise is marked rather than
 * dropped.
 */
@Component({
  selector: 'app-ingredient-text',
  template: `
    <p class="m-0 text-sm leading-relaxed">
      @for (segment of segments(); track $index) {
        @if (segment.kind === 'text') {
          <span>{{ segment.text }}</span>
        } @else {
          @let line = segment.line;
          <span [class.allergen]="line.groups.length > 0" [class.unrecognized]="!line.recognized">{{
            line.name
          }}</span>
          @if (line.groups.length > 0) {
            <span class="visually-hidden"> ({{ summary(line.groups) }})</span>
          }
          @if (line.additiveClass) {
            <span class="tag">&nbsp;{{ additiveLabel(line.additiveClass) }}</span>
          }
          @if (line.note) {
            <span class="note">&nbsp;({{ line.note }})</span>
          }
          @if (!line.recognized) {
            <span class="visually-hidden"> (not recognised)</span>
          }
        }
      }
    </p>
    @if (hasUnrecognized()) {
      <p class="note m-0 mt-2 text-xs">
        <span class="unrecognized">Dotted underline</span>: not in our ingredient list yet, so it is
        not counted in any group.
      </p>
    }
  `,
  styles: `
    :host {
      display: block;
    }
    .allergen {
      font-weight: 700;
      color: var(--eo-allergen-text);
    }
    .tag {
      font-size: 0.75rem;
      font-weight: 700;
      color: var(--eo-additive-text);
      white-space: nowrap;
    }
    .note {
      color: var(--eo-muted);
    }
    .unrecognized {
      text-decoration: underline dotted;
      text-underline-offset: 3px;
    }
  `,
})
export class IngredientText {
  readonly lines = input.required<readonly IngredientLine[]>();

  protected readonly segments = computed(() => ingredientSegments(this.lines()));
  protected readonly hasUnrecognized = computed(() => this.lines().some((l) => !l.recognized));

  protected summary(groups: readonly AllergenGroup[]): string {
    return allergenSummary(groups);
  }

  protected additiveLabel(additiveClass: string): string {
    return ADDITIVE_LABELS[additiveClass] ?? additiveClass;
  }
}
