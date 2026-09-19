import { Component, computed, inject, OnInit } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';

import { Logo } from './shared/logo';
import { AuthService } from './core/auth/auth.service';

interface NavLink {
  readonly path: string;
  readonly label: string;
  readonly icon: string;
}

/** Screens with their own bottom action, where the navigation would cover it. */
const FULL_SCREEN_ROUTES = ['/log', '/welcome'];

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, MatButtonModule, MatIconModule, Logo],
  templateUrl: './app.html',
  styles: `
    .nav-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.375rem;
      min-width: 3rem;
      height: 3rem;
      padding: 0 0.875rem;
      border-radius: 999px;
      color: var(--eo-hero-muted);
      font-weight: 700;
      font-size: 0.875rem;
      text-decoration: none;
    }
    .nav-link:hover {
      color: #ffffff;
    }
    .nav-link.is-active {
      flex: 1;
      background: var(--eo-mint);
      color: var(--eo-on-mint);
    }
    .nav-link:focus-visible {
      outline-color: var(--eo-mint);
    }
    /* A phone shows the current screen's name; the others are icons with
       accessible names. Wider screens have room for every label. */
    .nav-label {
      display: none;
    }
    .nav-link.is-active .nav-label {
      display: inline;
    }
    @media (min-width: 640px) {
      .nav-link {
        flex: 1;
      }
      .nav-label {
        display: inline;
      }
    }
  `,
})
export class App implements OnInit {
  protected readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly links: readonly NavLink[] = [
    { path: '/today', label: 'Today', icon: 'home' },
    { path: '/log', label: 'Log', icon: 'edit_note' },
    { path: '/insights', label: 'Insights', icon: 'insights' },
    { path: '/medications', label: 'Medications', icon: 'medication' },
  ];

  private readonly url = toSignal(
    this.router.events.pipe(
      filter((event) => event instanceof NavigationEnd),
      map((event) => event.urlAfterRedirects),
    ),
    { initialValue: this.router.url },
  );

  protected readonly onSignIn = computed(() => this.url().startsWith('/sign-in'));

  protected readonly showNav = computed(
    () =>
      this.auth.isSignedIn() &&
      !FULL_SCREEN_ROUTES.some((route) => this.url().startsWith(route)) &&
      this.url() !== '/',
  );

  ngOnInit(): void {
    // Exchanges the httpOnly refresh cookie for a session on first paint, so a
    // reload does not look like a sign-out.
    void this.auth.restore();
  }

  protected async signOut(): Promise<void> {
    await this.auth.signOut();
    void this.router.navigate(['/']);
  }
}
