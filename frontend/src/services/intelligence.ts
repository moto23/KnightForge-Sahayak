/**
 * Universal Document Intelligence service — 1:1 with the backend
 * /intelligence routes (Phase 11).
 *
 * POST /intelligence/process              classify + extract + merge one doc
 * GET  /intelligence/profile/{sessionId}  the unified canonical profile
 * POST /intelligence/resolve              resolve one field conflict
 */

import { api } from "@/services/api-client";
import type {
  IntelligenceProcessResponse,
  UnifiedProfileResponse,
} from "@/types/api";

export const intelligenceService = {
  /** Run the schema-driven pipeline for one uploaded document. */
  /**
   * `isPrimary` marks this upload as the form to be completed and returned —
   * the generated PDF is then that exact file, filled in.
   */
  process: (documentId: string, sessionId: string, isPrimary = false) =>
    api.post<IntelligenceProcessResponse>(
      "/intelligence/process",
      { document_id: documentId, session_id: sessionId, is_primary: isPrimary },
      { timeoutMs: 60_000 }, // first call may trigger OCR on scanned PDFs
    ),
  /** The session's unified profile (re-synced; deleted docs drop out). */
  profile: (sessionId: string, signal?: AbortSignal) =>
    api.get<UnifiedProfileResponse>(`/intelligence/profile/${sessionId}`, {
      signal,
    }),
  /** Resolve a conflict by choosing a source document's value. */
  resolve: (sessionId: string, canonicalId: string, documentId: string) =>
    api.post<UnifiedProfileResponse>("/intelligence/resolve", {
      session_id: sessionId,
      canonical_id: canonicalId,
      document_id: documentId,
    }),
  /** Select the ONE primary form this session generates as final output. */
  setPrimaryForm: (sessionId: string, formId: string) =>
    api.post<UnifiedProfileResponse>("/intelligence/primary-form", {
      session_id: sessionId,
      form_id: formId,
    }),
};
