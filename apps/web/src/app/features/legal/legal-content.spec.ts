import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { LegalBlock } from '../../core/api/api-types';
import { LegalContent } from './legal-content';

function render(blocks: LegalBlock[]): HTMLElement {
  const fixture = TestBed.createComponent(LegalContent);
  fixture.componentRef.setInput('blocks', blocks);
  fixture.detectChanges();
  return fixture.nativeElement as HTMLElement;
}

describe('LegalContent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LegalContent],
      providers: [provideRouter([])],
    }).compileComponents();
  });

  it('renders headings with the anchors the contents list links to', () => {
    const element = render([
      { kind: 'heading', level: 2, text: '1. Who runs eoehelp', anchor: 'who-runs' },
      { kind: 'heading', level: 3, text: '18.7 Opting out', anchor: 'opting-out' },
    ]);
    expect(element.querySelector('h2')?.id).toBe('who-runs');
    expect(element.querySelector('h3')?.textContent?.trim()).toBe('18.7 Opting out');
  });

  it('marks bold spans and leaves the rest as text', () => {
    const element = render([
      {
        kind: 'paragraph',
        spans: [
          { text: 'You may ', bold: false },
          { text: 'opt out', bold: true },
        ],
      },
    ]);
    expect(element.querySelector('strong')?.textContent).toBe('opt out');
    expect(element.textContent).toContain('You may');
  });

  it('opens an external link safely and keeps an internal one in the app', () => {
    const element = render([
      {
        kind: 'paragraph',
        spans: [
          { text: 'AAA', bold: false, href: 'https://www.adr.org' },
          { text: 'privacy', bold: false, href: '/privacy' },
        ],
      },
    ]);
    const [external, internal] = Array.from(element.querySelectorAll('a'));
    expect(external.getAttribute('rel')).toBe('noopener noreferrer');
    expect(external.getAttribute('target')).toBe('_blank');
    expect(internal.getAttribute('href')).toBe('/privacy');
    expect(internal.getAttribute('target')).toBeNull();
  });

  it('renders a table with its caption and column scopes', () => {
    const element = render([
      {
        kind: 'table',
        caption: 'What eoehelp stores',
        header: ['Category', 'Why'],
        rows: [[[{ text: 'Account', bold: false }], [{ text: 'To let you in', bold: false }]]],
      },
    ]);
    expect(element.querySelector('caption')?.textContent?.trim()).toBe('What eoehelp stores');
    expect(
      Array.from(element.querySelectorAll('th')).map((th) => th.getAttribute('scope')),
    ).toEqual(['col', 'col']);
    expect(element.querySelector('td')?.textContent?.trim()).toBe('Account');
  });

  it('never writes raw markup into the page', () => {
    const element = render([
      { kind: 'paragraph', spans: [{ text: '<script>alert(1)</script>', bold: false }] },
    ]);
    expect(element.querySelector('script')).toBeNull();
    expect(element.textContent).toContain('<script>alert(1)</script>');
  });

  it('does not treat a protocol-relative target as an internal link', () => {
    // "//evil.test" and "/\\evil.test" leave the site while looking internal to a
    // bare startsWith('/'). Binding one to routerLink would make a legal
    // document an open redirect. The server refuses these too; this is the
    // second, independent layer.
    for (const href of ['//evil.test', '/\\evil.test', '/%2fevil.test']) {
      const element = render([
        { kind: 'paragraph', spans: [{ text: 'click', bold: false, href }] },
      ]);
      const anchor = element.querySelector('a');
      expect(anchor?.getAttribute('rel')).toBe('noopener noreferrer');
      expect(anchor?.getAttribute('target')).toBe('_blank');
    }
  });
});
