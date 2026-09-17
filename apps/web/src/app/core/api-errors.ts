import { HttpErrorResponse } from '@angular/common/http';

interface ValidationDetail {
  readonly loc?: readonly (string | number)[];
  readonly msg?: string;
}

/** Field names as the patient would recognise them, not as the API spells them. */
const FIELD_LABELS: Record<string, string> = {
  birth_year: 'Year you were born',
  diagnosis_month: 'When you were diagnosed',
  display_name: 'What we should call you',
  timezone: 'Timezone',
  sex_at_birth: 'Sex at birth',
  consents: 'The agreements',
  medication_code: 'Medication',
  dose_amount: 'Dose',
  frequency: 'How often',
  started_on: 'Start date',
  ended_on: 'End date',
  stop_reason: 'Reason for stopping',
  odynophagia_severity: 'How much it hurt',
  dysphagia_severity: 'What happened',
  notes: 'Note',
  eaten_on: 'Day',
  meal: 'Meal',
  name: 'Name',
  ingredients: 'Ingredients',
  allergen_groups: 'Contains',
};

/**
 * Turn an API error into something worth showing a patient.
 *
 * Written because the first version of these screens swallowed the response and
 * showed "we could not create your record", which is true, useless, and leaves
 * someone stuck on a form with no idea which field is wrong. A 422 from this API
 * names the field; passing that through is the difference between a dead end and
 * a correction.
 *
 * Only the API's own `msg` and field locations are surfaced — never the submitted
 * value, which is the patient's own health data.
 */
export function describeApiError(error: unknown, fallback: string): string {
  if (!(error instanceof HttpErrorResponse)) {
    return fallback;
  }

  if (error.status === 0) {
    return 'We could not reach the server. Check your connection and try again.';
  }

  const detail: unknown = error.error?.detail;

  // FastAPI validation errors: a list of {loc, msg}.
  if (Array.isArray(detail)) {
    const described = (detail as ValidationDetail[])
      .map((item) => {
        // loc is ["body", "<field>", ...]; the field is what a patient can act on.
        const field = item.loc?.filter((part) => part !== 'body').at(0);
        const label = typeof field === 'string' ? (FIELD_LABELS[field] ?? field) : null;
        const message = item.msg ?? 'is not valid';
        return label ? `${label}: ${message}` : message;
      })
      .filter((line) => line.length > 0);

    if (described.length > 0) {
      return described.join('. ');
    }
  }

  // Everything this API raises deliberately carries a plain-string detail, and
  // those messages are already written for patients.
  if (typeof detail === 'string' && detail.length > 0) {
    return detail;
  }

  return fallback;
}
