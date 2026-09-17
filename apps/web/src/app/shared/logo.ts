import { Component, input } from '@angular/core';

/**
 * The eoehelp mark: two mirrored curves forming a channel that narrows at the
 * midpoint and opens below it — the esophagus in profile, and the stricture
 * relieved. See docs/design/logo-study.html for the directions considered.
 *
 * Two variants, because the outline does not survive being shrunk. At 16px its
 * two thin strokes read as a bracket, so the small size is a separately drawn
 * solid silhouette rather than a scaled copy.
 */
@Component({
  selector: 'app-logo',
  template: `
    @if (variant() === 'outline') {
      <svg
        [attr.width]="size()"
        [attr.height]="size()"
        viewBox="0 0 48 48"
        fill="none"
        stroke="currentColor"
        [attr.stroke-width]="weight()"
        stroke-linecap="round"
        aria-hidden="true"
      >
        <path d="M 15 5 C 15 17, 20.5 21, 20.5 24 C 20.5 27, 14 32, 14 43" />
        <path d="M 33 5 C 33 17, 27.5 21, 27.5 24 C 27.5 27, 34 32, 34 43" />
      </svg>
    } @else {
      <!-- Solid silhouette: the channel is knocked out of a filled square, which
           holds its shape as a favicon where two hairlines would disappear. -->
      <svg [attr.width]="size()" [attr.height]="size()" viewBox="0 0 48 48" aria-hidden="true">
        <path
          fill="currentColor"
          fill-rule="evenodd"
          d="M6 0h36a6 6 0 0 1 6 6v36a6 6 0 0 1-6 6H6a6 6 0 0 1-6-6V6a6 6 0 0 1 6-6Z
             M18 6 C18 17, 22 21, 22 24 C22 27, 16 33, 16 42 L11 42 C11 32, 17 27, 17 24
             C17 21, 13 17, 13 6 Z
             M30 6 C30 17, 26 21, 26 24 C26 27, 32 33, 32 42 L37 42 C37 32, 31 27, 31 24
             C31 21, 35 17, 35 6 Z"
        />
      </svg>
    }
  `,
  host: { class: 'inline-flex items-center' },
})
export class Logo {
  readonly variant = input<'outline' | 'solid'>('outline');
  readonly size = input<number>(28);
  readonly weight = input<number>(3.4);
}
