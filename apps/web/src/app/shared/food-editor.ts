import {
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
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
  ProductRead,
  ProductRef,
  ProductSnapshotRead,
  ProductSummaryRead,
} from '../core/api-types';
import { FoodService } from '../core/food.service';
import { BarcodeScanner, canScanBarcodes } from './barcode-scanner';
import {
  ADDITIVE_LABELS,
  ALLERGEN_GROUPS,
  ALLERGEN_LABELS,
  MEALS,
  MEAL_LABELS,
  SOURCE_LABELS,
  allergenSummary,
  mealForTime,
} from './food-labels';

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

interface LabelLine {
  readonly name: string;
  readonly depth: number;
  readonly recognized: boolean;
  readonly note: string | null;
  readonly additiveClass: string | null;
}

/** The product chosen for this food, from a fresh lookup or an earlier snapshot. */
interface SelectedProduct {
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

const MAX_OPTIONS = 8;
const NAME_MAX_LENGTH = 120;
const SEARCH_DELAY_MS = 350;
const LABEL_PREVIEW_LINES = 8;

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

function fromLookup(product: ProductRead): SelectedProduct {
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

function fromSnapshot(
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
    BarcodeScanner,
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

      <!-- A packaged product: its real label, not a guess. -->
      <section class="rounded-lg border border-outline-variant px-4 py-3" aria-label="Product">
        @if (product(); as chosen) {
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="m-0 font-medium">{{ chosen.name }}</p>
              @if (chosen.brand) {
                <p class="m-0 text-sm text-on-surface-variant">{{ chosen.brand }}</p>
              }
            </div>
            <button mat-button type="button" class="!min-h-tap shrink-0" (click)="clearProduct()">
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
                Some of this label could not be read reliably. Check the package, and add anything
                missing below.
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
                    <span class="ml-1 text-xs italic text-on-surface-variant">
                      · not recognized
                    </span>
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
        } @else if (scanning()) {
          <app-barcode-scanner
            (detected)="lookUpBarcode($event)"
            (cancelled)="scanning.set(false)"
          />
        } @else {
          <p class="m-0 text-sm font-medium">From a package?</p>
          <p class="m-0 mt-1 text-sm text-on-surface-variant">
            Find it to record the ingredients on its actual label.
          </p>
          <div class="mt-3 flex flex-wrap items-start gap-2">
            <mat-form-field appearance="outline" class="min-w-0 flex-1" subscriptSizing="dynamic">
              <mat-label>Search products</mat-label>
              <input
                matInput
                name="product-search"
                autocomplete="off"
                maxlength="100"
                placeholder="Brand and product"
                [ngModel]="productQuery()"
                (ngModelChange)="onProductQuery($event)"
              />
            </mat-form-field>
            @if (scanAvailable) {
              <button
                mat-stroked-button
                type="button"
                class="!min-h-tap"
                (click)="scanning.set(true)"
              >
                <mat-icon>barcode_scanner</mat-icon>
                Scan
              </button>
            }
          </div>
          <mat-form-field appearance="outline" class="mt-2 w-full" subscriptSizing="dynamic">
            <mat-label>Or type the barcode</mat-label>
            <input
              matInput
              name="barcode"
              inputmode="numeric"
              autocomplete="off"
              maxlength="14"
              [ngModel]="barcode()"
              (ngModelChange)="barcode.set($event)"
              (keydown.enter)="$event.preventDefault(); lookUpBarcode(barcode())"
            />
            <button
              mat-icon-button
              matSuffix
              type="button"
              aria-label="Look up this barcode"
              [disabled]="!validBarcode()"
              (click)="lookUpBarcode(barcode())"
            >
              <mat-icon>search</mat-icon>
            </button>
          </mat-form-field>

          @if (looking()) {
            <div class="mt-3 flex justify-center"><mat-spinner diameter="22" /></div>
          }
          @if (lookupError()) {
            <p role="alert" class="m-0 mt-3 text-sm text-danger">{{ lookupError() }}</p>
          }
          @if (productResults().length > 0) {
            <ul class="m-0 mt-2 flex list-none flex-col gap-1 p-0" aria-label="Products found">
              @for (hit of productResults(); track hit.source + hit.source_id) {
                <li>
                  <button
                    mat-button
                    type="button"
                    class="!h-auto !min-h-tap w-full !justify-start !py-2 text-left"
                    (click)="chooseProduct(hit)"
                  >
                    <span class="flex flex-col items-start">
                      <span>{{ hit.name }}</span>
                      <span class="text-xs text-on-surface-variant">
                        {{ hit.brand ?? 'Unknown brand' }} · {{ sourceLabels[hit.source] }}
                      </span>
                    </span>
                  </button>
                </li>
              }
            </ul>
          }
        }
      </section>

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
        <mat-hint>Optional if you add a product or ingredients.</mat-hint>
      </mat-form-field>

      <mat-form-field appearance="outline" class="w-full" subscriptSizing="dynamic">
        <mat-label>{{ product() ? 'Anything you added?' : 'Ingredients' }}</mat-label>
        <mat-chip-grid #grid aria-label="Ingredients">
          @for (item of draft(); track item.key) {
            <mat-chip-row (removed)="remove(item)">
              {{ item.name }}
              @if (item.groups.length > 0) {
                <span class="ml-1 text-xs text-on-surface-variant">
                  · {{ item.typical ? 'usually ' : '' }}{{ summary(item.groups) }}
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
                  {{ option.typical ? 'usually ' : '' }}{{ summary(option.groups) }}
                </span>
              }
            </mat-option>
          }
        </mat-autocomplete>
        <mat-hint>
          Allergen groups are filled in for ingredients we know. Anything else is saved as your own.
        </mat-hint>
      </mat-form-field>

      <!-- Dishes vary by recipe; the label is the reliable source. -->
      @for (item of typicalIngredients(); track item.key) {
        <p class="m-0 flex items-start gap-2 text-sm">
          <mat-icon class="!size-5 shrink-0 !text-xl text-brand" aria-hidden="true">info</mat-icon>
          <span>
            Recipes for {{ item.name.toLowerCase() }} vary. If it came from a package, finding the
            product above records what it really contained.
          </span>
        </p>
      }

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
export class FoodEditor implements OnInit, OnDestroy {
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
  protected readonly sourceLabels = SOURCE_LABELS;
  protected readonly nameMaxLength = NAME_MAX_LENGTH;
  protected readonly previewLines = LABEL_PREVIEW_LINES;
  protected readonly scanAvailable = canScanBarcodes();

  protected readonly meal = signal<Meal>(mealForTime());
  protected readonly name = signal('');
  protected readonly draft = signal<readonly DraftIngredient[]>([]);
  protected readonly query = signal('');
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly product = signal<SelectedProduct | null>(null);
  protected readonly productQuery = signal('');
  protected readonly productResults = signal<readonly ProductSummaryRead[]>([]);
  protected readonly barcode = signal('');
  protected readonly looking = signal(false);
  protected readonly lookupError = signal<string | null>(null);
  protected readonly scanning = signal(false);
  protected readonly showAllLines = signal(false);

  private searchTimer: ReturnType<typeof setTimeout> | null = null;
  // Responses can arrive out of order; only the newest request may update the list.
  private searchGeneration = 0;

  protected readonly canSave = computed(
    () => this.name().trim() !== '' || this.draft().length > 0 || this.product() !== null,
  );

  protected readonly validBarcode = computed(() => /^\d{8,14}$/.test(this.barcode().trim()));

  protected readonly ownIngredients = computed(() =>
    this.draft().filter((item) => item.code === null),
  );

  protected readonly typicalIngredients = computed(() =>
    this.product() ? [] : this.draft().filter((item) => item.typical),
  );

  protected readonly visibleLines = computed(() => {
    const lines = this.product()?.lines ?? [];
    return this.showAllLines() ? lines : lines.slice(0, LABEL_PREVIEW_LINES);
  });

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

  ngOnDestroy(): void {
    if (this.searchTimer !== null) clearTimeout(this.searchTimer);
  }

  protected summary(groups: readonly AllergenGroup[]): string {
    return allergenSummary(groups);
  }

  protected summaryOr(groups: readonly AllergenGroup[], empty: string): string {
    return groups.length > 0 ? allergenSummary(groups) : empty;
  }

  protected additiveLabel(additiveClass: string): string {
    return ADDITIVE_LABELS[additiveClass] ?? additiveClass;
  }

  // --- products ----------------------------------------------------------------

  protected onProductQuery(value: string): void {
    this.productQuery.set(value);
    this.lookupError.set(null);
    if (this.searchTimer !== null) clearTimeout(this.searchTimer);
    const text = value.trim();
    if (text.length < 2) {
      this.searchGeneration++;
      this.productResults.set([]);
      return;
    }
    this.searchTimer = setTimeout(() => void this.search(text), SEARCH_DELAY_MS);
  }

  private async search(text: string): Promise<void> {
    const generation = ++this.searchGeneration;
    this.looking.set(true);
    try {
      const results = await this.foods.searchProducts(text);
      if (generation !== this.searchGeneration) return;
      this.productResults.set(results);
      if (results.length === 0) {
        this.lookupError.set('No products matched. Try the brand name, or add the food below.');
      }
    } catch (failure: unknown) {
      if (generation !== this.searchGeneration) return;
      this.lookupError.set(describeApiError(failure, 'Product search failed. Try again.'));
    } finally {
      if (generation === this.searchGeneration) this.looking.set(false);
    }
  }

  protected async chooseProduct(hit: ProductSummaryRead): Promise<void> {
    await this.load(() => this.foods.product(hit.source, hit.source_id));
  }

  protected async lookUpBarcode(raw: string): Promise<void> {
    this.scanning.set(false);
    const code = raw.replace(/\D/g, '');
    if (!/^\d{8,14}$/.test(code)) {
      this.lookupError.set('A barcode is 8 to 14 digits.');
      return;
    }
    this.barcode.set(code);
    await this.load(() => this.foods.productByBarcode(code));
  }

  private async load(fetch: () => Promise<ProductRead>): Promise<void> {
    const generation = ++this.searchGeneration;
    this.looking.set(true);
    this.lookupError.set(null);
    try {
      const found = await fetch();
      if (generation !== this.searchGeneration) return;
      this.product.set(fromLookup(found));
      this.productResults.set([]);
      this.showAllLines.set(false);
      if (!this.name().trim()) this.name.set(found.name.slice(0, NAME_MAX_LENGTH));
    } catch (failure: unknown) {
      if (generation !== this.searchGeneration) return;
      const missing = failure instanceof HttpErrorResponse && failure.status === 404;
      this.lookupError.set(
        missing
          ? 'That product is not in the food databases yet. Add it by name below.'
          : describeApiError(failure, 'That product could not be loaded. Try again.'),
      );
    } finally {
      if (generation === this.searchGeneration) this.looking.set(false);
    }
  }

  protected clearProduct(): void {
    this.product.set(null);
    this.productQuery.set('');
    this.productResults.set([]);
    this.barcode.set('');
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
