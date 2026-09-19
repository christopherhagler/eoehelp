import { Component, computed, input, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import {
  AllergenGroup,
  IngredientRead,
  ProductRead,
  ProductRef,
  ProductSnapshotRead,
} from '../../core/api/api-types';
import { ALLERGEN_GROUPS } from './food-labels';
import { IngredientLine, IngredientText } from './ingredient-text';
import { LabelFacts } from './label-facts';

/** The product chosen for a food, from a fresh lookup or an earlier snapshot. */
export interface SelectedProduct {
  readonly ref: ProductRef;
  readonly name: string;
  readonly brand: string | null;
  readonly declared: readonly AllergenGroup[];
  readonly mayContain: readonly AllergenGroup[];
  /** Groups the ingredient list implies that the "Contains" line does not name. */
  readonly undeclared: readonly AllergenGroup[];
  readonly complete: boolean;
  /** Empty for a re-log, where the label is the stored snapshot's. */
  readonly lines: readonly IngredientLine[];
  readonly attribution: string;
}

export function fromLookup(product: ProductRead): SelectedProduct {
  return {
    ref: { source: product.source, source_id: product.source_id },
    name: product.name,
    brand: product.brand,
    declared: product.declared_allergens,
    mayContain: product.may_contain,
    undeclared: product.inferred_allergens.filter(
      (group) => !product.declared_allergens.includes(group),
    ),
    complete: product.ingredients_complete,
    lines: product.ingredients.map((line) => ({
      name: line.name,
      depth: line.depth,
      recognized: line.recognized,
      note: line.note,
      additiveClass: line.additive_class,
      groups: line.allergen_groups,
    })),
    attribution: product.attribution,
  };
}

export function fromSnapshot(
  snapshot: ProductSnapshotRead,
  labelRows: readonly IngredientRead[],
): SelectedProduct {
  const inferred = new Set(labelRows.flatMap((row) => row.allergen_groups));
  return {
    ref: { snapshot_id: snapshot.snapshot_id },
    name: snapshot.name,
    brand: snapshot.brand,
    declared: snapshot.declared_allergens,
    mayContain: snapshot.may_contain,
    undeclared: ALLERGEN_GROUPS.filter(
      (group) => inferred.has(group) && !snapshot.declared_allergens.includes(group),
    ),
    complete: snapshot.ingredients_complete,
    lines: labelRows.map((row) => ({
      name: row.name,
      depth: row.depth,
      recognized: row.recognized,
      note: row.note,
      additiveClass: row.additive_class,
      groups: row.allergen_groups,
    })),
    attribution: snapshot.attribution,
  };
}

/**
 * A product's label as the patient needs to read it: the declaration, the
 * precautionary statement and the additives side by side, then every
 * ingredient in label order. See LabelFacts and IngredientText for why each is
 * shown the way it is.
 */
@Component({
  selector: 'app-product-label',
  imports: [IngredientText, LabelFacts, MatButtonModule, MatIconModule],
  template: `
    @let chosen = product();
    <div
      class="on-dark flex flex-col gap-4 rounded-[22px] p-4 sm:p-5"
      style="background: var(--eo-label-card)"
    >
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <p class="hero-muted m-0 text-xs font-bold uppercase tracking-[0.08em]">From the label</p>
          <p class="m-0 mt-0.5 font-display text-lg font-semibold">{{ chosen.name }}</p>
          <p class="hero-muted m-0 text-sm">
            {{ chosen.brand ?? 'Unknown brand' }}
            @if (chosen.lines.length > 0) {
              · {{ topLevelCount() }} ingredients
            }
          </p>
        </div>
        <button
          mat-button
          type="button"
          class="!min-h-tap shrink-0 !text-mint"
          (click)="changed.emit()"
        >
          Change
        </button>
      </div>

      <app-label-facts
        [declared]="chosen.declared"
        [undeclared]="chosen.undeclared"
        [mayContain]="chosen.mayContain"
        [additiveClasses]="additiveClasses()"
      />

      @if (!chosen.complete) {
        <p class="m-0 flex items-start gap-2 text-sm">
          <mat-icon class="!size-5 shrink-0 !text-xl" aria-hidden="true">warning</mat-icon>
          <span>
            Some of this label could not be read reliably. Check the package, and add anything
            missing below.
          </span>
        </p>
      }

      @if (chosen.lines.length > 0) {
        <app-ingredient-text [lines]="chosen.lines" aria-label="Ingredients from the label" />
      } @else {
        <p class="hero-muted m-0 text-sm">
          Its label ingredients are recorded as they were last time.
        </p>
      }
      <p class="hero-muted m-0 text-xs">{{ chosen.attribution }}</p>
    </div>
  `,
})
export class ProductLabel {
  readonly product = input.required<SelectedProduct>();
  /** The patient wants a different product, or none. */
  readonly changed = output<void>();

  protected readonly topLevelCount = computed(
    () => this.product().lines.filter((line) => line.depth === 0).length,
  );

  protected readonly additiveClasses = computed(() =>
    this.product()
      .lines.map((line) => line.additiveClass)
      .filter((cls): cls is string => cls !== null),
  );
}
