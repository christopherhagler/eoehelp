import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL } from './api/api';

@Injectable({ providedIn: 'root' })
export class ReferenceService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);

  /**
   * The timezones the API will accept.
   *
   * Taken from the server rather than `Intl.supportedValuesOf('timeZone')`,
   * because the browser's ICU data and the server's tz database move
   * independently: a browser offering a zone the API has never heard of would
   * leave the patient stuck on the form with no valid choice.
   */
  async timezones(): Promise<string[]> {
    return firstValueFrom(this.http.get<string[]>(`${this.baseUrl}/reference/timezones`));
  }
}
