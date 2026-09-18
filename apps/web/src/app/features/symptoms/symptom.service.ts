import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL } from '../../core/api/api';
import {
  SymptomBurdenRead,
  SymptomBurdenTrend,
  SymptomEntryInput,
  SymptomEntryList,
  SymptomEntryRead,
} from '../../core/api/api-types';

@Injectable({ providedIn: 'root' })
export class SymptomService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);

  private get symptoms(): string {
    return `${this.baseUrl}/me/symptoms`;
  }

  /**
   * Entries are addressed by date, not id, because a patient has exactly one per
   * day. PUT makes the write idempotent, so a retry — or an offline submission
   * replayed on reconnect — cannot produce a second entry for the same day.
   */
  async save(entryDate: string, entry: SymptomEntryInput): Promise<SymptomEntryRead> {
    return firstValueFrom(this.http.put<SymptomEntryRead>(`${this.symptoms}/${entryDate}`, entry));
  }

  /** Resolves to null when the day has not been logged, which is not an error. */
  async get(entryDate: string): Promise<SymptomEntryRead | null> {
    try {
      return await firstValueFrom(this.http.get<SymptomEntryRead>(`${this.symptoms}/${entryDate}`));
    } catch {
      return null;
    }
  }

  async list(from: string, to: string): Promise<SymptomEntryList> {
    return firstValueFrom(this.http.get<SymptomEntryList>(this.symptoms, { params: { from, to } }));
  }

  async remove(entryDate: string): Promise<void> {
    await firstValueFrom(this.http.delete(`${this.symptoms}/${entryDate}`));
  }

  /** The 14-day DSQ score, computed server-side so the screen and the eventual
   * PDF cannot disagree about the same patient. */
  async burden(asOf?: string): Promise<SymptomBurdenRead> {
    return firstValueFrom(
      this.http.get<SymptomBurdenRead>(`${this.symptoms}/burden`, {
        params: asOf ? { as_of: asOf } : {},
      }),
    );
  }

  async burdenTrend(points = 30): Promise<SymptomBurdenTrend> {
    return firstValueFrom(
      this.http.get<SymptomBurdenTrend>(`${this.symptoms}/burden/trend`, {
        params: { points },
      }),
    );
  }
}
