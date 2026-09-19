import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { AuthService } from '../../core/auth/auth.service';

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
  ],
  template: `
    <section class="page-hero">
      <div class="mx-auto max-w-md px-5 pb-20 pt-6">
        <h1 class="m-0 text-3xl font-semibold">{{ sent() ? 'Check your email' : 'Sign in' }}</h1>
        <p class="hero-muted m-0 mt-2 text-sm leading-relaxed">
          @if (sent()) {
            It works once and expires in 15 minutes.
          } @else {
            We email you a link instead of using a password. There is no password to forget, and
            none to steal.
          }
        </p>
      </div>
    </section>

    <section class="mx-auto -mt-14 flex max-w-md flex-col items-center px-4">
      <mat-card appearance="outlined" class="w-full shadow-lift">
        <mat-card-content class="!p-7">
          @if (sent()) {
            <div class="flex flex-col items-center text-center">
              <span
                class="mb-4 flex size-12 items-center justify-center rounded-full
                       bg-brand-container text-on-brand-container"
              >
                <mat-icon>mark_email_read</mat-icon>
              </span>
              <p class="m-0 text-sm leading-relaxed text-muted">
                If <strong class="text-on-surface">{{ submittedEmail() }}</strong> can receive mail,
                a sign-in link is on its way.
              </p>
              <button mat-stroked-button type="button" class="mt-6" (click)="reset()">
                Use a different address
              </button>
            </div>
          } @else {
            @if (error()) {
              <div
                role="alert"
                class="mb-5 flex items-start gap-2 rounded-2xl bg-danger/10 px-4 py-3
                       text-sm text-danger"
              >
                <mat-icon class="!size-5 shrink-0 !text-xl">error</mat-icon>
                <span>{{ error() }}</span>
              </div>
            }

            <form class="flex flex-col" (ngSubmit)="submit()" novalidate>
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

              <button mat-flat-button type="submit" class="!mt-6 !min-h-tap" [disabled]="busy()">
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
        By continuing you agree to our terms and privacy policy. eoehelp is a personal health
        record, not a medical record system, and does not provide medical advice.
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
