import { TestBed } from '@angular/core/testing';
import { MatChipInputEvent } from '@angular/material/chips';

import {
  CatalogIngredientRead,
  CustomIngredientRead,
  FoodItemInput,
  FoodItemRead,
} from '../core/api-types';
import { FoodService } from '../core/food.service';
import { FoodDraftSeed, FoodEditor } from './food-editor';
import { mealForTime } from './food-labels';

const CATALOG: CatalogIngredientRead[] = [
  { code: 'cheese', name: 'Cheese', allergen_groups: ['milk'], aliases: ['cheddar'] },
  { code: 'cream_cheese', name: 'Cream cheese', allergen_groups: ['milk'], aliases: [] },
  {
    code: 'wheat_flour',
    name: 'Wheat flour',
    allergen_groups: ['wheat'],
    aliases: ['flour'],
  },
  { code: 'rice', name: 'Rice', allergen_groups: [], aliases: [] },
];

const RELISH: CustomIngredientRead = { id: 'relish-id', name: 'Relish', allergen_groups: [] };

class StubFoodService {
  readonly calls: string[] = [];
  logged: FoodItemInput | null = null;

  async updateCustomIngredient(id: string, update: { allergen_groups?: string[] }) {
    this.calls.push(`retag:${id}:${update.allergen_groups?.join('+')}`);
    return { ...RELISH, allergen_groups: update.allergen_groups };
  }

  async log(item: FoodItemInput): Promise<FoodItemRead> {
    this.calls.push('log');
    this.logged = item;
    return { id: 'new', ...item } as unknown as FoodItemRead;
  }

  async update(id: string, item: FoodItemInput): Promise<FoodItemRead> {
    this.calls.push(`update:${id}`);
    this.logged = item;
    return { id, ...item } as unknown as FoodItemRead;
  }
}

// The component's working state is protected; the spec reaches it by name
// rather than widening the class's public surface for tests.
type Internals = {
  query: { set(value: string): void };
  options(): { name: string }[];
  draft(): { name: string; code: string | null; customId: string | null }[];
  name: { set(value: string): void };
  meal(): string;
  addTyped(event: MatChipInputEvent): void;
  toggleGroup(item: unknown, group: string, selected: boolean): void;
  save(): Promise<void>;
};

function typed(value: string): MatChipInputEvent {
  return { value, chipInput: { clear: () => undefined } } as unknown as MatChipInputEvent;
}

describe('FoodEditor', () => {
  let stub: StubFoodService;

  beforeEach(async () => {
    stub = new StubFoodService();
    await TestBed.configureTestingModule({
      imports: [FoodEditor],
      providers: [{ provide: FoodService, useValue: stub }],
    }).compileComponents();
  });

  function create(options: { seed?: FoodDraftSeed; itemId?: string } = {}) {
    const fixture = TestBed.createComponent(FoodEditor);
    fixture.componentRef.setInput('day', '2026-09-16');
    fixture.componentRef.setInput('catalog', CATALOG);
    fixture.componentRef.setInput('customIngredients', [RELISH]);
    if (options.seed) fixture.componentRef.setInput('seed', options.seed);
    if (options.itemId) fixture.componentRef.setInput('itemId', options.itemId);
    fixture.detectChanges();
    return {
      fixture,
      editor: fixture.componentInstance as unknown as Internals,
    };
  }

  describe('search', () => {
    it('ranks an exact match, then prefixes, then anything containing the text', () => {
      const { editor } = create();
      editor.query.set('cheese');
      expect(editor.options().map((o) => o.name)).toEqual(['Cheese', 'Cream cheese']);
    });

    it('finds ingredients by alias', () => {
      const { editor } = create();
      editor.query.set('flour');
      expect(editor.options().map((o) => o.name)).toEqual(['Wheat flour']);
    });

    it("includes the patient's own ingredients", () => {
      const { editor } = create();
      editor.query.set('rel');
      expect(editor.options().map((o) => o.name)).toEqual(['Relish']);
    });

    it('leaves out what is already chosen', () => {
      const { editor } = create();
      editor.addTyped(typed('cheese'));
      editor.query.set('chee');
      expect(editor.options().map((o) => o.name)).toEqual(['Cream cheese']);
    });
  });

  describe('typed text', () => {
    it('resolves a known name or alias to the catalog rather than a new ingredient', () => {
      const { editor } = create();
      editor.addTyped(typed('  FLOUR '));
      editor.addTyped(typed('relish'));
      expect(editor.draft().map((d) => [d.name, d.code, d.customId])).toEqual([
        ['Wheat flour', 'wheat_flour', null],
        ['Relish', null, 'relish-id'],
      ]);
    });

    it('does not add the same ingredient twice', () => {
      const { editor } = create();
      editor.addTyped(typed('Cheddar'));
      editor.addTyped(typed('cheese'));
      expect(editor.draft().length).toBe(1);
    });
  });

  describe('saving', () => {
    it('names a food after its ingredients when no name is given', async () => {
      const { editor } = create();
      editor.addTyped(typed('rice'));
      editor.addTyped(typed('Hot relish'));
      await editor.save();

      expect(stub.logged).toEqual({
        eaten_on: '2026-09-16',
        meal: mealForTime(),
        name: 'Rice, Hot relish',
        ingredients: [{ code: 'rice' }, { name: 'Hot relish', allergen_groups: [] }],
      });
    });

    it('sends groups chosen for a new ingredient with the food', async () => {
      const { editor } = create();
      editor.name.set('Tacos');
      editor.addTyped(typed('Taco sauce'));
      const [sauce] = editor.draft();
      editor.toggleGroup(sauce, 'wheat', true);
      editor.toggleGroup(sauce, 'soy', true);
      await editor.save();

      expect(stub.calls).toEqual(['log']);
      expect(stub.logged?.ingredients).toEqual([
        { name: 'Taco sauce', allergen_groups: ['wheat', 'soy'] },
      ]);
    });

    it('retags an existing ingredient through its own endpoint before logging', async () => {
      const { editor } = create();
      editor.addTyped(typed('relish'));
      const [relish] = editor.draft();
      editor.toggleGroup(relish, 'soy', true);
      await editor.save();

      expect(stub.calls).toEqual(['retag:relish-id:soy', 'log']);
      expect(stub.logged?.ingredients).toEqual([{ custom_ingredient_id: 'relish-id' }]);
    });

    it('an edit keeps its meal and updates in place', async () => {
      const seed: FoodDraftSeed = {
        name: 'Late snack',
        meal: mealForTime() === 'snack' ? 'breakfast' : 'snack',
        ingredients: [
          { code: 'rice', custom_ingredient_id: null, name: 'Rice', allergen_groups: [] },
        ],
      };
      const { editor } = create({ seed, itemId: 'item-1' });
      expect(editor.meal()).toBe(seed.meal);
      await editor.save();
      expect(stub.calls).toEqual(['update:item-1']);
      expect(stub.logged?.ingredients).toEqual([{ code: 'rice' }]);
    });

    it('logging a recent food again takes the current meal, not the old one', () => {
      const seed: FoodDraftSeed = {
        name: 'Porridge',
        meal: mealForTime() === 'snack' ? 'breakfast' : 'snack',
        ingredients: [],
      };
      const { editor } = create({ seed });
      expect(editor.meal()).toBe(mealForTime());
    });
  });
});
