import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API_BASE_URL } from '../../core/api/api';
import { LegalDocumentRead, LegalDocumentSummary } from '../../core/api/api-types';

/**
 * The legal documents. Public: no account is needed to read them.
 *
 * Documents are immutable — a change is a new version with a new id — so once
 * one has been fetched it is kept for the session.
 */
@Injectable({ providedIn: 'root' })
export class LegalService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);
  private readonly cache = signal(new Map<string, LegalDocumentRead>());

  async list(): Promise<LegalDocumentSummary[]> {
    return firstValueFrom(this.http.get<LegalDocumentSummary[]>(`${this.baseUrl}/legal/documents`));
  }

  async document(documentId: string): Promise<LegalDocumentRead> {
    const held = this.cache().get(documentId);
    if (held) return held;
    const document = await firstValueFrom(
      this.http.get<LegalDocumentRead>(`${this.baseUrl}/legal/documents/${documentId}`),
    );
    this.cache.update((map) => new Map(map).set(documentId, document));
    return document;
  }
}
