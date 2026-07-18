/**
 * PDF service — 1:1 with the backend /pdf routes.
 * POST /pdf/generate · GET /pdf · GET /pdf/{id} · DELETE /pdf/{id}
 * (GET /pdf/{id}/download is a browser-native navigation — pages build the
 *  href with absoluteUrl(pdf.download_url) instead of fetching bytes.)
 */

import { api } from "@/services/api-client";
import type {
  DeletePdfResponse,
  GeneratedPdfResponse,
  GeneratePdfResponse,
} from "@/types/api";

export const pdfService = {
  /** 409 code="interview_incomplete" lists the missing fields. */
  generate: (sessionId: string) =>
    api.post<GeneratePdfResponse>(
      "/pdf/generate",
      { session_id: sessionId },
      { timeoutMs: 60_000 }, // template render + overlay can take a moment
    ),
  list: (signal?: AbortSignal) =>
    api.get<GeneratedPdfResponse[]>("/pdf", { signal }),
  get: (pdfId: string) => api.get<GeneratedPdfResponse>(`/pdf/${pdfId}`),
  remove: (pdfId: string) => api.delete<DeletePdfResponse>(`/pdf/${pdfId}`),
};
