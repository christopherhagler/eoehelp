/**
 * The contract with the API, re-exported from the generated OpenAPI types.
 *
 * `api-client/schema.d.ts` is generated from `packages/openapi/schema.json`,
 * which FastAPI emits and CI diffs. A backend response-shape change therefore
 * becomes a TypeScript error here rather than a runtime surprise in a clinical
 * screen — which matters more than usual on this product, because fields like
 * eos/hpf and EREFS sub-scores transpose silently and dangerously.
 *
 * Regenerate with `make api-types`. Never hand-edit the generated file.
 */
import type { components } from '../api-client/schema';

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

export type SymptomEntryInput = Schemas['SymptomEntryInput'];
export type SymptomEntryRead = Schemas['SymptomEntryRead'];
export type SymptomEntryList = Schemas['SymptomEntryList'];
export type SymptomBurdenRead = Schemas['SymptomBurdenRead'];
export type SymptomBurdenTrend = Schemas['SymptomBurdenTrend'];
export type DysphagiaSeverity = Schemas['DysphagiaSeverity'];
export type CopingAction = Schemas['CopingAction'];
export type EntryMethod = Schemas['EntryMethod'];
