/**
 * OCR / document-understanding service — 1:1 with the backend /ocr routes.
 * POST /ocr/extract · GET /ocr/{document_id} (cached) · POST /ocr/prefill
 */

import { api } from "@/services/api-client";
import type { OCRExtractResponse, PrefillResponse } from "@/types/api";

export const ocrService = {
  /** Run (or re-run with force) the full OCR → extraction pipeline. */
  extract: (documentId: string, force = false) =>
    api.post<OCRExtractResponse>(
      "/ocr/extract",
      { document_id: documentId, force },
      { timeoutMs: 60_000 }, // OCR on scanned PDFs can be slow
    ),
  /** Cached pipeline result — 404 if the document was never processed. */
  getUnderstanding: (documentId: string) =>
    api.get<OCRExtractResponse>(`/ocr/${documentId}`),
  /** Write accepted extracted values into a session. */
  prefill: (documentId: string, sessionId: string, overwrite = false) =>
    api.post<PrefillResponse>("/ocr/prefill", {
      document_id: documentId,
      session_id: sessionId,
      overwrite,
    }),
};
