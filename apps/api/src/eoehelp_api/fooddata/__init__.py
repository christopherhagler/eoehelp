"""Packaged-food data: product lookup, label parsing, and ingredient identity.

Why this exists: a generic "mayonnaise" says nothing reliable about what was
eaten. Hellmann's Real Mayonnaise contains soybean oil and calcium disodium
EDTA; a vegan mayo contains no egg at all. For a food-symptom analysis to find
a trigger — including one that is not a major allergen, such as a preservative —
the record has to hold the ingredients printed on the actual product.

Sources are Open Food Facts (parsed ingredients, additives, allergen tags; ODbL)
and USDA FoodData Central branded foods (public domain; raw label text, parsed
here). Both are called from the server only.
"""
