import {
  Component,
  OnInit,
  computed,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  MatAutocompleteModule,
  MatAutocompleteSelectedEvent,
  MatAutocompleteTrigger,
} from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatChipInputEvent, MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { describeApiError } from '../../core/api/api-errors';
import {
  AllergenGroup,
  CatalogIngredientRead,
  CustomIngredientRead,
  FoodItemInput,
  FoodItemRead,
  IngredientRead,
  IngredientRef,
  Meal,
  ProductRead,
  ProductSnapshotRead,
} from '../../core/api/api-types';
import {
  ALLERGEN_GROUPS,
  ALLERGEN_LABELS,
  MEALS,
  MEAL_LABELS,
  allergenSummary,
  mealForTime,
} from './food-labels';
import { FoodService } from './food.service';
import { ProductLabel, SelectedProduct, fromLookup, fromSnapshot } from './product-label';
import { ProductPicker } from './product-picker';

/** What the editor starts from: an item being edited, or a food being logged again. */
export interface FoodDraftSeed {
  readonly name: string;
  readonly meal: Meal;
  readonly ingredients: readonly IngredientRead[];
  readonly product: ProductSnapshotRead | null;
}

/** One chip in the editor: an ingredient the patient is adding. */
interface DraftIngredient {
  /** Stable identity for de-duplication and `track`. */
  readonly key: string;
  readonly name: string;
  readonly code: string | null;
  readonly customId: string | null;
  /** A dish from the catalog, whose groups are only the usual recipe's. */
  readonly typical: boolean;
  /** Groups as the patient currently has them, which may differ from `savedGroups`. */
  readonly groups: readonly AllergenGroup[];
  /** Groups as stored, so a change to an existing ingredient can be sent on save. */
  readonly savedGroups: readonly AllergenGroup[];
}

interface SearchOption {
  readonly key: string;
  readonly name: string;
  readonly code: string | null;
  readonly customId: string | null;
  readonly typical: boolean;
  readonly groups: readonly AllergenGroup[];
  readonly terms: readonly string[];
}

const MAX_OPTIONS = 8;
const NAME_MAX_LENGTH = 120;

function keyFor(name: string): string {
  return name.trim().replace(/\s+/g, ' ').toLocaleLowerCase();
}

function draftFrom(ingredient: IngredientRead): DraftIngredient {
  return {
    key: ingredient.code
      ? `catalog:${ingredient.code}`
      : `custom:${ingredient.custom_ingredient_id}`,
    name: ingredient.name,
    code: ingredient.code,
    customId: ingredient.custom_ingredient_id,
    typical: ingredient.typical,
    groups: ingredient.allergen_groups,
    savedGroups: ingredient.allergen_groups,
  };
}

function sameGroups(a: readonly AllergenGroup[], b: readonly AllergenGroup[]): boolean {
  return a.length === b.length && a.every((group) => b.includes(group));
}

/**
 * Add or edit one eaten food.
 *
 * Two routes, because precision matters and so does speed. A packaged product is
 * found by search or barcode, and its ingredients come from its actual label —
 * the only way to know that this mayonnaise contains soy and a preservative, or
 * that that one contains no egg at all. Anything else is typed, and typing finds
 * catalog ingredients by name or alias; text that matches nothing becomes the
 * patient's own ingredient, with an optional "contains" tag.
 */
@Component({
  selector: 'app-food-editor',
  imports: [
    FormsModule,
    MatAutocompleteModule,
    MatButtonModule,
    MatButtonToggleModule,
    MatChipsModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    ProductLabel,
    ProductPicker,
  ],
  styles: `
    mat-button-toggle-group.meals {
      width: 100%;
      --mat-standard-button-toggle-height: 2.75rem;
    }
    mat-button-toggle-group.meals mat-button-toggle {
      flex: 1;
      min-width: 0;
    }
    /* Four meals have to fit a 360px phone. Material's default label padding
       clips "Snack" at that width. */
    mat-button-toggle-group.meals ::ng-deep .mat-button-toggle-label-content {
      padding: 0 0.25rem;
    }
  `,
  templateUrl: './food-editor.html',
})
export class FoodEditor implements OnInit {
  readonly day = input.required<string>();
  readonly itemId = input<string | null>(null);
  readonly seed = input<FoodDraftSeed | null>(null);
  /** Supplied by the host so several editors never fetch the same lists twice. */
  readonly catalog = input<readonly CatalogIngredientRead[]>([]);
  readonly customIngredients = input<readonly CustomIngredientRead[]>([]);

  readonly saved = output<FoodItemRead>();
  readonly cancelled = output<void>();

  private readonly foods = inject(FoodService);
  private readonly trigger = viewChild(MatAutocompleteTrigger);

  protected readonly meals = MEALS;
  protected readonly mealLabels = MEAL_LABELS;
  protected readonly groups = ALLERGEN_GROUPS;
  protected readonly groupLabels = ALLERGEN_LABELS;
  protected readonly nameMaxLength = NAME_MAX_LENGTH;

  protected readonly meal = signal<Meal>(mealForTime());
  protected readonly name = signal('');
  protected readonly draft = signal<readonly DraftIngredient[]>([]);
  protected readonly query = signal('');
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly product = signal<SelectedProduct | null>(null);

  protected readonly canSave = computed(
    () => this.name().trim() !== '' || this.draft().length > 0 || this.product() !== null,
  );

  protected readonly ownIngredients = computed(() =>
    this.draft().filter((item) => item.code === null),
  );

  protected readonly typicalIngredients = computed(() =>
    this.product() ? [] : this.draft().filter((item) => item.typical),
  );

