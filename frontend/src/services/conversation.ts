/**
 * AI conversation service — 1:1 with the backend /conversation routes.
 * POST /conversation/start · POST /conversation/reply · POST /conversation/explain
 * (POST /conversation/extract is intentionally unused: /reply already performs
 *  extraction + validation + next-question in one call.)
 */

import { api } from "@/services/api-client";
import type {
  ExplainResponse,
  Language,
  ReplyResponse,
  StartConversationResponse,
} from "@/types/api";

/** LLM turns can be slow — give conversation calls more headroom. */
const CHAT_TIMEOUT = { timeoutMs: 45_000 };

export const conversationService = {
  start: (language: Language = "english") =>
    api.post<StartConversationResponse>(
      "/conversation/start",
      { language },
      CHAT_TIMEOUT,
    ),
  reply: (sessionId: string, message: string, language: Language = "english") =>
    api.post<ReplyResponse>(
      "/conversation/reply",
      { session_id: sessionId, message, language },
      CHAT_TIMEOUT,
    ),
  explain: (
    sessionId: string,
    fieldId?: string,
    language: Language = "english",
  ) =>
    api.post<ExplainResponse>(
      "/conversation/explain",
      { session_id: sessionId, field_id: fieldId ?? null, language },
      CHAT_TIMEOUT,
    ),
};
