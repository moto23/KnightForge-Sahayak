/**
 * Saved-conversations service — 1:1 with the backend /chats routes (Phase 12).
 * All endpoints require a signed-in access token (set by the auth context);
 * guests keep using knowledgeService.query directly, nothing saved.
 */

import { api } from "@/services/api-client";
import type {
  AskChatResponse,
  ChatDetailResponse,
  ChatListResponse,
  ChatSummary,
  DeleteChatResponse,
} from "@/types/api";

export const chatsService = {
  create: (title?: string) => api.post<ChatSummary>("/chats", { title }),
  list: (query?: string, signal?: AbortSignal) =>
    api.get<ChatListResponse>(
      query?.trim() ? `/chats?q=${encodeURIComponent(query.trim())}` : "/chats",
      { signal },
    ),
  get: (chatId: string, signal?: AbortSignal) =>
    api.get<ChatDetailResponse>(`/chats/${chatId}`, { signal }),
  ask: (chatId: string, question: string, sessionId?: string | null) =>
    api.post<AskChatResponse>(
      `/chats/${chatId}/messages`,
      { question, session_id: sessionId ?? null },
      { timeoutMs: 90_000 }, // embedding + Gemini can take a while
    ),
  rename: (chatId: string, title: string) =>
    api.patch<ChatSummary>(`/chats/${chatId}`, { title }),
  remove: (chatId: string) => api.delete<DeleteChatResponse>(`/chats/${chatId}`),
};
