import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL, AccessTokenResponse, SessionUser } from '../api/api';

const REFRESH_RETRY_DELAY_MS = 500;

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

  private restoreInFlight: Promise<void> | null = null;
  private refreshInFlight: Promise<void> | null = null;
  private verifiedDuringRestore = false;

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

  /**
   * Replace the in-memory access token with one the API just issued.
   *
   * Onboarding needs this: it returns a token carrying the new patient id, and
   * without adopting it every /me route would keep rejecting the session until
   * the old token expired.
   */
  adoptAccessToken(token: string): void {
    this.accessToken.set(token);
  }

  /** Re-read /auth/session, e.g. after onboarding changes what it reports. */
  async reloadSession(): Promise<void> {
    await this.loadSession();
  }

  async requestMagicLink(email: string): Promise<void> {
    await firstValueFrom(this.http.post(`${this.baseUrl}/auth/magic-link`, { email }));
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
    if (this.restoreInFlight) this.verifiedDuringRestore = true;
    await this.loadSession();
  }

  /**
   * Recover a session on page load using the refresh cookie.
   *
   * Single-flight: the app shell and the route guard both ask for this on a full
   * page load, and two refreshes with the same cookie look to the server exactly
   * like a stolen token being replayed.
   */
  restore(): Promise<void> {
    this.restoreInFlight ??= this.doRestore().finally(() => {
      this.restoreInFlight = null;
    });
    return this.restoreInFlight;
  }

  private async doRestore(): Promise<void> {
    this.restoring.set(true);
    try {
      await this.refresh();
      await this.loadSession();
    } catch {
      // A sign-in that completed while this was pending owns the session now;
      // clearing here would throw its fresh token away.
      if (!this.verifiedDuringRestore) this.clear();
    } finally {
      this.verifiedDuringRestore = false;
      this.restoring.set(false);
    }
  }

  /**
   * Exchange the refresh cookie for a new access token.
   *
   * Single-flight for the same reason as `restore`: several requests failing
   * with 401 at once must share one refresh, not each start their own. One
   * delayed retry covers another tab having rotated the cookie a moment ago;
   * the browser will have stored that tab's new cookie by then.
   */
  refresh(): Promise<void> {
    this.refreshInFlight ??= this.doRefresh().finally(() => {
      this.refreshInFlight = null;
    });
    return this.refreshInFlight;
  }

  private async doRefresh(): Promise<void> {
    try {
      await this.exchangeRefreshCookie();
    } catch {
      await new Promise((resolve) => setTimeout(resolve, REFRESH_RETRY_DELAY_MS));
      await this.exchangeRefreshCookie();
    }
  }

  private async exchangeRefreshCookie(): Promise<void> {
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
    const user = await firstValueFrom(this.http.get<SessionUser>(`${this.baseUrl}/auth/session`));
    this.currentUser.set(user);
  }

  private clear(): void {
    this.accessToken.set(null);
    this.currentUser.set(null);
  }
}
