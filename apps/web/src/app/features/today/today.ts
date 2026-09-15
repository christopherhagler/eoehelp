import { Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-today',
  imports: [MatButtonModule, MatCardModule, MatIconModule, MatProgressBarModule],
  template: `
    <section class="mx-auto max-w-4xl px-6 py-10 sm:py-14">
      <header class="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p class="m-0 text-sm font-semibold uppercase tracking-[0.12em] text-brand">
            {{ today }}
          </p>
          <h1 class="m-0 mt-1 text-3xl font-semibold tracking-tight">Today</h1>
        </div>
        <p class="m-0 text-sm text-on-surface-variant">
          Signed in as {{ auth.user()?.email }}
        </p>
      </header>

      <mat-card appearance="outlined" class="mt-8">
        <mat-card-content class="!p-7">
          <div class="flex items-start gap-4">
            <span
              class="flex size-11 shrink-0 items-center justify-center rounded-xl
                     bg-brand-container text-on-brand-container"
            >
              <mat-icon>edit_note</mat-icon>
            </span>
            <div>
              <h2 class="m-0 text-lg font-semibold tracking-tight">
                Your daily log lands here next
              </h2>
              <p class="mt-2 text-sm leading-relaxed text-on-surface-variant">
                The symptom entry flow — did you eat solid food, did anything get
                stuck, and what you did about it — is the next thing being built. It
                follows the Dysphagia Symptom Questionnaire and is designed to take
                under a minute on an ordinary day.
              </p>
            </div>
          </div>
        </mat-card-content>
      </mat-card>

      <div class="mt-5 grid gap-5 sm:grid-cols-2">
        <mat-card appearance="outlined">
          <mat-card-content class="!p-6">
            <h3
              class="m-0 text-xs font-semibold uppercase tracking-[0.1em]
                     text-on-surface-variant"
            >
              Account
            </h3>
            <p class="mt-3 flex items-center gap-2 text-sm">
              <mat-icon class="!size-5 !text-xl text-brand">verified_user</mat-icon>
              Created and secured
            </p>
            <p class="mt-2 flex items-center gap-2 text-sm">
              <mat-icon class="!size-5 !text-xl text-brand">lock</mat-icon>
              Nothing shared with anyone
            </p>
          </mat-card-content>
        </mat-card>

        <mat-card appearance="outlined">
          <mat-card-content class="!p-6">
            <h3
              class="m-0 text-xs font-semibold uppercase tracking-[0.1em]
                     text-on-surface-variant"
            >
              Next milestone
            </h3>
            <p class="mt-3 text-sm text-on-surface-variant">
              Daily symptom logging, diet phases, and the clinical report.
            </p>
            <mat-progress-bar
              class="mt-4 !rounded-full"
              mode="determinate"
              [value]="25"
              aria-label="Build progress through the first release"
            />
            <p class="mt-2 text-xs tabular-nums text-on-surface-variant">
              Foundations complete
            </p>
          </mat-card-content>
        </mat-card>
      </div>
    </section>
  `,
})
export class Today {
  protected readonly auth = inject(AuthService);

  protected readonly today = new Intl.DateTimeFormat(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  }).format(new Date());
}
