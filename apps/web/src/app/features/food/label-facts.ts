import { Component, computed, input } from '@angular/core';

import { AllergenGroup } from '../../core/api/api-types';
import { ADDITIVE_LABELS, allergenSummary } from './food-labels';

/**
 * The three things a label says about allergens and additives, side by side.
 *
 * They are separate kinds of evidence and are never merged: the "Contains"
 * statement is the manufacturer's declaration, "may contain" is a precaution
 * about shared equipment, and groups the ingredients imply without being
 * declared are shown as such. A preservative or emulsifier can matter to an EoE
 * patient as much as a major allergen, so additives get a tile of their own.
 */
@Component({
  selector: 'app-label-facts',
  template: `
    <dl class="m-0 grid gap-2">
      <div class="tile">
        <dt>Contains</dt>
        <dd class="value" [class.allergen]="declared().length > 0">
          {{ declared().length > 0 ? summary(declared()) : 'None declared' }}
        </dd>
        @if (undeclared().length > 0) {
          <dd class="extra">+ {{ summary(undeclared()) }} in the ingredients</dd>
        }
      </div>
      <div class="tile">
        <dt>May contain</dt>
        <dd class="value">
          {{ mayContain().length > 0 ? summary(mayContain()) : 'None stated' }}
        </dd>
      </div>
      <div class="tile">
        <dt>Additives</dt>
        <dd class="value" [class.additive]="additiveSummary() !== ''">
          {{ additiveSummary() || 'None found' }}
        </dd>
      </div>
    </dl>
  `,
  styles: `
    :host {
      display: block;
      container-type: inline-size;
    }
    dl {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .tile {
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
      min-width: 0;
      padding: 0.625rem 0.75rem;
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.08);
    }
    dt {
      font-size: 0.6875rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--eo-muted);
    }
    dd {
      margin: 0;
      hyphens: auto;
      overflow-wrap: break-word;
    }
    .value {
      font-size: 0.875rem;
      font-weight: 700;
      line-height: 1.25;
    }
    .allergen {
      color: var(--eo-allergen-text);
    }
    .additive {
      color: var(--eo-additive-text);
    }
    .extra {
      font-size: 0.75rem;
      color: var(--eo-muted);
    }
    /* A phone-width card cannot fit three tiles without breaking words, so
       each fact becomes a row: label on the left, value beside it. */
    @container (max-width: 24rem) {
      dl {
        grid-template-columns: 1fr;
        gap: 0.375rem;
      }
      .tile {
        display: grid;
        grid-template-columns: 6.5rem 1fr;
        column-gap: 0.75rem;
        align-items: baseline;
      }
      .extra {
        grid-column: 2;
      }
    }
  `,
})
export class LabelFacts {
  readonly declared = input.required<readonly AllergenGroup[]>();
  /** Groups the ingredient list implies that the declaration does not name. */
  readonly undeclared = input<readonly AllergenGroup[]>([]);
  readonly mayContain = input.required<readonly AllergenGroup[]>();
  /** One entry per additive on the label, as its class ("preservative"). */
  readonly additiveClasses = input<readonly string[]>([]);

  /** "2 preservatives, emulsifier": counted by class, in first-seen order. */
  protected readonly additiveSummary = computed(() => {
    const counts = new Map<string, number>();
    for (const cls of this.additiveClasses()) counts.set(cls, (counts.get(cls) ?? 0) + 1);
    return [...counts]
      .map(([cls, n]) => {
        const label = ADDITIVE_LABELS[cls] ?? cls;
        return n > 1 ? `${n} ${label}s` : label;
      })
      .join(', ')
      .replace(/^./, (c) => c.toUpperCase());
  });

  protected summary(groups: readonly AllergenGroup[]): string {
    return allergenSummary(groups);
  }
}
