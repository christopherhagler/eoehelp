import { DoseFrequency, MedicationStopReason } from '../core/api-types';

/** Plain-English labels, kept in one place so the log, the list, and the eventual
 * report cannot describe the same schedule differently. */
export const FREQUENCY_LABELS: Record<DoseFrequency, string> = {
  once_daily: 'Once a day',
  twice_daily: 'Twice a day',
  three_times_daily: 'Three times a day',
  every_other_day: 'Every other day',
  weekly: 'Once a week',
  every_two_weeks: 'Every 2 weeks',
  every_four_weeks: 'Every 4 weeks',
  as_needed: 'As needed',
};

export const STOP_REASON_LABELS: Record<MedicationStopReason, string> = {
  remission: 'In remission',
  ineffective: 'It did not work',
  side_effects: 'Side effects',
  cost: 'Too expensive',
  insurance: 'Insurance would not cover it',
  provider_directed: 'My doctor stopped it',
  other: 'Another reason',
};

export function frequencyLabel(frequency: DoseFrequency | null): string {
  // Null means a schedule this version of the app did not generate — an honest
  // "we cannot name this" rather than guessing at one.
  return frequency ? FREQUENCY_LABELS[frequency] : 'Custom schedule';
}
