/**
 * Knowledge RAG service (Phase 10).
 * Routes: POST /knowledge/index · POST /knowledge/query · GET /knowledge/status
 */

import { api } from "@/services/api-client";
import type {
  KnowledgeIndexResponse,
  KnowledgeQueryResponse,
  KnowledgeStatusResponse,
} from "@/types/api";

// Index rebuilds embed the whole corpus (and download the model on first
// run); querying loads the model lazily too — both need patient timeouts.
const INDEX_TIMEOUT_MS = 300_000;
const QUERY_TIMEOUT_MS = 90_000;

export const knowledgeService = {
  /** POST /knowledge/index — (re)build the vector index from the corpus. */
  buildIndex: () =>
    api.post<KnowledgeIndexResponse>("/knowledge/index", undefined, {
      timeoutMs: INDEX_TIMEOUT_MS,
    }),

  /** POST /knowledge/query — grounded, cited answer (or an honest IDK). */
  /**
   * `sessionId` is the ACTIVE KYC session, when there is one. The backend uses
   * it to answer "what's left for me?" from that session's own state instead
   * of from the document corpus. Omitted for guests with no workflow open.
   */
  query: (question: string, topK?: number, sessionId?: string | null) =>
    api.post<KnowledgeQueryResponse>(
      "/knowledge/query",
      { question, top_k: topK ?? null, session_id: sessionId ?? null },
      { timeoutMs: QUERY_TIMEOUT_MS },
    ),

  /** GET /knowledge/status — engine readiness + index size + config. */
  status: (signal?: AbortSignal) =>
    api.get<KnowledgeStatusResponse>("/knowledge/status", { signal }),
};
