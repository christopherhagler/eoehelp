import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL } from './api';
import {
  ConsentRecord,
  OnboardingRequest,
  OnboardingResponse,
  PatientProfile,
  PatientProfileUpdate,
} from './api-types';
import { AuthService } from './auth.service';

@Injectable({ providedIn: 'root' })
export class PatientService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);
  private readonly auth = inject(AuthService);

  private readonly currentProfile = signal<PatientProfile | null>(null);
  readonly profile = this.currentProfile.asReadonly();

  /**
   * Completing onboarding changes what the session can do, so the access token
   * the API returns here replaces the one in memory: the previous token predates
   * the patient record and carries no patient id, which every /me route requires.
   */
  async completeOnboarding(request: OnboardingRequest): Promise<PatientProfile> {
    const response = await firstValueFrom(
      this.http.post<OnboardingResponse>(`${this.baseUrl}/me/onboarding`, request),
    );
    this.auth.adoptAccessToken(response.access_token);
    await this.auth.reloadSession();
    this.currentProfile.set(response.patient);
    return response.patient;
  }

  async loadProfile(): Promise<PatientProfile> {
    const profile = await firstValueFrom(
      this.http.get<PatientProfile>(`${this.baseUrl}/me/profile`),
    );
    this.currentProfile.set(profile);
    return profile;
  }

  async updateProfile(changes: PatientProfileUpdate): Promise<PatientProfile> {
    const profile = await firstValueFrom(
      this.http.patch<PatientProfile>(`${this.baseUrl}/me/profile`, changes),
    );
    this.currentProfile.set(profile);
    return profile;
  }

  async consents(): Promise<ConsentRecord[]> {
    return firstValueFrom(this.http.get<ConsentRecord[]>(`${this.baseUrl}/me/consents`));
  }

  async deleteAccount(): Promise<void> {
    await firstValueFrom(this.http.delete(`${this.baseUrl}/me`, { withCredentials: true }));
  }
}
