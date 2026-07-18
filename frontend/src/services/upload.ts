/**
 * Upload service — 1:1 with the backend /upload routes.
 * POST /upload (multipart) · GET /upload · GET /upload/{id}
 * GET /upload/{id}/file · DELETE /upload/{id}
 */

import { absoluteUrl, api, apiUpload } from "@/services/api-client";
import type {
  DeleteUploadResponse,
  DocumentMetadata,
  ListUploadsResponse,
  UploadDocumentType,
  UploadHistoryResponse,
  UploadResponse,
} from "@/types/api";

export const uploadService = {
  /** Multipart upload with live progress %; cancellable via signal. */
  upload: (
    file: File,
    documentType: UploadDocumentType,
    onProgress?: (percent: number) => void,
    signal?: AbortSignal,
  ) =>
    apiUpload<UploadResponse>("/upload", file, onProgress, signal, {
      document_type: documentType,
    }),
  list: () => api.get<ListUploadsResponse>("/upload"),
  /** The signed-in account's persistent upload history (Phase 13). */
  history: (signal?: AbortSignal) =>
    api.get<UploadHistoryResponse>("/upload/history", { signal }),
  get: (documentId: string) =>
    api.get<DocumentMetadata>(`/upload/${documentId}`),
  /**
   * Stable URL of the stored document bytes (inline content-disposition) —
   * the persistent "View document" target that survives refresh/navigation.
   */
  fileUrl: (documentId: string) => absoluteUrl(`/upload/${documentId}/file`),
  remove: (documentId: string) =>
    api.delete<DeleteUploadResponse>(`/upload/${documentId}`),
};
