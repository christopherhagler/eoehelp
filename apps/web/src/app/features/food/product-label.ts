import { Component, computed, input, output, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import {
  AllergenGroup,
  IngredientRead,
  ProductRead,
  ProductRef,
  ProductSnapshotRead,
} from '../../core/api/api-types';
import { ADDITIVE_LABELS, ALLERGEN_GROUPS, allergenSummary } from './food-labels';

interface LabelLine {
  readonly name: string;
  readonly depth: number;
  readonly recognized: boolean;
  readonly note: string | null;
  readonly additiveClass: string | null;
}

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
  readonly lines: readonly LabelLine[];
  readonly attribution: string;
}

const LABEL_PREVIEW_LINES = 8;

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
    })),
    attribution: snapshot.attribution,
  };
}

/**
 * A product's label as the patient needs to read it.
 *
 * The "Contains" statement, precautionary "may contain" warnings, and groups the
 * ingredients imply but the statement leaves out are shown separately, because
 * they are different kinds of evidence. Ingredients the vocabulary does not
 * recognize are marked rather than hidden.
 */
@Component({
  selector: 'app-product-label',
  imports: [MatButtonModule, MatIconModule],
  template: `
    @let chosen = product();
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="m-0 font-medium">{{ chosen.name }}</p>
        @if (chosen.brand) {
          <p class="m-0 text-sm text-on-surface-variant">{{ chosen.brand }}</p>
        }
      </div>
      <button mat-button type="button" class="!min-h-tap shrink-0" (click)="changed.emit()">
        Change
      </button>
    </div>

    <dl class="m-0 mt-3 grid gap-1 text-sm">
      <div class="flex gap-2">
        <dt class="font-medium">Contains:</dt>
        <dd class="m-0">{{ summaryOr(chosen.declared, 'none declared') }}</dd>
      </div>
      @if (chosen.mayContain.length > 0) {
        <div class="flex gap-2">
          <dt class="font-medium">May contain:</dt>
          <dd class="m-0">{{ summary(chosen.mayContain) }}</dd>
        </div>
      }
      @if (chosen.undeclared.length > 0) {
        <div class="flex gap-2">
          <dt class="font-medium">Ingredients also suggest:</dt>
          <dd class="m-0">{{ summary(chosen.undeclared) }}</dd>
        </div>
      }
    </dl>

    @if (!chosen.complete) {
      <p class="m-0 mt-3 flex items-start gap-2 text-sm">
        <mat-icon class="!size-5 shrink-0 !text-xl" aria-hidden="true">warning</mat-icon>
        <span>
          Some of this label could not be read reliably. Check the package, and add anything missing
          below.
        </span>
      </p>
    }

    @if (chosen.lines.length > 0) {
      <ul class="m-0 mt-3 list-none p-0 text-sm" aria-label="Ingredients from the label">
        @for (line of visibleLines(); track $index) {
          <li class="py-0.5" [style.padding-left.rem]="line.depth * 1.25">
            {{ line.name }}
            @if (line.additiveClass) {
              <span class="ml-1 text-xs text-on-surface-variant">
                · {{ additiveLabel(line.additiveClass) }}
              </span>
            }
            @if (line.note) {
              <span class="ml-1 text-xs text-on-surface-variant">({{ line.note }})</span>
            }
            @if (!line.recognized) {
              <span class="ml-1 text-xs italic text-on-surface-variant"> · not recognized </span>
            }
          </li>
        }
      </ul>
      @if (chosen.lines.length > previewLines) {
        <button
          mat-button
          type="button"
          class="!min-h-tap !px-2"
          (click)="showAllLines.set(!showAllLines())"
        >
          {{ showAllLines() ? 'Show fewer' : 'Show all ' + chosen.lines.length }}
        </button>
      }
    } @else {
      <p class="m-0 mt-3 text-sm text-on-surface-variant">
        Its label ingredients are recorded as they were last time.
      </p>
    }
    <p class="m-0 mt-2 text-xs text-on-surface-variant">{{ chosen.attribution }}</p>
  `,
})
export class ProductLabel {
  readonly product = input.required<SelectedProduct>();
  /** The patient wants a different product, or none. */
  readonly changed = output<void>();

  protected readonly previewLines = LABEL_PREVIEW_LINES;
  protected readonly showAllLines = signal(false);

  protected readonly visibleLines = computed(() => {
    const lines = this.product().lines;
    return this.showAllLines() ? lines : lines.slice(0, LABEL_PREVIEW_LINES);
  });

  protected summary(groups: readonly AllergenGroup[]): string {
    return allergenSummary(groups);
  }

  protected summaryOr(groups: readonly AllergenGroup[], empty: string): string {
    return groups.length > 0 ? allergenSummary(groups) : empty;
  }

  protected additiveLabel(additiveClass: string): string {
    return ADDITIVE_LABELS[additiveClass] ?? additiveClass;
  }
}
