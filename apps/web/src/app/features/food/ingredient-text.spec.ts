import { IngredientLine, ingredientSegments } from './ingredient-text';

function line(name: string, depth = 0): IngredientLine {
  return { name, depth, recognized: true, note: null, additiveClass: null, groups: [] };
}

function render(lines: IngredientLine[]): string {
  return ingredientSegments(lines)
    .map((segment) => (segment.kind === 'text' ? segment.text : segment.line.name))
    .join('');
}

describe('ingredientSegments', () => {
  it('lists top-level ingredients in label order', () => {
    expect(render([line('water'), line('soybean oil'), line('salt')])).toBe(
      'water, soybean oil, salt',
    );
  });

  it('puts nested ingredients in parentheses after their parent', () => {
    expect(
      render([line('mayonnaise'), line('soybean oil', 1), line('egg yolk', 1), line('mustard')]),
    ).toBe('mayonnaise (soybean oil, egg yolk), mustard');
  });

  it('closes every level it opened, including at the end', () => {
    expect(render([line('sauce'), line('stock', 1), line('celery', 2)])).toBe(
      'sauce (stock (celery))',
    );
  });

  it('treats a jump of several levels as one, so parentheses still balance', () => {
    const text = render([line('bread'), line('yeast', 3), line('salt')]);
    expect(text).toBe('bread (yeast), salt');
  });
});
