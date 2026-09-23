/**
 * The contract with the API, re-exported from the generated OpenAPI types.
 *
 * `api-client/schema.d.ts` is generated from `packages/openapi/schema.json`,
 * which FastAPI emits and CI diffs. A backend response-shape change therefore
 * becomes a TypeScript error here rather than a runtime surprise in a clinical
 * screen — which matters more than usual on this product, because fields like
 * eos/hpf and EREFS sub-scores transpose silently and dangerously.
 *
 * Regenerate with `just api-types`. Never hand-edit the generated file.
 */
import type { components } from '../../api-client/schema';

type Schemas = components['schemas'];

export type AccessTokenResponse = Schemas['AccessTokenResponse'];
export type SessionUser = Schemas['SessionUser'];

export type ConsentAcceptance = Schemas['ConsentAcceptance'];
export type ConsentRecord = Schemas['ConsentRecord'];
export type OnboardingRequest = Schemas['OnboardingRequest'];
export type OnboardingResponse = Schemas['OnboardingResponse'];
export type PatientProfile = Schemas['PatientProfile'];
export type PatientProfileUpdate = Schemas['PatientProfileUpdate'];
export type SexAtBirth = Schemas['SexAtBirth'];

export type MedicationCatalogItem = Schemas['MedicationCatalogItem'];
export type MedicationCreate = Schemas['MedicationCreate'];
export type MedicationRead = Schemas['MedicationRead'];
export type MedicationStop = Schemas['MedicationStop'];
export type MedicationToday = Schemas['MedicationToday'];
export type MedicationTodayItem = Schemas['MedicationTodayItem'];
export type DoseCreate = Schemas['DoseCreate'];
export type DoseRead = Schemas['DoseRead'];
export type DoseStatus = Schemas['DoseStatus'];
export type DoseFrequency = Schemas['DoseFrequency'];
export type DrugClass = Schemas['DrugClass'];
export type MedicationStopReason = Schemas['MedicationStopReason'];
export type AdherenceRead = Schemas['AdherenceRead'];
export type AdherenceSummary = Schemas['AdherenceSummary'];

export type SymptomEntryInput = Schemas['SymptomEntryInput'];
export type SymptomEntryRead = Schemas['SymptomEntryRead'];
export type SymptomEntryList = Schemas['SymptomEntryList'];
export type SymptomBurdenRead = Schemas['SymptomBurdenRead'];
export type SymptomBurdenTrend = Schemas['SymptomBurdenTrend'];
export type DysphagiaRelief = Schemas['DysphagiaRelief'];
export type EntryMethod = Schemas['EntryMethod'];

export type AllergenGroup = Schemas['AllergenGroup'];
export type Meal = Schemas['Meal'];
export type CatalogIngredientRead = Schemas['CatalogIngredientRead'];
export type CustomIngredientRead = Schemas['CustomIngredientRead'];
export type CustomIngredientUpdate = Schemas['CustomIngredientUpdate'];
export type IngredientRef = Schemas['IngredientRef'];
export type IngredientRead = Schemas['IngredientRead'];
export type FoodItemInput = Schemas['FoodItemInput'];
export type FoodItemRead = Schemas['FoodItemRead'];
export type FoodItemList = Schemas['FoodItemList'];
export type RecentFood = Schemas['RecentFood'];
export type FoodDataSource = Schemas['FoodDataSource'];
export type IngredientProvenance = Schemas['IngredientProvenance'];
export type ProductRef = Schemas['ProductRef'];
export type ProductSummaryRead = Schemas['ProductSummaryRead'];
export type ProductRead = Schemas['ProductRead'];
export type ProductIngredientRead = Schemas['ProductIngredientRead'];
export type ProductSnapshotRead = Schemas['ProductSnapshotRead'];

export type FoodPatternReport = Schemas['FoodPatternReport'];
export type FoodPatternRead = Schemas['FoodPatternRead'];
export type PatternStatus = Schemas['PatternStatus'];

export type LegalDocumentSummary = Schemas['LegalDocumentSummary'];
export type LegalDocumentRead = Schemas['LegalDocumentRead'];
export type LegalBlock = LegalDocumentRead['blocks'][number];
export type LegalSpan = Schemas['LegalSpan'];
export type LegalHeading = Schemas['LegalHeading'];
export type ReviewStatus = Schemas['ReviewStatus'];
