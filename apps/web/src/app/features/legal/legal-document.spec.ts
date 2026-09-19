import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';

import { LegalDocumentRead } from '../../core/api/api-types';
import { LegalDocument } from './legal-document';
import { LegalService } from './legal.service';

function document(overrides: Partial<LegalDocumentRead> = {}): LegalDocumentRead {
  return {
    id: 'tos-2026-09',
    consent_type: 'terms_of_service',
    slug: 'terms',
    title: 'Terms of service',
    effective_on: '2026-09-19',
    review_status: 'draft',
    content_sha256: 'a'.repeat(64),
    superseded_by: null,
    blocks: [
      { kind: 'heading', level: 2, text: '1. Who runs eoehelp', anchor: 'who' },
      { kind: 'heading', level: 2, text: '18. Resolving a dispute', anchor: 'dispute' },
      { kind: 'paragraph', spans: [{ text: 'Body text.', bold: false }] },
    ],
    ...overrides,
  };
}

class StubLegal {
  next: LegalDocumentRead | Error = document();
  async document(): Promise<LegalDocumentRead> {
    if (this.next instanceof Error) throw this.next;
    return this.next;
  }
}

describe('LegalDocument', () => {
  let legal: StubLegal;

  beforeEach(async () => {
    legal = new StubLegal();
    await TestBed.configureTestingModule({
      imports: [LegalDocument],
      providers: [
        provideRouter([]),
        { provide: LegalService, useValue: legal },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: new Map(), data: { documentId: 'terms' } } },
        },
      ],
    }).compileComponents();
  });

  async function render() {
    const fixture = TestBed.createComponent(LegalDocument);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('says plainly when a document is an unreviewed draft', async () => {
    const element = await render();
    expect(element.textContent).toContain('This is a draft.');
    expect(element.textContent).toContain('has not been reviewed by a lawyer');
  });

  it('says nothing of the sort once a lawyer has reviewed it', async () => {
    legal.next = document({ review_status: 'attorney_reviewed' });
    const element = await render();
    expect(element.textContent).not.toContain('This is a draft.');
  });

  it('warns when the version being read has been superseded', async () => {
    legal.next = document({ superseded_by: 'tos-2027-01' });
    const element = await render();
    expect(element.textContent).toContain('no longer current');
  });

  it('lists the numbered sections', async () => {
    const element = await render();
    const contents = Array.from(element.querySelectorAll('nav a')).map((a) =>
      a.textContent?.trim(),
    );
    expect(contents).toEqual(['1. Who runs eoehelp', '18. Resolving a dispute']);
  });

  it('offers a retry when it cannot be loaded', async () => {
    legal.next = new Error('offline');
    const element = await render();
    expect(element.querySelector('[role="alert"]')).not.toBeNull();
    expect(element.textContent).toContain('Try again');
  });
});
