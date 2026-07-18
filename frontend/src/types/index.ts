/**
 * Frontend domain types (Phase 9A — UI only).
 *
 * These mirror the backend's public API shapes so Phase 9B integration is a
 * drop-in: services/ will fetch real data into these exact types. Until then
 * they type the placeholder data used by the UI.
 */

/** Lifecycle of a single form field on the progress dashboard. */
export type FieldStatus = "answered" | "prefilled" | "pending" | "invalid";

export type FieldProgress = {
  fieldId: string;
  label: string;
  section: string;
  required: boolean;
  status: FieldStatus;
  value?: string;
};

/** One message in the AI interview chat. */
export type ChatMessage = {
  id: string;
  role: "assistant" | "user";
  content: string;
  /** Field this question/answer relates to, when applicable. */
  fieldId?: string;
  timestamp: string;
};

/** An uploaded source document (KYC scan, ID proof…). */
export type UploadedDocument = {
  documentId: string;
  filename: string;
  contentType: string;
  sizeBytes: number;
  pageCount?: number;
  status: "uploaded" | "processing" | "analyzed" | "failed";
  uploadedAt: string;
};

/** Metadata of a generated, filled PDF. */
export type GeneratedPdf = {
  pdfId: string;
  templateId: string;
  templateVersion: string;
  pageCount: number;
  fileSize: number;
  fieldsFilled: number;
  generatedAt: string;
  downloadUrl: string;
};

/** High-level session summary for the dashboard. */
export type SessionSummary = {
  sessionId: string;
  formName: string;
  progressPercent: number;
  answeredCount: number;
  requiredCount: number;
  status: "in_progress" | "completed";
  updatedAt: string;
};
