import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { describeApiError } from '../../core/api/api-errors';
import {
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
import { ALLERGEN_GROUPS, MEALS, MEAL_LABELS, allergenSummary } from './food-labels';

/** Which editor is open, if any. One at a time keeps the screen short. */
type Editing =
  | { readonly kind: 'new'; readonly seed: FoodDraftSeed | null }
  | { readonly kind: 'edit'; readonly item: FoodItemRead };

interface MealGroup {
  readonly meal: Meal;
  readonly label: string;
  readonly items: readonly FoodItemRead[];
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
  imports: [FoodEditor, MatButtonModule, MatIconModule, MatProgressSpinnerModule, MatTooltipModule],
  template: `
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
            <ul class="m-0 mt-2 flex list-none flex-col gap-2 p-0">
              @for (item of group.items; track item.id) {
                <li class="rounded-xl border border-outline-variant px-4 py-3">
                  @if (isEditing(item)) {
                    <app-food-editor
                      [day]="day()"
                      [itemId]="item.id"
                      [seed]="item"
                      [catalog]="catalog()"
                      [customIngredients]="customIngredients()"
                      (saved)="afterSave()"
                      (cancelled)="editing.set(null)"
                    />
                  } @else {
                    <div class="flex items-start justify-between gap-3">
                      <div class="min-w-0">
                        <p class="m-0 font-medium">{{ item.name }}</p>
                        @if (item.product; as product) {
                          <p
                            class="m-0 mt-0.5 flex items-center gap-1 text-xs text-on-surface-variant"
                          >
                            <mat-icon class="!size-4 !text-base" aria-hidden="true">
                              qr_code_2
                            </mat-icon>
                            {{ product.brand ? product.brand + ' · ' : '' }}ingredients from the
                            label
                          </p>
                        }
                        @if (ingredientNames(item); as names) {
                          <p class="m-0 mt-1 line-clamp-2 text-sm text-on-surface-variant">
                            {{ names }}
                          </p>
                        }
                        @if (containsLabel(item); as contains) {
                          <p class="m-0 mt-1 flex items-center gap-1 text-xs">
                            <mat-icon class="!size-4 !text-base" aria-hidden="true">
                              info
                            </mat-icon>
                            Contains {{ contains }}
                          </p>
                        }
                        @if (item.product && item.product.may_contain.length > 0) {
                          <p class="m-0 mt-0.5 text-xs text-on-surface-variant">
                            May contain {{ mayContainLabel(item) }}
                          </p>
                        }
                      </div>
                      <div class="flex shrink-0 items-center">
                        <button
                          mat-icon-button
                          type="button"
                          matTooltip="Edit"
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
                          [attr.aria-label]="'Remove ' + item.name"
                          [disabled]="!!editing()"
                          (click)="remove(item)"
                        >
                          <mat-icon>delete</mat-icon>
                        </button>
                      </div>
                    </div>
                  }
                </li>
              }
            </ul>
          </section>
        }
      </div>

      @if (newEditor(); as open) {
        <div class="mt-4 rounded-xl border border-outline-variant px-4 py-4">
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
                mat-stroked-button
                type="button"
                class="!min-h-tap"
                [attr.aria-label]="'Log ' + food.name + ' again'"
                (click)="startFrom(food)"
              >
                <mat-icon>replay</mat-icon>
                {{ food.name }}
              </button>
            }
          </div>
        }
        <button
          mat-stroked-button
          type="button"
          class="!mt-4 !min-h-tap"
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

  /** Top-level ingredients only; nested ones belong to the label's detail. */
  protected ingredientNames(item: FoodItemRead): string {
    return item.ingredients
      .filter((ingredient) => ingredient.depth === 0)
      .map((ingredient) => ingredient.name)
      .join(', ');
  }

  /**
   * Every group the food is known to contain: the label's declaration and
   * whatever its ingredients imply. Shown as text rather than colour.
   */
  protected containsLabel(item: FoodItemRead): string {
    const present = new Set([
      ...item.ingredients.flatMap((ingredient) => ingredient.allergen_groups),
      ...(item.product?.declared_allergens ?? []),
    ]);
    return allergenSummary(ALLERGEN_GROUPS.filter((group) => present.has(group))).toLowerCase();
  }

  protected mayContainLabel(item: FoodItemRead): string {
    return allergenSummary(item.product?.may_contain ?? []).toLowerCase();
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
