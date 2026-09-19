import { NgTemplateOutlet } from '@angular/common';
import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { describeApiError } from '../../core/api/api-errors';
import {
  AllergenGroup,
  CatalogIngredientRead,
  CustomIngredientRead,
  FoodItemInput,
  FoodItemRead,
  IngredientRead,
  Meal,
  RecentFood,
} from '../../core/api/api-types';
import { FoodService } from './food.service';
import { FoodDraftSeed, FoodEditor } from './food-editor';
import { ALLERGEN_GROUPS, ALLERGEN_LABELS, MEALS, MEAL_LABELS } from './food-labels';
import { IngredientLine, IngredientText } from './ingredient-text';
import { LabelFacts } from './label-facts';

/** Which editor is open, if any. One at a time keeps the screen short. */
type Editing =
  | { readonly kind: 'new'; readonly seed: FoodDraftSeed | null }
  | { readonly kind: 'edit'; readonly item: FoodItemRead };

interface MealGroup {
  readonly meal: Meal;
  readonly label: string;
  readonly items: readonly FoodItemRead[];
}

function toLine(row: IngredientRead): IngredientLine {
  return {
    name: row.name,
    depth: row.depth,
    recognized: row.recognized,
    note: row.note,
    additiveClass: row.additive_class,
    groups: row.allergen_groups,
  };
}

/** The patient's own ingredients, as references; label rows come with the product. */
function refsFor(ingredients: readonly IngredientRead[]): FoodItemInput['ingredients'] {
  return ingredients
    .filter((ingredient) => ingredient.provenance === 'patient')
    .map((ingredient) =>
      ingredient.code
        ? { code: ingredient.code }
        : { custom_ingredient_id: ingredient.custom_ingredient_id },
    );
}

/**
 * What the patient ate on one day, on the same screen as the symptom log.
 *
 * Recent foods sit above the list, because most meals are repeats and
 * re-logging one should take two taps rather than a search. Deleting offers an
 * undo instead of asking for confirmation first: the undo is cheaper for the
 * patient and just as safe.
 */
