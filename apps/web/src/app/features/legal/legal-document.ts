import { Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { Title } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { describeApiError } from '../../core/api/api-errors';
import { LegalDocumentRead, LegalHeading } from '../../core/api/api-types';
import { LegalContent } from './legal-content';
import { LegalService } from './legal.service';

/** One legal document, by slug ("terms") or by version id ("tos-2026-09"). */
@Component({
  selector: 'app-legal-document',
  imports: [LegalContent, MatButtonModule, MatIconModule, MatProgressSpinnerModule, RouterLink],
  template: `
    <section class="page-hero">
      <div class="mx-auto max-w-3xl px-5 pb-10 pt-4">
        <h1 class="m-0 text-3xl font-semibold">{{ document()?.title ?? 'Legal' }}</h1>
        @if (document(); as doc) {
          <p class="hero-muted m-0 mt-2 text-sm">
            In force from {{ doc.effective_on }} · version {{ doc.id }}
          </p>
        }
      </div>
    </section>

    <section class="mx-auto max-w-3xl px-4 pb-4 pt-4">
      @if (loading()) {
        <div class="flex justify-center py-16" aria-busy="true">
          <mat-spinner diameter="36" aria-label="Loading the document" />
        </div>
      } @else if (error()) {
        <div class="rounded-[24px] bg-card p-5">
          <p class="m-0 text-sm" role="alert">{{ error() }}</p>
          <button mat-flat-button type="button" class="!mt-4 !min-h-tap" (click)="load()">
            Try again
          </button>
        </div>
      } @else if (document(); as doc) {
        @if (doc.review_status === 'draft') {
          <div class="mb-4 flex items-start gap-2 rounded-[20px] bg-subtle p-4 text-sm" role="note">
            <mat-icon class="!size-5 shrink-0 !text-xl" aria-hidden="true">gavel</mat-icon>
            <span>
              <strong class="font-semibold">This is a draft.</strong> It was written by the person
              who runs eoehelp and has not been reviewed by a lawyer. This build is for testing, not
              for real health information.
            </span>
          </div>
        }
        @if (doc.superseded_by; as newer) {
          <div class="mb-4 flex items-start gap-2 rounded-[20px] bg-subtle p-4 text-sm" role="note">
            <mat-icon class="!size-5 shrink-0 !text-xl" aria-hidden="true">history</mat-icon>
            <span>
              This version is no longer current. It is kept because people agreed to it.
              <a [routerLink]="['/legal', newer]">Read the current version</a>.
            </span>
          </div>
        }

        <div class="rounded-[26px] bg-card p-5 sm:p-7">
          @if (sections().length > 1) {
            <nav aria-labelledby="contents" class="mb-6 rounded-[20px] bg-subtle p-4">
              <p id="contents" class="m-0 text-sm font-semibold">On this page</p>
              <ul class="m-0 mt-2 flex list-none flex-col p-0 text-sm">
                @for (section of sections(); track section.anchor) {
                  <li>
                    <a class="flex min-h-tap items-center" [href]="'#' + section.anchor">
                      {{ section.text }}
                    </a>
                  </li>
                }
              </ul>
            </nav>
          }
          <app-legal-content [blocks]="doc.blocks" />
        </div>

        <p class="mt-4 text-sm text-muted">
          Also read:
          <a routerLink="/terms">terms of service</a>, <a routerLink="/privacy">privacy policy</a>,
          <a routerLink="/health-data">Consumer Health Data Privacy Policy</a>.
        </p>
      } @else {
        <div class="rounded-[24px] bg-card p-5">
          <p class="m-0 text-sm">
            There is no document at this address. Read the
            <a routerLink="/terms">terms of service</a>, the
            <a routerLink="/privacy">privacy policy</a>, or the
            <a routerLink="/health-data">Consumer Health Data Privacy Policy</a>.
          </p>
        </div>
      }
    </section>
  `,
})
export class LegalDocument {
  private readonly legal = inject(LegalService);
  private readonly route = inject(ActivatedRoute);
  private readonly title = inject(Title);

  protected readonly document = signal<LegalDocumentRead | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);

  /** Level-2 headings, which are the numbered sections. */
  protected readonly sections = computed(() =>
    (this.document()?.blocks ?? []).filter(
      (block): block is LegalHeading => block.kind === 'heading' && block.level === 2,
    ),
  );

  constructor() {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    const id =
      this.route.snapshot.paramMap.get('documentId') ?? this.route.snapshot.data['documentId'];
    try {
      const document = await this.legal.document(id);
      this.document.set(document);
      this.title.setTitle(`${document.title} — eoehelp`);
    } catch (failure: unknown) {
      if (failure instanceof Object && 'status' in failure && failure.status === 404) {
        this.document.set(null);
        this.title.setTitle('Not found — eoehelp');
      } else {
        this.error.set(describeApiError(failure, 'This document could not be loaded.'));
      }
    } finally {
      this.loading.set(false);
    }
  }
}
