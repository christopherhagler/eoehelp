import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL, AccessTokenResponse, SessionUser } from './api';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);

  /**
   * Access token is held in memory only — never localStorage or sessionStorage.
   * For a health record, a persisted token turns any injected script into full
   * account takeover. The refresh token lives in an httpOnly cookie the
   * JavaScript here cannot read, so a page reload recovers the session via
   * `restore()` instead of by reading storage.
   */
  private readonly accessToken = signal<string | null>(null);
  private readonly currentUser = signal<SessionUser | null>(null);
  private readonly restoring = signal(true);

  readonly user = this.currentUser.asReadonly();
  readonly isRestoring = this.restoring.asReadonly();
  readonly isSignedIn = computed(() => this.currentUser() !== null);
  readonly needsOnboarding = computed(() => {
    const user = this.currentUser();
    return user !== null && !user.onboarding_complete;
  });

  token(): string | null {
    return this.accessToken();
  }

  async requestMagicLink(email: string): Promise<void> {
    await firstValueFrom(
      this.http.post(`${this.baseUrl}/auth/magic-link`, { email }),
    );
  }

  async verifyMagicLink(token: string): Promise<void> {
    const response = await firstValueFrom(
      this.http.post<AccessTokenResponse>(
        `${this.baseUrl}/auth/magic-link/verify`,
        { token },
        { withCredentials: true },
      ),
    );
    this.accessToken.set(response.access_token);
    await this.loadSession();
  }

  /** Recover a session on page load using the refresh cookie. */
  async restore(): Promise<void> {
    this.restoring.set(true);
    try {
      await this.refresh();
      await this.loadSession();
    } catch {
      this.clear();
    } finally {
      this.restoring.set(false);
    }
  }

  async refresh(): Promise<void> {
    const response = await firstValueFrom(
      this.http.post<AccessTokenResponse>(
        `${this.baseUrl}/auth/refresh`,
        {},
        { withCredentials: true },
      ),
    );
    this.accessToken.set(response.access_token);
  }

  async signOut(): Promise<void> {
    try {
      await firstValueFrom(
        this.http.post(`${this.baseUrl}/auth/sign-out`, {}, { withCredentials: true }),
      );
    } finally {
      this.clear();
    }
  }

  private async loadSession(): Promise<void> {
    const user = await firstValueFrom(
      this.http.get<SessionUser>(`${this.baseUrl}/auth/session`),
    );
    this.currentUser.set(user);
  }

  private clear(): void {
    this.accessToken.set(null);
    this.currentUser.set(null);
  }
}
