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
  query: (question: string, topK?: number) =>
    api.post<KnowledgeQueryResponse>(
      "/knowledge/query",
      { question, top_k: topK ?? null },
      { timeoutMs: QUERY_TIMEOUT_MS },
    ),

  /** GET /knowledge/status — engine readiness + index size + config. */
  status: (signal?: AbortSignal) =>
    api.get<KnowledgeStatusResponse>("/knowledge/status", { signal }),
};
