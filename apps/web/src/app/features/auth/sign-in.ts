import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { AuthService } from '../../core/auth.service';
import { Logo } from '../../shared/logo';

@Component({
  selector: 'app-sign-in',
  imports: [
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    Logo,
  ],
  template: `
    <section class="mx-auto flex max-w-md flex-col items-center px-6 py-16 sm:py-24">
      <app-logo [size]="40" class="mb-6 text-brand" />

      <mat-card appearance="outlined" class="w-full">
        <mat-card-content class="!p-7">
          @if (sent()) {
            <div class="flex flex-col items-center text-center">
              <span
                class="mb-4 flex size-12 items-center justify-center rounded-full
                       bg-brand-container text-on-brand-container"
              >
                <mat-icon>mark_email_read</mat-icon>
              </span>
              <h1 class="m-0 text-2xl font-semibold tracking-tight">Check your email</h1>
              <p class="mt-3 text-sm leading-relaxed text-on-surface-variant">
                If <strong class="text-on-surface">{{ submittedEmail() }}</strong> can
                receive mail, a sign-in link is on its way. It works once and expires
                in 15 minutes.
              </p>
              <button mat-stroked-button type="button" class="mt-6" (click)="reset()">
                Use a different address
              </button>
            </div>
          } @else {
            <h1 class="m-0 text-2xl font-semibold tracking-tight">Sign in</h1>
            <p class="mt-2 text-sm leading-relaxed text-on-surface-variant">
              We email you a link instead of using a password. There is no password to
              forget, and none to steal.
            </p>

            @if (error()) {
              <div
                role="alert"
                class="mt-5 flex items-start gap-2 rounded-lg border border-danger/40
                       bg-danger/10 px-4 py-3 text-sm text-danger"
              >
                <mat-icon class="!size-5 shrink-0 !text-xl">error</mat-icon>
                <span>{{ error() }}</span>
              </div>
            }

            <form class="mt-6 flex flex-col" (ngSubmit)="submit()" novalidate>
              <mat-form-field appearance="outline">
                <mat-label>Email address</mat-label>
                <input
                  matInput
                  name="email"
                  type="email"
                  autocomplete="email"
                  inputmode="email"
                  required
                  [(ngModel)]="email"
                  [attr.aria-invalid]="error() ? 'true' : null"
                />
                <mat-icon matSuffix>mail</mat-icon>
                <mat-hint>New here? This creates your account.</mat-hint>
              </mat-form-field>

              <button
                mat-flat-button
                type="submit"
                class="!mt-6 !min-h-tap"
                [disabled]="busy()"
              >
                @if (busy()) {
                  <mat-spinner diameter="20" />
                  Sending…
                } @else {
                  Email me a sign-in link
                }
              </button>
            </form>
          }
        </mat-card-content>
      </mat-card>

      <p class="mt-6 text-center text-xs leading-relaxed text-on-surface-variant">
        By continuing you agree to our terms and privacy policy. eoehelp is a personal
        health record, not a medical record system, and does not provide medical advice.
      </p>
    </section>
  `,
})
export class SignIn {
  private readonly auth = inject(AuthService);

  protected email = '';
  protected readonly busy = signal(false);
  protected readonly sent = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly submittedEmail = signal('');

  protected async submit(): Promise<void> {
    const address = this.email.trim();
    if (!address) {
      this.error.set('Enter your email address.');
      return;
    }

    this.busy.set(true);
    this.error.set(null);
    try {
      await this.auth.requestMagicLink(address);
      this.submittedEmail.set(address);
      // Confirmation is deliberately identical whether or not the address has an
      // account — on this product, revealing that would disclose a diagnosis.
      this.sent.set(true);
    } catch {
      this.error.set('We could not send that link. Please try again in a moment.');
    } finally {
      this.busy.set(false);
    }
  }

  protected reset(): void {
    this.sent.set(false);
    this.email = '';
  }
}
