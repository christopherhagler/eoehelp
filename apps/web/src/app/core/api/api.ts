import { InjectionToken } from '@angular/core';

/**
 * Injected rather than imported from a constant so tests and the container build
 * can point at a different origin without a rebuild.
 */
export const API_BASE_URL = new InjectionToken<string>('API_BASE_URL', {
  providedIn: 'root',
  factory: () => {
    const { hostname, origin } = window.location;
    const isLocal = hostname === 'localhost' || hostname === '127.0.0.1';
    return isLocal ? 'http://localhost:8000/api/v1' : `${origin}/api/v1`;
  },
});

export interface AccessTokenResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
}

export interface SessionUser {
  id: string;
  email: string;
  role: 'patient' | 'doctor' | 'researcher' | 'admin';
  email_verified: boolean;
  patient_id: string | null;
  onboarding_complete: boolean;
}