@Component({
  selector: 'app-food-log',
  imports: [
    FoodEditor,
    IngredientText,
    LabelFacts,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    NgTemplateOutlet,
  ],
  template: `
    <ng-template #actions let-item let-dark="dark">
      <div class="-mr-2 -mt-1 flex shrink-0 items-center">
        <button
          mat-icon-button
          type="button"
          matTooltip="Edit"
          [class.!text-white]="dark"
          [attr.aria-label]="'Edit ' + item.name"
          [disabled]="!!editing()"
          (click)="editing.set({ kind: 'edit', item })"
        >
          <mat-icon>edit</mat-icon>
        </button>
        <button
          mat-icon-button
          type="button"
          matTooltip="Remove"
          [class.!text-white]="dark"
          [attr.aria-label]="'Remove ' + item.name"
          [disabled]="!!editing()"
          (click)="remove(item)"
        >
          <mat-icon>delete</mat-icon>
        </button>
      </div>
    </ng-template>

    @if (loading()) {
      <div class="flex justify-center py-6"><mat-spinner diameter="24" /></div>
    } @else {
      @if (loadError()) {
        <p role="alert" class="m-0 mb-3 text-sm text-danger">{{ loadError() }}</p>
      }

      @if (groups().length === 0 && !editing()) {
        <p class="m-0 text-sm leading-relaxed text-on-surface-variant">
          Nothing logged yet. Adding what you ate, down to the ingredients, is how patterns become
          visible over time.
        </p>
      }

      <div class="flex flex-col gap-4">
        @for (group of groups(); track group.meal) {
          <section [attr.aria-label]="group.label">
            <h3
              class="m-0 text-xs font-semibold uppercase tracking-[0.1em]
                     text-on-surface-variant"
            >
              {{ group.label }}
            </h3>
            <ul class="m-0 mt-2 flex list-none flex-col gap-3 p-0">
              @for (item of group.items; track item.id) {
                <li>
                  @if (isEditing(item)) {
                    <div class="rounded-[22px] bg-subtle p-4">
                      <app-food-editor
                        [day]="day()"
                        [itemId]="item.id"
                        [seed]="item"
                        [catalog]="catalog()"
                        [customIngredients]="customIngredients()"
                        (saved)="afterSave()"
                        (cancelled)="editing.set(null)"
                      />
                    </div>
                  } @else if (item.product; as product) {
                    <!-- A packaged product: its own label, in full. -->
                    <article
                      class="on-dark flex flex-col gap-4 rounded-[22px] p-4 sm:p-5"
                      style="background: var(--eo-label-card)"
                      [attr.aria-label]="item.name"
                    >
                      <div class="flex items-start justify-between gap-2">
                        <div class="min-w-0">
                          <p class="hero-muted m-0 text-xs font-bold uppercase tracking-[0.08em]">
                            From the label
                          </p>
                          <p class="m-0 mt-0.5 font-display text-lg font-semibold">
                            {{ item.name }}
                          </p>
                          <p class="hero-muted m-0 text-sm">
                            {{ product.brand ?? 'Unknown brand'
                            }}{{ item.name !== product.name ? ' · ' + product.name : '' }}
                          </p>
                        </div>
                        <ng-container
                          [ngTemplateOutlet]="actions"
                          [ngTemplateOutletContext]="{ $implicit: item, dark: true }"
                        />
                      </div>
                      <app-label-facts
                        [declared]="product.declared_allergens"
                        [undeclared]="undeclared(item)"
                        [mayContain]="product.may_contain"
                        [additiveClasses]="additiveClasses(labelLines(item))"
                      />
                      @if (labelLines(item).length > 0) {
                        <app-ingredient-text [lines]="labelLines(item)" />
                      }
                      @if (ownLines(item).length > 0) {
                        <div>
                          <p
                            class="hero-muted m-0 mb-1 text-xs font-bold uppercase tracking-[0.08em]"
                          >
                            You added
                          </p>
                          <app-ingredient-text [lines]="ownLines(item)" />
                        </div>
                      }
                    </article>
                  } @else {
                    <!-- A food logged by name: the patient's own ingredients. -->
                    <article
                      class="flex flex-col gap-3 rounded-[22px] bg-subtle p-4"
                      [attr.aria-label]="item.name"
                    >
                      <div class="flex items-start justify-between gap-2">
                        <p class="m-0 pt-2 font-semibold">{{ item.name }}</p>
                        <ng-container
                          [ngTemplateOutlet]="actions"
                          [ngTemplateOutletContext]="{ $implicit: item, dark: false }"
                        />
                      </div>
                      @let groups = groupsOf(item);
                      @if (groups.definite.length + groups.usual.length > 0) {
                        <div class="flex flex-wrap gap-1.5">
                          @for (group of groups.definite; track group) {
                            <span class="chip chip-allergen">
                              <mat-icon class="!size-4 !text-base" aria-hidden="true"
                                >error</mat-icon
                              >
                              Contains {{ groupLabel(group) }}
                            </span>
                          }
                          @for (group of groups.usual; track group) {
                            <span class="chip chip-caution">
                              Usually contains {{ groupLabel(group) }}
                            </span>
                          }
                        </div>
                      }
                      @if (ownLines(item).length > 0) {
                        <app-ingredient-text [lines]="ownLines(item)" />
                      } @else {
                        <p class="m-0 text-sm text-muted">No ingredients recorded.</p>
                      }
                    </article>
                  }
                </li>
              }
            </ul>
          </section>
        }
      </div>

      @if (newEditor(); as open) {
        <div class="mt-4 rounded-[22px] bg-subtle p-4">
          <app-food-editor
            [day]="day()"
            [seed]="open.seed"
            [catalog]="catalog()"
            [customIngredients]="customIngredients()"
            (saved)="afterSave()"
            (cancelled)="editing.set(null)"
          />
        </div>
      } @else if (!editing()) {
        @if (recent().length > 0) {
          <h3
            class="m-0 mt-5 text-xs font-semibold uppercase tracking-[0.1em]
                   text-on-surface-variant"
          >
            Eat one of these again?
          </h3>
          <!-- Buttons, not chips: a display chip is not focusable, and this row
               has to work from a keyboard and a switch device. -->
          <div class="mt-2 flex flex-wrap gap-2" role="group" aria-label="Recent foods">
            @for (food of recent(); track food.name) {
              <button
                mat-button
                type="button"
                class="!min-h-tap !bg-subtle !px-4 !text-on-surface"
                [attr.aria-label]="'Log ' + food.name + ' again'"
                (click)="startFrom(food)"
              >
                <mat-icon>add</mat-icon>
                {{ food.name }}
              </button>
            }
          </div>
        }
        <button
          mat-stroked-button
          type="button"
          class="!mt-4 !min-h-tap !w-full !border-dashed"
          (click)="editing.set({ kind: 'new', seed: null })"
        >
          <mat-icon>add</mat-icon>
          Add food
        </button>
      }
    }
  `,
})
export class FoodLog implements OnInit {
  /** The patient's calendar day being logged. */
  readonly day = input.required<string>();