  private readonly searchIndex = computed<SearchOption[]>(() => [
    ...this.customIngredients().map((row) => ({
      key: `custom:${row.id}`,
      name: row.name,
      code: null,
      customId: row.id,
      typical: false,
      groups: row.allergen_groups,
      terms: [keyFor(row.name)],
    })),
    ...this.catalog().map((row) => ({
      key: `catalog:${row.code}`,
      name: row.name,
      code: row.code,
      customId: null,
      typical: row.is_composite,
      groups: row.allergen_groups,
      terms: [keyFor(row.name), ...row.aliases],
    })),
  ]);

  /** Exact matches first, then prefixes, then anything containing the text. */
  protected readonly options = computed<SearchOption[]>(() => {
    const text = keyFor(this.query());
    if (!text) return [];
    const chosen = new Set(this.draft().map((item) => item.key));
    const rank = (option: SearchOption): number => {
      if (option.terms.some((term) => term === text)) return 0;
      if (option.terms.some((term) => term.startsWith(text))) return 1;
      if (option.terms.some((term) => term.includes(text))) return 2;
      return -1;
    };
    return this.searchIndex()
      .filter((option) => !chosen.has(option.key))
      .map((option) => ({ option, rank: rank(option) }))
      .filter(({ rank: r }) => r >= 0)
      .sort((a, b) => a.rank - b.rank || a.option.name.localeCompare(b.option.name))
      .slice(0, MAX_OPTIONS)
      .map(({ option }) => option);
  });

  ngOnInit(): void {
    // Read once: the seed is where the draft starts, not something it tracks.
    const seed = this.seed();
    if (!seed) return;
    this.name.set(seed.name);
    // A re-log from the recent list takes the current meal; an edit keeps its own.
    if (this.itemId()) this.meal.set(seed.meal);
    const own = seed.ingredients.filter((row) => row.provenance === 'patient');
    const label = seed.ingredients.filter((row) => row.provenance === 'label');
    this.draft.set(own.map(draftFrom));
    if (seed.product) this.product.set(fromSnapshot(seed.product, label));
  }

  protected summary(groups: readonly AllergenGroup[]): string {
    return allergenSummary(groups);
  }

  // --- the product ------------------------------------------------------------

  protected useProduct(found: ProductRead): void {
    this.product.set(fromLookup(found));
    if (!this.name().trim()) this.name.set(found.name.slice(0, NAME_MAX_LENGTH));
  }

  // --- the patient's own ingredients ------------------------------------------

  protected pick(event: MatAutocompleteSelectedEvent): void {
    const option = event.option.value as SearchOption;
    this.add({ ...option, savedGroups: option.groups });
    event.option.deselect();
  }

  protected addTyped(event: MatChipInputEvent): void {
    // Enter with a highlighted suggestion is a pick, handled by `pick`. Acting on
    // it here as well would also add the half-typed text as a new ingredient.
    if (this.trigger()?.activeOption) return;

    const text = event.value.trim().replace(/\s+/g, ' ');
    if (!text) return;
    const key = keyFor(text);
    const known = this.searchIndex().find((option) => option.terms.includes(key));
    if (known) {
      this.add({ ...known, savedGroups: known.groups });
    } else {
      this.add({
        key: `new:${key}`,
        name: text,
        code: null,
        customId: null,
        typical: false,
        groups: [],
        savedGroups: [],
      });
    }
    event.chipInput.clear();
  }

  private add(item: DraftIngredient): void {
    if (!this.draft().some((existing) => existing.key === item.key)) {
      this.draft.update((items) => [...items, item]);
    }
    this.query.set('');
  }

  protected remove(item: DraftIngredient): void {
    this.draft.update((items) => items.filter((existing) => existing.key !== item.key));
  }

  protected toggleGroup(item: DraftIngredient, group: AllergenGroup, selected: boolean): void {
    this.draft.update((items) =>
      items.map((existing) => {
        if (existing.key !== item.key) return existing;
        const next = new Set(existing.groups);
        if (selected) next.add(group);
        else next.delete(group);
        return { ...existing, groups: ALLERGEN_GROUPS.filter((g) => next.has(g)) };
      }),
    );
  }

  // --- saving -------------------------------------------------------------------

  protected async save(): Promise<void> {
    if (!this.canSave() || this.saving()) return;
    this.saving.set(true);
    this.error.set(null);
    try {
      // Retagging an existing ingredient is a property of the ingredient, not of
      // this meal, so it goes through its own endpoint before the food is saved.
      for (const item of this.draft()) {
        if (item.customId && !sameGroups(item.groups, item.savedGroups)) {
          await this.foods.updateCustomIngredient(item.customId, {
            allergen_groups: [...item.groups],
          });
        }
      }

      const payload = this.buildPayload();
      const id = this.itemId();
      const result = id ? await this.foods.update(id, payload) : await this.foods.log(payload);
      this.saved.emit(result);
    } catch (failure: unknown) {
      this.error.set(describeApiError(failure, 'That did not save. Try again.'));
    } finally {
      this.saving.set(false);
    }
  }

  private buildPayload(): FoodItemInput {
    const ingredients: IngredientRef[] = this.draft().map((item) => {
      if (item.code) return { code: item.code };
      if (item.customId) return { custom_ingredient_id: item.customId };
      return { name: item.name, allergen_groups: [...item.groups] };
    });
    // A food named only by its product or ingredients needs no separate name.
    const product = this.product();
    const fallback = (
      product?.name ??
      this.draft()
        .map((item) => item.name)
        .join(', ')
    ).slice(0, NAME_MAX_LENGTH);
    return {
      eaten_on: this.day(),
      meal: this.meal(),
      name: this.name().trim() || fallback,
      product: product?.ref ?? null,
      ingredients,
    };
  }
}
