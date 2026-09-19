import { Component, inject, signal } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { describeApiError } from '../../core/api/api-errors';
import { LegalDocumentRead } from '../../core/api/api-types';
import { LegalContent } from './legal-content';
import { LegalService } from './legal.service';

/**
 * A legal document in a dialog, for reading it from onboarding.
 *
 * A dialog rather than a navigation: the onboarding form holds what the patient
 * typed in signals, and leaving the page would discard it. MatDialog traps
 * focus, closes on Escape, and returns focus to the link that opened it.
 */
@Component({
  selector: 'app-legal-dialog',
  imports: [
    LegalContent,
    MatButtonModule,
    MatDialogModule,
    MatIconModule,
    MatProgressSpinnerModule,
  ],
  template: `
    <h2 mat-dialog-title class="!font-display">{{ document()?.title ?? 'Loading' }}</h2>
    <mat-dialog-content>
      @if (loading()) {
        <div class="flex justify-center py-10" aria-busy="true">
          <mat-spinner diameter="32" aria-label="Loading the document" />
        </div>
      } @else if (error()) {
        <p class="m-0 text-sm" role="alert">{{ error() }}</p>
      } @else if (document(); as doc) {
        @if (doc.review_status === 'draft') {
          <p
            class="m-0 mb-4 flex items-start gap-2 rounded-[16px] bg-subtle p-3 text-sm"
            role="note"
          >
            <mat-icon class="!size-5 shrink-0 !text-xl" aria-hidden="true">gavel</mat-icon>
            <span>
              <strong class="font-semibold">This is a draft</strong> and has not been reviewed by a
              lawyer.
            </span>
          </p>
        }
        <app-legal-content [blocks]="doc.blocks" />
      }
    </mat-dialog-content>
    <mat-dialog-actions class="!justify-between">
      @if (document(); as doc) {
        <a mat-button class="!min-h-tap" [href]="'/' + doc.slug" target="_blank" rel="noopener">
          Open in a new tab
        </a>
      }
      <button mat-flat-button type="button" class="!min-h-tap" mat-dialog-close>Close</button>
    </mat-dialog-actions>
  `,
})
export class LegalDialog {
  private readonly legal = inject(LegalService);
  private readonly slug = inject<string>(MAT_DIALOG_DATA);
  protected readonly reference = inject(MatDialogRef<LegalDialog>);

  protected readonly document = signal<LegalDocumentRead | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      this.document.set(await this.legal.document(this.slug));
    } catch (failure: unknown) {
      this.error.set(describeApiError(failure, 'This document could not be loaded.'));
    } finally {
      this.loading.set(false);
    }
  }
}
