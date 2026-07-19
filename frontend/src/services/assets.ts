/**
 * Form asset service — 1:1 with the backend /assets routes.
 * GET /assets/{sid} · POST /assets/{sid}/{kind} · DELETE /assets/{sid}/{kind}
 *
 * Assets (photograph, signature) are only ever collected when the session's
 * ACTIVE primary form actually requires them — `requirements()` is what tells
 * the UI whether to mention them at all.
 */

import { absoluteUrl, api, apiUpload } from "@/services/api-client";
import type {
  AssetDeleteResponse,
  AssetKind,
  AssetUploadResponse,
  SessionAssetsResponse,
} from "@/types/api";

export const assetsService = {
  /** What this session's form requires, and what has been supplied. */
  requirements: (sessionId: string, signal?: AbortSignal) =>
    api.get<SessionAssetsResponse>(`/assets/${sessionId}`, { signal }),

  /** Upload (or replace) one photograph/signature. */
  upload: (
    sessionId: string,
    kind: AssetKind,
    file: File,
    onProgress?: (percent: number) => void,
    signal?: AbortSignal,
  ) =>
    apiUpload<AssetUploadResponse>(
      `/assets/${sessionId}/${kind}`,
      file,
      onProgress,
      signal,
    ),

  /** Remove one asset — its interview field returns to PENDING. */
  remove: (sessionId: string, kind: AssetKind) =>
    api.delete<AssetDeleteResponse>(`/assets/${sessionId}/${kind}`),

  /** Stable preview URL for a stored asset. */
  fileUrl: (sessionId: string, kind: AssetKind) =>
    absoluteUrl(`/assets/${sessionId}/${kind}/file`),
};
