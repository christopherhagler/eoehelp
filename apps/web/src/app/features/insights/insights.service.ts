import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL } from '../../core/api/api';
import { FoodPatternReport } from '../../core/api/api-types';

/** Lag windows the API accepts: how many days before a symptom day food still counts. */
export const LAG_OPTIONS = [0, 1, 2, 3] as const;
export const DEFAULT_LAG = 2;

@Injectable({ providedIn: 'root' })
export class InsightsService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);

  async foodPatterns(lagDays: number = DEFAULT_LAG): Promise<FoodPatternReport> {
    return firstValueFrom(
      this.http.get<FoodPatternReport>(`${this.baseUrl}/me/insights/food-patterns`, {
        params: { lag_days: lagDays },
      }),
    );
  }
}
