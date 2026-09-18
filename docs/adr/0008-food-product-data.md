# ADR 0008 — Real product labels from Open Food Facts and USDA FoodData Central

**Status:** Accepted · 2026-09-17
**Extends:** [ADR 0007](0007-food-and-ingredient-logging.md) (food and ingredient logging)

## Context

ADR 0007's catalog tagged generic foods with allergen groups: "Mayonnaise → egg".
That is wrong in both directions for real products:

- **Hellmann's Real Mayonnaise** contains soybean oil (soy) and calcium disodium
  EDTA, a preservative. The generic tag missed both.
- **Vegan mayonnaises** contain no egg at all. They do contain chickpea, xanthan
  gum, nisin, and potato or rice protein.

A patient whose EoE is driven by something that is not a major allergen, such as a
preservative, an emulsifier, or a gum, can only find it if the record holds the
ingredients printed on the product they actually ate.

## Decision

### Sources

**Open Food Facts and USDA FoodData Central branded foods**, both called from
the server.

- **Open Food Facts** returns ingredients already parsed into taxonomy IDs,
  additive E-numbers, and allergen and traces tags. The data is licensed under
  the ODbL: attribution is shown wherever the data appears, and **the
  share-alike terms need a lawyer's reading before launch**.
- **USDA FoodData Central** is public domain and has strong coverage of US
  packaged foods by UPC. Its ingredients arrive as raw label text only.
- Commercial APIs were rejected. They are paid per call, their terms usually
  forbid storing the data (which conflicts with snapshots), and they would add
  another vendor handling patient food queries.

Search asks both sources concurrently and merges the results. Branded results
come first, and a product with the same barcode in both sources is shown once,
preferring Open Food Facts. Barcode lookup tries Open Food Facts and falls back
to USDA. When one source is down, the other still answers. When both are down,
lookups return a 503 that points to logging by name, and nothing else breaks.
Results are cached in process for 10 minutes. The query text is never logged.

### What is stored

- **`food_products` holds immutable label snapshots**, keyed by source, source
  ID, and a hash of the label content. The application database role may insert
  and select rows but never update or delete them. A changed label becomes a new
  row, so a logged meal always points at the label as it was.
- **The server fetches the label itself.** A client names a product (source and
  ID, or an existing snapshot ID) and can never supply label ingredients.
- **Every logged ingredient row carries a canonical key** in Open Food Facts'
  form (`en:soya-oil`, `en:e385`), a **provenance** (`label` or `patient`), its
  nesting depth, a **recognized** flag, and any stated purpose ("to protect
  freshness").
- **Label rows get their allergen groups when read**, from the classifier, so an
  improvement to the classifier corrects past days.
- **Allergen information is kept in three separate forms**:
  - **declared**: the "Contains:" statement
  - **may contain**: precautionary and shared-facility statements, which are
    plausibly relevant to trace exposure in EoE
  - **inferred**: groups the ingredient list implies

  When the declaration and the inferred groups disagree, the screen shows it.
- **Catalog dishes are marked composite** (mayonnaise, bread, soy sauce, hummus,
  and similar). Their groups are shown as "usually", and the editor suggests
  finding the actual product.

### Parsing and vocabulary

- **The label parser** (`food/products/labels.py`) handles:
  - nested ingredient lists
  - "contains 2% or less of"
  - purpose notes
  - the allergen statement and every precautionary statement
  - trailing debris such as addresses

  It is also applied to Open Food Facts' own parse, which carries label phrasing
  and scanning errors into its nodes.
- **The vocabulary** (`food/products/vocabulary.py`) maps US label spellings onto Open
  Food Facts keys and holds about 80 common additives with their E-numbers and
  classes. Unknown names get a slug key and are marked unrecognized, which the
  screen shows rather than hides.
- **The allergen classifier** handles the cases naive matching gets wrong:
  buckwheat, coconut milk, cocoa butter, nutmeg, butternut squash, eggplant, and
  cream of tartar. It does not treat "mayonnaise" as egg.

**Pending clinical confirmation:** the classifier rules, the additive classes,
and the composite list.

## Consequences

- `httpx` is a runtime dependency.
- Production refuses to start with USDA's `DEMO_KEY`.
- Open Food Facts requires a User-Agent that identifies the application.
- **Rate limits:** USDA allows 1,000 requests an hour with a key. Open Food Facts
  allows about 10 searches and 100 product reads a minute. Both limits are fine
  for a closed beta and not for launch. **Before launch, mirror both datasets
  locally**; that also removes the runtime dependency and any third-party view
  of query traffic. The full Open Food Facts ingredient taxonomy replaces the
  curated vocabulary at the same time.
- **Barcode scanning** uses the browser's built-in `BarcodeDetector`, so no image
  leaves the device. Safari on iOS has no `BarcodeDetector`, so iPhone users type
  the number for now. A WebAssembly fallback (for example, ZXing) is planned
  before launch.
- Tests never reach the network. The default test provider behaves as an outage.
  Recorded responses in `tests/food/fixtures` drive the mapping and API
  tests, and `httpx.MockTransport` drives the client and provider tests.
