import { NgTemplateOutlet } from '@angular/common';
import { Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';

import { LegalBlock, LegalSpan } from '../../core/api/api-types';

/**
 * A legal document's body, from the typed blocks the API returns.
 *
 * The API parses the source and sends structure, so nothing here needs
 * `innerHTML` or a sanitiser: a document cannot introduce markup or a script,
 * and link targets were restricted when it was parsed.
 */
@Component({
  selector: 'app-legal-content',
  imports: [NgTemplateOutlet, RouterLink],
  template: `
    @for (block of blocks(); track $index) {
      @switch (block.kind) {
        @case ('heading') {
          @if (block.level === 2) {
            <h2 [id]="block.anchor" class="mt-8 text-xl font-semibold first:mt-0">
              {{ block.text }}
            </h2>
          } @else {
            <h3 [id]="block.anchor" class="mt-6 text-lg font-semibold">{{ block.text }}</h3>
          }
        }
        @case ('paragraph') {
          <p class="mt-3 leading-relaxed">
            @for (span of block.spans; track $index) {
              <ng-container
                [ngTemplateOutlet]="piece"
                [ngTemplateOutletContext]="{ $implicit: span }"
              />
            }
          </p>
        }
        @case ('bullets') {
          <ul class="mt-3 flex list-disc flex-col gap-2 pl-5 leading-relaxed">
            @for (item of block.items; track $index) {
              <li>
                @for (span of item; track $index) {
                  <ng-container
                    [ngTemplateOutlet]="piece"
                    [ngTemplateOutletContext]="{ $implicit: span }"
                  />
                }
              </li>
            }
          </ul>
        }
        @case ('table') {
          <div class="mt-4 overflow-x-auto">
            <table class="w-full border-collapse text-left text-sm">
              @if (block.caption) {
                <caption class="pb-2 text-left text-sm text-muted">
                  {{
                    block.caption
                  }}
                </caption>
              }
              <thead>
                <tr>
                  @for (heading of block.header; track $index) {
                    <th scope="col" class="border-b border-outline-variant py-2 pr-3 font-semibold">
                      {{ heading }}
                    </th>
                  }
                </tr>
              </thead>
              <tbody>
                @for (row of block.rows; track $index) {
                  <tr>
                    @for (cell of row; track $index) {
                      <td class="border-b border-outline-variant py-2 pr-3 align-top">
                        @for (span of cell; track $index) {
                          <ng-container
                            [ngTemplateOutlet]="piece"
                            [ngTemplateOutletContext]="{ $implicit: span }"
                          />
                        }
                      </td>
                    }
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      }
    }

    <ng-template #piece let-span>
      @if (span.href) {
        @if (isInternal(span)) {
          <a [routerLink]="span.href">{{ span.text }}</a>
        } @else {
          <a [href]="span.href" target="_blank" rel="noopener noreferrer">{{ span.text }}</a>
        }
      } @else if (span.bold) {
        <strong class="font-semibold">{{ span.text }}</strong>
      } @else {
        {{ span.text }}
      }
    </ng-template>
  `,
})
export class LegalContent {
  readonly blocks = input.required<readonly LegalBlock[]>();

  protected isInternal(span: LegalSpan): boolean {
    return (span.href ?? '').startsWith('/');
  }
}
