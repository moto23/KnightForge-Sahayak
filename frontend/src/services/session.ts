/**
 * Session service — 1:1 with the backend /session routes.
 * POST /session · GET /session/{id} · DELETE /session/{id}
 * POST /session/{id}/answer · DELETE /session/{id}/answer/{field_id}
 * GET /session/{id}/next · GET /session/{id}/progress
 */

import { api } from "@/services/api-client";
import type {
  ClearAnswerResponse,
  CreateSessionResponse,
  DeleteSessionResponse,
  NextQuestionResponse,
  ProgressResponse,
  SessionResponse,
  SubmitAnswerResponse,
} from "@/types/api";

export const sessionService = {
  create: () => api.post<CreateSessionResponse>("/session"),
  get: (sessionId: string) =>
    api.get<SessionResponse>(`/session/${sessionId}`),
  remove: (sessionId: string) =>
    api.delete<DeleteSessionResponse>(`/session/${sessionId}`),
  submitAnswer: (sessionId: string, fieldId: string, value: string | null) =>
    api.post<SubmitAnswerResponse>(`/session/${sessionId}/answer`, {
      field_id: fieldId,
      value,
    }),
  /** Un-answer one field (prefill rollback) — it becomes pending again. */
  clearAnswer: (sessionId: string, fieldId: string) =>
    api.delete<ClearAnswerResponse>(
      `/session/${sessionId}/answer/${fieldId}`,
    ),
  nextQuestion: (sessionId: string) =>
    api.get<NextQuestionResponse>(`/session/${sessionId}/next`),
  progress: (sessionId: string) =>
    api.get<ProgressResponse>(`/session/${sessionId}/progress`),
};
