import { Component, OnDestroy, computed, inject, output, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { describeApiError } from '../../core/api/api-errors';
import { ProductRead, ProductSummaryRead } from '../../core/api/api-types';
import { BarcodeScanner, canScanBarcodes } from './barcode-scanner';
import { SOURCE_LABELS } from './food-labels';
import { FoodService } from './food.service';

const SEARCH_DELAY_MS = 350;
const BARCODE = /^\d{8,14}$/;

/**
 * Find a packaged product by name, by typing its barcode, or by scanning it.
 *
 * Emits the full product, label included, once one is chosen. Nothing is stored
 * here: the server snapshots the label only when the food is saved.
 *
 * Its fields sit inside the food editor's form but are not part of the food, so
 * they are standalone, and Enter in them never saves the meal.
 */
@Component({
  selector: 'app-product-picker',
  imports: [
    BarcodeScanner,
    FormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
  ],
  template: `
    @if (scanning()) {
      <app-barcode-scanner (detected)="lookUpBarcode($event)" (cancelled)="scanning.set(false)" />
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
            [ngModel]="query()"
            [ngModelOptions]="{ standalone: true }"
            (ngModelChange)="onQuery($event)"
            (keydown.enter)="$event.preventDefault()"
          />
        </mat-form-field>
        @if (scanAvailable) {
          <button mat-stroked-button type="button" class="!min-h-tap" (click)="scanning.set(true)">
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
          [ngModelOptions]="{ standalone: true }"
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
      @if (error()) {
        <p role="alert" class="m-0 mt-3 text-sm text-danger">{{ error() }}</p>
      }
      @if (results().length > 0) {
        <ul class="m-0 mt-2 flex list-none flex-col gap-1 p-0" aria-label="Products found">
          @for (hit of results(); track hit.source + hit.source_id) {
            <li>
              <button
                mat-button
                type="button"
                class="!h-auto !min-h-tap w-full !justify-start !py-2 text-left"
                (click)="choose(hit)"
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
  `,
})
export class ProductPicker implements OnDestroy {
  readonly chosen = output<ProductRead>();

  private readonly foods = inject(FoodService);

  protected readonly sourceLabels = SOURCE_LABELS;
  protected readonly scanAvailable = canScanBarcodes();

  protected readonly query = signal('');
  protected readonly results = signal<readonly ProductSummaryRead[]>([]);
  protected readonly barcode = signal('');
  protected readonly looking = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly scanning = signal(false);

  protected readonly validBarcode = computed(() => BARCODE.test(this.barcode().trim()));

  private searchTimer: ReturnType<typeof setTimeout> | null = null;
  // Responses can arrive out of order; only the newest request may update the list.
  private generation = 0;

  ngOnDestroy(): void {
    if (this.searchTimer !== null) clearTimeout(this.searchTimer);
    // A response still in flight must not emit into an editor that moved on.
    this.generation++;
  }

  protected onQuery(value: string): void {
    this.query.set(value);
    this.error.set(null);
    if (this.searchTimer !== null) clearTimeout(this.searchTimer);
    const text = value.trim();
    if (text.length < 2) {
      this.generation++;
      this.results.set([]);
      return;
    }
    this.searchTimer = setTimeout(() => void this.search(text), SEARCH_DELAY_MS);
  }

  private async search(text: string): Promise<void> {
    const generation = ++this.generation;
    this.looking.set(true);
    try {
      const results = await this.foods.searchProducts(text);
      if (generation !== this.generation) return;
      this.results.set(results);
      if (results.length === 0) {
        this.error.set('No products matched. Try the brand name, or add the food below.');
      }
    } catch (failure: unknown) {
      if (generation !== this.generation) return;
      this.error.set(describeApiError(failure, 'Product search failed. Try again.'));
    } finally {
      if (generation === this.generation) this.looking.set(false);
    }
  }

  protected async choose(hit: ProductSummaryRead): Promise<void> {
    await this.load(() => this.foods.product(hit.source, hit.source_id));
  }

  protected async lookUpBarcode(raw: string): Promise<void> {
    this.scanning.set(false);
    const code = raw.replace(/\D/g, '');
    if (!BARCODE.test(code)) {
      this.error.set('A barcode is 8 to 14 digits.');
      return;
    }
    this.barcode.set(code);
    await this.load(() => this.foods.productByBarcode(code));
  }

  private async load(fetch: () => Promise<ProductRead>): Promise<void> {
    const generation = ++this.generation;
    this.looking.set(true);
    this.error.set(null);
    try {
      const found = await fetch();
      if (generation !== this.generation) return;
      this.chosen.emit(found);
    } catch (failure: unknown) {
      if (generation !== this.generation) return;
      const missing = failure instanceof HttpErrorResponse && failure.status === 404;
      this.error.set(
        missing
          ? 'That product is not in the food databases yet. Add it by name below.'
          : describeApiError(failure, 'That product could not be loaded. Try again.'),
      );
    } finally {
      if (generation === this.generation) this.looking.set(false);
    }
  }
}
