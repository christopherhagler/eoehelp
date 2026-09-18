import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { ProductRead, ProductSummaryRead } from '../../core/api/api-types';
import { FoodService } from './food.service';
import { ProductPicker } from './product-picker';

const FOUND: ProductRead = {
  source: 'open_food_facts',
  source_id: '0048001213487',
  barcode: '0048001213487',
  name: 'Real Mayonnaise',
  brand: "Hellmann's",
  ingredients_text: 'soybean oil',
  ingredients: [],
  ingredients_complete: true,
  declared_allergens: [],
  may_contain: [],
  inferred_allergens: [],
  source_updated_at: null,
  attribution: 'Product data from Open Food Facts.',
};

const HIT: ProductSummaryRead = {
  source: FOUND.source,
  source_id: FOUND.source_id,
  barcode: FOUND.barcode,
  name: FOUND.name,
  brand: FOUND.brand,
};

class StubFoodService {
  readonly calls: string[] = [];
  searches: { query: string; resolve: (hits: ProductSummaryRead[]) => void }[] = [];
  missing = false;

  searchProducts(query: string): Promise<ProductSummaryRead[]> {
    return new Promise((resolve) => this.searches.push({ query, resolve }));
  }

  async product(source: string, id: string): Promise<ProductRead> {
    this.calls.push(`product:${source}:${id}`);
    return FOUND;
  }

  async productByBarcode(code: string): Promise<ProductRead> {
    this.calls.push(`barcode:${code}`);
    if (this.missing) throw new HttpErrorResponse({ status: 404 });
    return FOUND;
  }
}

// The component's working state is protected; the spec reaches it by name
// rather than widening the class's public surface for tests.
type Internals = {
  results(): ProductSummaryRead[];
  error(): string | null;
  onQuery(value: string): void;
  choose(hit: ProductSummaryRead): Promise<void>;
  lookUpBarcode(raw: string): Promise<void>;
};

describe('ProductPicker', () => {
  let stub: StubFoodService;

  beforeEach(async () => {
    stub = new StubFoodService();
    await TestBed.configureTestingModule({
      imports: [ProductPicker],
      providers: [{ provide: FoodService, useValue: stub }],
    }).compileComponents();
  });

  function create() {
    const fixture = TestBed.createComponent(ProductPicker);
    const chosen: ProductRead[] = [];
    fixture.componentInstance.chosen.subscribe((product) => chosen.push(product));
    fixture.detectChanges();
    return { picker: fixture.componentInstance as unknown as Internals, chosen };
  }

  it('a typed barcode is cleaned of spaces before it is looked up', async () => {
    const { picker, chosen } = create();
    await picker.lookUpBarcode('0 48001 21348 7');
    expect(stub.calls).toEqual(['barcode:048001213487']);
    expect(chosen).toEqual([FOUND]);
  });

  it('refuses a barcode that cannot be one, without asking the server', async () => {
    const { picker, chosen } = create();
    await picker.lookUpBarcode('12345');
    expect(stub.calls).toEqual([]);
    expect(chosen).toEqual([]);
    expect(picker.error()).toBe('A barcode is 8 to 14 digits.');
  });

  it('an unknown product points to logging it by name', async () => {
    stub.missing = true;
    const { picker, chosen } = create();
    await picker.lookUpBarcode('048001213487');
    expect(chosen).toEqual([]);
    expect(picker.error()).toContain('Add it by name below');
  });

  it('choosing a search result fetches the whole label', async () => {
    const { picker, chosen } = create();
    await picker.choose(HIT);
    expect(stub.calls).toEqual(['product:open_food_facts:0048001213487']);
    expect(chosen).toEqual([FOUND]);
  });

  it('a slow search cannot overwrite a newer one', async () => {
    vi.useFakeTimers();
    try {
      const { picker } = create();
      picker.onQuery('hel');
      await vi.advanceTimersByTimeAsync(400);
      picker.onQuery('hellmann');
      await vi.advanceTimersByTimeAsync(400);
      const [first, second] = stub.searches;
      second.resolve([HIT]);
      await vi.advanceTimersByTimeAsync(0);
      first.resolve([]);
      await vi.advanceTimersByTimeAsync(0);
      expect(picker.results().map((hit) => hit.name)).toEqual(['Real Mayonnaise']);
    } finally {
      vi.useRealTimers();
    }
  });
});
