import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL } from '../../core/api/api';
import {
  AdherenceSummary,
  DoseCreate,
  DoseRead,
  MedicationCatalogItem,
  MedicationCreate,
  MedicationRead,
  MedicationStop,
  MedicationToday,
} from '../../core/api/api-types';

@Injectable({ providedIn: 'root' })
export class MedicationService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);

  private get meds(): string {
    return `${this.baseUrl}/me/medications`;
  }

  /** Reference data, so it is not under /me and needs no patient record. */
  async catalog(): Promise<MedicationCatalogItem[]> {
    return firstValueFrom(
      this.http.get<MedicationCatalogItem[]>(`${this.baseUrl}/medications/catalog`),
    );
  }

  async list(includeEnded = true): Promise<MedicationRead[]> {
    return firstValueFrom(
      this.http.get<MedicationRead[]>(this.meds, {
        params: { include_ended: includeEnded },
      }),
    );
  }

  async add(medication: MedicationCreate): Promise<MedicationRead> {
    return firstValueFrom(this.http.post<MedicationRead>(this.meds, medication));
  }

  async stop(medicationId: string, stop: MedicationStop): Promise<MedicationRead> {
    return firstValueFrom(
      this.http.post<MedicationRead>(`${this.meds}/${medicationId}/stop`, stop),
    );
  }

  /** Only possible before any dose is logged; after that it is history. */
  async remove(medicationId: string): Promise<void> {
    await firstValueFrom(this.http.delete(`${this.meds}/${medicationId}`));
  }

  /** What is due today and what has been logged, in one call. */
  async today(onDate?: string): Promise<MedicationToday> {
    return firstValueFrom(
      this.http.get<MedicationToday>(`${this.meds}/today`, {
        params: onDate ? { on: onDate } : {},
      }),
    );
  }

  /**
   * The daily action, so it sends no body at all — the server timestamps the
   * dose, which is the only version worth trusting.
   */
  async logDose(medicationId: string, dose?: DoseCreate): Promise<DoseRead> {
    return firstValueFrom(
      this.http.post<DoseRead>(`${this.meds}/${medicationId}/doses`, dose ?? null),
    );
  }

  async undoDose(doseId: string): Promise<void> {
    await firstValueFrom(this.http.delete(`${this.meds}/doses/${doseId}`));
  }

  async adherence(from?: string, to?: string): Promise<AdherenceSummary> {
    const params: Record<string, string> = {};
    if (from) params['from'] = from;
    if (to) params['to'] = to;
    return firstValueFrom(this.http.get<AdherenceSummary>(`${this.meds}/adherence`, { params }));
  }
}
