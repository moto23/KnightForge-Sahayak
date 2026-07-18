/**
 * Service layer barrel (Phase 9B).
 *
 * One file per backend feature — each maps 1:1 to a FastAPI router, so the
 * whole backend surface is visible from this directory:
 *
 *   health.ts        GET /health · GET /schema
 *   session.ts       /session (create, get, delete, answer, next, progress)
 *   upload.ts        /upload  (multipart upload, list, get, delete)
 *   ocr.ts           /ocr     (extract, cached understanding, prefill)
 *   conversation.ts  /conversation (start, reply, explain)
 *   pdf.ts           /pdf     (generate, list, get, delete, download URL)
 *   knowledge.ts     /knowledge (index, query, status) — Phase 10 RAG
 *   intelligence.ts  /intelligence (process, profile, resolve) — Phase 11
 *   auth.ts          /auth (register, login, refresh, logout, google) — Phase 12
 *   chats.ts         /chats (saved conversations + messages) — Phase 12
 *
 * Pages and hooks NEVER call fetch directly; they import from here.
 */

export { formsService, healthService } from "@/services/health";
export { sessionService } from "@/services/session";
export { uploadService } from "@/services/upload";
export { ocrService } from "@/services/ocr";
export { conversationService } from "@/services/conversation";
export { pdfService } from "@/services/pdf";
export { knowledgeService } from "@/services/knowledge";
export { intelligenceService } from "@/services/intelligence";
export { authService } from "@/services/auth";
export { chatsService } from "@/services/chats";
