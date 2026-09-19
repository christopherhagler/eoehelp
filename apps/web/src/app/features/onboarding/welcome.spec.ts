import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { provideRouter } from '@angular/router';

import { LegalDocumentSummary } from '../../core/api/api-types';
import { LegalService } from '../legal/legal.service';
import { Welcome } from './welcome';

function summary(id: string, slug: string): LegalDocumentSummary {
  return {
    id,
    consent_type: 'terms_of_service',
    slug,
    title: slug,
    effective_on: '2026-09-19',
    review_status: 'draft',
    content_sha256: 'a'.repeat(64),
    superseded_by: null,
  };
}

class StubLegal {
  documents = [summary('tos-2026-09', 'terms'), summary('privacy-2026-09', 'privacy')];
  async list(): Promise<LegalDocumentSummary[]> {
    return this.documents;
  }
}

describe('Welcome', () => {
  let opened: unknown[];

  beforeEach(async () => {
    opened = [];
    await TestBed.configureTestingModule({
      imports: [Welcome],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: LegalService, useValue: new StubLegal() },
        { provide: MatDialog, useValue: { open: (...args: unknown[]) => opened.push(args) } },
      ],
    }).compileComponents();
  });

  async function render() {
    const fixture = TestBed.createComponent(Welcome);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    return { fixture, element: fixture.nativeElement as HTMLElement };
  }

  it('opens the document without ticking the consent box', async () => {
    // The regression this test exists for: a link inside a checkbox label
    // toggles the checkbox as well as following the link, which would record
    // agreement because someone clicked to read.
    const { fixture, element } = await render();
    const link = element.querySelector<HTMLAnchorElement>('a[href="/terms"]');
    expect(link).not.toBeNull();

    link?.click();
    fixture.detectChanges();

    const checked = Array.from(element.querySelectorAll('input[type="checkbox"]')).filter(
      (input) => (input as HTMLInputElement).checked,
    );
    expect(checked).toEqual([]);
    expect(opened.length).toBe(1);
  });

  it('names the versions being agreed to, and says they are drafts', async () => {
    const { element } = await render();
    expect(element.textContent).toContain('tos-2026-09, privacy-2026-09');
    expect(element.textContent).toContain('drafts and have not yet been reviewed by a lawyer');
  });

  it('gives notice of the arbitration clause where the agreement happens', async () => {
    const { element } = await render();
    expect(element.textContent).toContain('individual arbitration');
    expect(element.textContent).toContain('opt out of that within 30 days');
  });
});
