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

import { describeApiError } from '../core/api-errors';
import {
  AllergenGroup,
  CatalogIngredientRead,
  CustomIngredientRead,
  FoodItemInput,
  FoodItemRead,
  IngredientRead,
  IngredientRef,
  Meal,
} from '../core/api-types';
import { FoodService } from '../core/food.service';
import {
  ALLERGEN_GROUPS,
  ALLERGEN_LABELS,
  MEALS,
  MEAL_LABELS,
  allergenSummary,
  mealForTime,
} from './food-labels';

/** What the editor starts from: an item being edited, or a food being logged again. */
export interface FoodDraftSeed {
  readonly name: string;
  readonly meal: Meal;
  readonly ingredients: readonly IngredientRead[];
}

/** One chip in the editor. */
interface DraftIngredient {
  /** Stable identity for de-duplication and `track`. */
  readonly key: string;
  readonly name: string;
  readonly code: string | null;
  readonly customId: string | null;
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
 * Built for speed, since a slow food log is one nobody keeps. Typing finds
 * catalog ingredients by name or alias, and Enter takes the top match. Text that
 * matches nothing becomes the patient's own ingredient when saved, with an
 * optional "contains" tag. The catalog decides groups for its own ingredients;
 * the patient decides them for theirs.
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
  template: `
    <form class="flex flex-col gap-4" (submit)="$event.preventDefault(); save()">
      <mat-button-toggle-group
        class="meals"
        aria-label="Meal"
        hideSingleSelectionIndicator
        [value]="meal()"
        (change)="meal.set($event.value)"
      >
        @for (option of meals; track option) {
          <mat-button-toggle [value]="option">{{ mealLabels[option] }}</mat-button-toggle>
        }
      </mat-button-toggle-group>

      <mat-form-field appearance="outline" class="w-full" subscriptSizing="dynamic">
        <mat-label>What was it?</mat-label>
        <input
          matInput
          name="food-name"
          autocomplete="off"
          [maxlength]="nameMaxLength"
          placeholder="Turkey sandwich"
          [ngModel]="name()"
          (ngModelChange)="name.set($event)"
        />
        <mat-hint>Optional if you add ingredients.</mat-hint>
      </mat-form-field>

      <mat-form-field appearance="outline" class="w-full" subscriptSizing="dynamic">
        <mat-label>Ingredients</mat-label>
        <mat-chip-grid #grid aria-label="Ingredients">
          @for (item of draft(); track item.key) {
            <mat-chip-row (removed)="remove(item)">
              {{ item.name }}
              @if (item.groups.length > 0) {
                <span class="ml-1 text-xs text-on-surface-variant">
                  · {{ summary(item.groups) }}
                </span>
              }
              <button matChipRemove type="button" [attr.aria-label]="'Remove ' + item.name">
                <mat-icon>cancel</mat-icon>
              </button>
            </mat-chip-row>
          }
          <input
            #ingredientInput
            placeholder="Type to search, Enter to add"
            [matChipInputFor]="grid"
            [matAutocomplete]="auto"
            [value]="query()"
            (input)="query.set(ingredientInput.value)"
            (matChipInputTokenEnd)="addTyped($event)"
          />
        </mat-chip-grid>
        <mat-autocomplete
          #auto="matAutocomplete"
          [autoActiveFirstOption]="true"
          (optionSelected)="pick($event)"
        >
          @for (option of options(); track option.key) {
            <mat-option [value]="option">
              <span>{{ option.name }}</span>
              @if (option.groups.length > 0) {
                <span class="ml-2 text-xs text-on-surface-variant">
                  {{ summary(option.groups) }}
                </span>
              }
            </mat-option>
          }
        </mat-autocomplete>
        <mat-hint>
          Allergen groups are filled in for ingredients we know. Anything else is saved
          as your own.
        </mat-hint>
      </mat-form-field>

      <!-- Tagging, only for ingredients the catalog does not describe. -->
      @for (item of ownIngredients(); track item.key) {
        <div class="rounded-lg border border-outline-variant px-4 py-3">
          <p class="m-0 text-sm">
            Does <span class="font-medium">{{ item.name }}</span> contain any of these?
          </p>
          <mat-chip-listbox
            class="mt-2"
            multiple
            [attr.aria-label]="'Allergen groups in ' + item.name"
          >
            @for (group of groups; track group) {
              <mat-chip-option
                [selected]="item.groups.includes(group)"
                (selectionChange)="toggleGroup(item, group, $event.selected)"
              >
                {{ groupLabels[group] }}
              </mat-chip-option>
            }
          </mat-chip-listbox>
          @if (item.customId) {
            <p class="m-0 mt-2 text-xs text-on-surface-variant">
              Changing this updates every day you have logged it.
            </p>
          }
        </div>
      }

      @if (error()) {
        <p role="alert" class="m-0 text-sm text-danger">{{ error() }}</p>
      }

      <div class="flex flex-wrap justify-end gap-2">
        <button mat-button type="button" class="!min-h-tap" (click)="cancelled.emit()">
          Cancel
        </button>
        <button
          mat-flat-button
          type="submit"
          class="!min-h-tap"
          [disabled]="!canSave() || saving()"
        >
          @if (saving()) {
            <mat-spinner diameter="18" />
          }
          {{ itemId() ? 'Save changes' : 'Add food' }}
        </button>
      </div>
    </form>
  `,
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

  protected readonly canSave = computed(
    () => this.name().trim() !== '' || this.draft().length > 0,
  );

  protected readonly ownIngredients = computed(() =>
    this.draft().filter((item) => item.code === null),
  );

  private readonly searchIndex = computed<SearchOption[]>(() => [
    ...this.customIngredients().map((row) => ({
      key: `custom:${row.id}`,
      name: row.name,
      code: null,
      customId: row.id,
      groups: row.allergen_groups,
      terms: [keyFor(row.name)],
    })),
    ...this.catalog().map((row) => ({
      key: `catalog:${row.code}`,
      name: row.name,
      code: row.code,
      customId: null,
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
    if (seed) {
      this.name.set(seed.name);
      // A re-log from the recent list takes the current meal; an edit keeps its own.
      if (this.itemId()) this.meal.set(seed.meal);
      this.draft.set(seed.ingredients.map(draftFrom));
    }
  }

  protected summary(groups: readonly AllergenGroup[]): string {
    return allergenSummary(groups);
  }

  protected pick(event: MatAutocompleteSelectedEvent): void {
    const option = event.option.value as SearchOption;
    this.add({
      key: option.key,
      name: option.name,
      code: option.code,
      customId: option.customId,
      groups: option.groups,
      savedGroups: option.groups,
    });
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
      const result = id
        ? await this.foods.update(id, payload)
        : await this.foods.log(payload);
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
    // A food named only by its ingredients ("Coffee") needs no separate name.
    const typed = this.name().trim();
    const fallback = this.draft()
      .map((item) => item.name)
      .join(', ')
      .slice(0, NAME_MAX_LENGTH);
    return {
      eaten_on: this.day(),
      meal: this.meal(),
      name: typed || fallback,
      ingredients,
    };
  }
}
