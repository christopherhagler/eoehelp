import { Component, OnInit, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-verify',
  imports: [
    RouterLink,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatProgressSpinnerModule,
  ],
  template: `
    <section class="mx-auto flex max-w-md px-6 py-16 sm:py-24">
      <mat-card appearance="outlined" class="w-full">
        <mat-card-content class="!p-7" aria-live="polite">
          @if (failed()) {
            <div class="flex flex-col items-center text-center">
              <span
                class="mb-4 flex size-12 items-center justify-center rounded-full
                       bg-danger/10 text-danger"
              >
                <mat-icon>link_off</mat-icon>
              </span>
              <h1 class="m-0 text-2xl font-semibold tracking-tight">
                That link didn't work
              </h1>
              <p class="mt-3 text-sm leading-relaxed text-on-surface-variant">
                Sign-in links expire after 15 minutes and can only be used once. If you
                opened this one already, or asked for a newer one, request a fresh link.
              </p>
              <a mat-flat-button routerLink="/sign-in" class="!mt-6 !min-h-tap">
                Get a new link
              </a>
            </div>
          } @else {
            <div class="flex flex-col items-center py-4 text-center">
              <mat-spinner diameter="40" />
              <h1 class="m-0 mt-6 text-xl font-semibold tracking-tight">
                Signing you in…
              </h1>
              <p class="mt-2 text-sm text-on-surface-variant">One moment.</p>
            </div>
          }
        </mat-card-content>
      </mat-card>
    </section>
  `,
})
export class Verify implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly failed = signal(false);

  async ngOnInit(): Promise<void> {
    const token = this.route.snapshot.queryParamMap.get('token');
    if (!token) {
      this.failed.set(true);
      return;
    }

    try {
      await this.auth.verifyMagicLink(token);
      // replaceUrl so the back button cannot return to a consumed token, and so
      // the token stops sitting in history.
      void this.router.navigate(['/today'], { replaceUrl: true });
    } catch {
      this.failed.set(true);
    }
  }
}
