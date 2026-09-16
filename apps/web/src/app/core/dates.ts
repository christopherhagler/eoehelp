/**
 * Local-calendar date helpers.
 *
 * `toIsoDate` deliberately avoids `Date.toISOString()`, which converts to UTC
 * first. For a patient in Los Angeles at 8pm, that returns tomorrow — so the
 * daily log would offer to write a day that has not happened, and the API would
 * reject it. The server independently computes "today" from the patient's stored
 * timezone; this keeps the browser's idea of the date in agreement with it.
 */
export function toIsoDate(date: Date): string {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function todayIso(): string {
  return toIsoDate(new Date());
}

export function addDays(iso: string, days: number): string {
  const [year, month, day] = iso.split('-').map(Number);
  // Constructed in local time from parts, so no timezone conversion happens.
  const date = new Date(year, month - 1, day + days);
  return toIsoDate(date);
}

export function formatDayLabel(iso: string, today = todayIso()): string {
  if (iso === today) return 'Today';
  if (iso === addDays(today, -1)) return 'Yesterday';
  const [year, month, day] = iso.split('-').map(Number);
  return new Intl.DateTimeFormat(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  }).format(new Date(year, month - 1, day));
}

/** The browser's timezone, used to prefill onboarding rather than ask. */
export function detectTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}