  private readonly foods = inject(FoodService);
  private readonly snackBar = inject(MatSnackBar);

  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);
  protected readonly items = signal<readonly FoodItemRead[]>([]);
  protected readonly recent = signal<readonly RecentFood[]>([]);
  protected readonly catalog = signal<readonly CatalogIngredientRead[]>([]);
  protected readonly customIngredients = signal<readonly CustomIngredientRead[]>([]);
  protected readonly editing = signal<Editing | null>(null);

  protected readonly groups = computed<MealGroup[]>(() =>
    MEALS.map((meal) => ({
      meal,
      label: MEAL_LABELS[meal],
      items: this.items().filter((item) => item.meal === meal),
    })).filter((group) => group.items.length > 0),
  );

  protected readonly newEditor = computed(() => {
    const open = this.editing();
    return open?.kind === 'new' ? open : null;
  });

  ngOnInit(): void {
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      const [items, recent, catalog, custom] = await Promise.all([
        this.foods.forDay(this.day()),
        this.foods.recent(),
        this.foods.catalog(),
        this.foods.customIngredients(),
      ]);
      this.items.set(items);
      this.recent.set(recent);
      this.catalog.set(catalog);
      this.customIngredients.set(custom);
      this.loadError.set(null);
    } catch (failure: unknown) {
      this.loadError.set(describeApiError(failure, 'Food for this day could not be loaded.'));
    } finally {
      this.loading.set(false);
    }
  }

  protected isEditing(item: FoodItemRead): boolean {
    const open = this.editing();
    return open?.kind === 'edit' && open.item.id === item.id;
  }

  /** The label's own rows, in label order. */
  protected labelLines(item: FoodItemRead): IngredientLine[] {
    return item.ingredients.filter((row) => row.provenance === 'label').map(toLine);
  }

  /** What the patient typed or added on top of a label. */
  protected ownLines(item: FoodItemRead): IngredientLine[] {
    return item.ingredients.filter((row) => row.provenance === 'patient').map(toLine);
  }

  /** Groups the label's ingredients imply that its "Contains" line leaves out. */
  protected undeclared(item: FoodItemRead): AllergenGroup[] {
    const declared = new Set(item.product?.declared_allergens ?? []);
    const implied = new Set(
      item.ingredients
        .filter((row) => row.provenance === 'label')
        .flatMap((row) => row.allergen_groups),
    );
    return ALLERGEN_GROUPS.filter((group) => implied.has(group) && !declared.has(group));
  }

  protected additiveClasses(lines: readonly IngredientLine[]): string[] {
    return lines.map((line) => line.additiveClass).filter((cls): cls is string => cls !== null);
  }

  /**
   * Groups a typed food contains. A catalog dish ("mayonnaise") only usually
   * contains its groups, since recipes differ, so those are kept apart rather
   * than stated as fact.
   */
  protected groupsOf(item: FoodItemRead): { definite: AllergenGroup[]; usual: AllergenGroup[] } {
    const definite = new Set<AllergenGroup>();
    const usual = new Set<AllergenGroup>();
    for (const row of item.ingredients) {
      for (const group of row.allergen_groups) (row.typical ? usual : definite).add(group);
    }
    return {
      definite: ALLERGEN_GROUPS.filter((group) => definite.has(group)),
      usual: ALLERGEN_GROUPS.filter((group) => usual.has(group) && !definite.has(group)),
    };
  }

  protected groupLabel(group: AllergenGroup): string {
    return ALLERGEN_LABELS[group].toLowerCase();
  }

  protected startFrom(food: RecentFood): void {
    this.editing.set({ kind: 'new', seed: food });
  }

  protected async afterSave(): Promise<void> {
    this.editing.set(null);
    // Reload rather than splice: the save may have created an ingredient or
    // retagged one, and both the list and the search index need to reflect it.
    await this.load();
  }

  protected async remove(item: FoodItemRead): Promise<void> {
    try {
      await this.foods.remove(item.id);
    } catch (failure: unknown) {
      this.snackBar.open(describeApiError(failure, 'That could not be removed.'), 'OK');
      return;
    }
    this.items.update((items) => items.filter((existing) => existing.id !== item.id));

    const undo = this.snackBar.open(`Removed ${item.name}.`, 'Undo', { duration: 6000 });
    undo.onAction().subscribe(() => void this.restore(item));
  }

  private async restore(item: FoodItemRead): Promise<void> {
    try {
      await this.foods.log({
        eaten_on: item.eaten_on,
        meal: item.meal,
        name: item.name,
        product: item.product ? { snapshot_id: item.product.snapshot_id } : null,
        ingredients: refsFor(item.ingredients),
      });
    } catch (failure: unknown) {
      this.snackBar.open(describeApiError(failure, 'That could not be put back.'), 'OK');
    }
    await this.load();
  }
}
