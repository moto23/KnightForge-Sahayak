/**
 * Typed wire models for the KnightForge Sahayak backend (Phases 1–8).
 *
 * These mirror the FastAPI Pydantic DTOs one-to-one (snake_case preserved) so
 * the OpenAPI contract and this file never drift apart silently. All frontend
 * code consumes these types — no `any` anywhere in the data path.
 */

/* ------------------------------------------------------------------ */
/* Shared / enums                                                      */
/* ------------------------------------------------------------------ */

export type InterviewStatus =
  | "not_started"
  | "in_progress"
  | "completed"
  | "abandoned";

export type FieldType =
  | "text"
  | "number"
  | "date"
  | "email"
  | "phone"
  | "single_choice"
  | "multi_choice"
  | "boolean";

export type Language = "english" | "hinglish" | "hindi";

export interface ValidationResult {
  valid: boolean;
  code: string;
  message: string;
}

export interface InvalidAttempt {
  value: string | null;
  code: string;
  message: string;
}

/** The backend's uniform error envelope: {"error": {"code", "message"}}. */
export interface ApiErrorEnvelope {
  error: { code: string; message: string };
}

/* ------------------------------------------------------------------ */
/* Form schema (/schema)                                               */
/* ------------------------------------------------------------------ */

export interface FieldOption {
  value: string;
  label: string;
}

export interface KYCField {
  id: string;
  display_name: string;
  section: string;
  field_type: FieldType;
  required: boolean;
  placeholder: string | null;
  help_text: string | null;
  validation_type: string;
  example: string | null;
  options: FieldOption[];
}

export interface KYCSection {
  id: string;
  title: string;
  description: string | null;
  order: number;
  fields: KYCField[];
}

export interface KYCForm {
  id: string;
  title: string;
  description: string | null;
  version: string;
  sections: KYCSection[];
}

export interface FormSchemaResponse {
  form: KYCForm;
  total_fields: number;
}

/* ------------------------------------------------------------------ */
/* Session & interview (/session)                                      */
/* ------------------------------------------------------------------ */

export interface SessionResponse {
  session_id: string;
  form_id: string;
  created_at: string;
  updated_at: string;
  interview_status: InterviewStatus;
  current_field: string | null;
  completed_fields: string[];
  answers: Record<string, string>;
  validation_errors: Record<string, InvalidAttempt>;
  progress_percentage: number;
}

export interface CreateSessionResponse {
  session: SessionResponse;
  next_question: KYCField | null;
}

export interface SubmitAnswerRequest {
  field_id: string;
  value: string | null;
}

export interface SubmitAnswerResponse {
  field_id: string;
  accepted: boolean;
  result: ValidationResult;
  session: SessionResponse;
  next_question: KYCField | null;
}

export interface NextQuestionResponse {
  session_id: string;
  completed: boolean;
  question: KYCField | null;
  remaining_required: number;
}

export interface ProgressResponse {
  session_id: string;
  interview_status: InterviewStatus;
  progress_percentage: number;
  total_fields: number;
  required_fields: number;
  answered_fields: number;
  completed_required_fields: number;
  pending_required_fields: string[];
  invalid_fields: string[];
}

export interface DeleteSessionResponse {
  session_id: string;
  deleted: boolean;
}

export interface ClearAnswerResponse {
  field_id: string;
  cleared: boolean;
  session: SessionResponse;
}

/* ------------------------------------------------------------------ */
/* Upload (/upload)                                                    */
/* ------------------------------------------------------------------ */

export interface DocumentMetadata {
  document_id: string;
  original_filename: string;
  stored_filename: string;
  content_type: string;
  file_size: number;
  category: "pdf" | "image";
  uploaded_at: string;
}

export interface UploadResponse {
  message: string;
  document: DocumentMetadata;
}

export interface ListUploadsResponse {
  total: number;
  documents: DocumentMetadata[];
}

export interface DeleteUploadResponse {
  document_id: string;
  deleted: boolean;
}

/* ------------------------------------------------------------------ */
/* Document understanding (/ocr)                                       */
/* ------------------------------------------------------------------ */

export type DocumentQuality = "good" | "fair" | "poor" | "blank";

export interface DocumentAnalysisResponse {
  document_id: string;
  category: "pdf" | "image";
  document_type: string;
  page_count: number;
  overall_quality: DocumentQuality;
  ocr_required: boolean;
  pages: {
    page_number: number;
    width: number;
    height: number;
    has_text_layer: boolean;
    quality: DocumentQuality;
  }[];
  warnings: string[];
}

export interface OCRSummaryResponse {
  engine: string;
  pages_read: number;
  total_chars: number;
  mean_confidence: number;
  warnings: string[];
}

export interface ExtractedFieldResponse {
  field_id: string;
  value: string;
  confidence: number;
  source: string;
  method: string;
  page_number: number;
  validation_result: ValidationResult;
  accepted: boolean;
}

export interface ExtractionResponse {
  document_id: string;
  is_kyc_form: boolean;
  fields_found: number;
  fields_accepted: number;
  fields: ExtractedFieldResponse[];
  missing_required: string[];
  warnings: string[];
}

export interface OCRExtractResponse {
  extraction: ExtractionResponse;
  analysis: DocumentAnalysisResponse;
  ocr: OCRSummaryResponse;
  processed_at: string;
}

export interface PrefillResponse {
  session_id: string;
  document_id: string;
  prefilled_count: number;
  prefilled: { field_id: string; value: string; confidence: number }[];
  skipped: { field_id: string; reason: string; confidence: number }[];
  remaining_required: string[];
  progress_percentage: number;
}

/* ------------------------------------------------------------------ */
/* AI conversation (/conversation)                                     */
/* ------------------------------------------------------------------ */

export interface ExtractedAnswerModel {
  field_id: string;
  value: string | null;
  confidence: string;
  intent: string;
  ai_generated: boolean;
}

export interface StartConversationResponse {
  session_id: string;
  language: Language;
  message: string;
  ai_generated: boolean;
  question: KYCField | null;
  session: SessionResponse;
}

export interface ReplyResponse {
  session_id: string;
  message: string;
  ai_generated: boolean;
  intent: string;
  extraction: ExtractedAnswerModel | null;
  accepted: boolean | null;
  validation: ValidationResult | null;
  next_question: KYCField | null;
  interview_status: InterviewStatus;
  progress_percentage: number;
}

export interface ExplainResponse {
  session_id: string;
  field_id: string | null;
  message: string;
  ai_generated: boolean;
}

/* ------------------------------------------------------------------ */
/* PDF generation (/pdf)                                               */
/* ------------------------------------------------------------------ */

export interface GeneratedPdfResponse {
  pdf_id: string;
  generated_by_session: string;
  template_id: string;
  template_version: string;
  page_count: number;
  file_size: number;
  fields_filled: number;
  generated_at: string;
  download_url: string;
}

export interface GeneratePdfResponse {
  message: string;
  pdf: GeneratedPdfResponse;
}

export interface DeletePdfResponse {
  pdf_id: string;
  deleted: boolean;
}

/* ------------------------------------------------------------------ */
/* Health                                                              */
/* ------------------------------------------------------------------ */

export interface HealthResponse {
  status: string;
  app_name?: string;
  version?: string;
  [key: string]: unknown;
}

/* ------------------------------------------------------------------ */
/* Knowledge RAG (Phase 10)                                            */
/* ------------------------------------------------------------------ */

export interface KnowledgeIndexResponse {
  documents_indexed: number;
  chunks_indexed: number;
  document_names: string[];
  embedding_model: string;
  elapsed_seconds: number;
  indexed_at: string;
}

export interface KnowledgeCitation {
  document_name: string;
  source: string;
  page_number: number;
  similarity: number;
  snippet: string;
}

export interface KnowledgeQueryResponse {
  question: string;
  answer: string;
  /** False = honest "I don't know" — the engine refused to guess. */
  confident: boolean;
  /** LLM model name, "extractive-fallback" (AI offline), or "none". */
  generator: string;
  citations: KnowledgeCitation[];
}

export interface KnowledgeStatusResponse {
  ready: boolean;
  dependencies_installed: boolean;
  ai_available: boolean;
  document_count: number;
  chunk_count: number;
  embedding_model: string;
  vector_db_path: string;
  collection: string;
  chunk_size: number;
  chunk_overlap: number;
  top_k: number;
  min_similarity: number;
  last_indexed_at: string | null;
}

/* --------------------------------------------------------------------- *
 * Universal Document Intelligence (Phase 11) — /intelligence endpoints
 * --------------------------------------------------------------------- */

export interface DocumentTypeInfo {
  /** Matched schema id (e.g. "sbi_kyc", "pan_card"), or "unknown". */
  schema_id: string;
  label: string;
  kind: "kyc_form" | "identity_document" | "unknown";
  confidence: number;
  matched_markers: string[];
}

export interface CanonicalValueInfo {
  canonical_id: string;
  label: string;
  value: string;
  confidence: number;
  valid: boolean;
  page_number: number;
}

export interface IntelligenceDocumentSummary {
  document_id: string;
  filename: string;
  sequence: number;
  document_type: DocumentTypeInfo;
  values: CanonicalValueInfo[];
}

export interface MergedFieldInfo {
  canonical_id: string;
  label: string;
  value: string;
  source_document_id: string;
  source_document_name: string;
  source_type_label: string;
  confidence: number;
  validated: boolean;
  /** True if the user chose this value in a conflict. */
  resolved: boolean;
  /** True if written into the interview session. */
  applied: boolean;
  session_field_id: string | null;
}

export interface ConflictOptionInfo {
  document_id: string;
  document_name: string;
  document_type_label: string;
  value: string;
  confidence: number;
  valid: boolean;
}

export interface FieldConflictInfo {
  canonical_id: string;
  label: string;
  options: ConflictOptionInfo[];
  resolved: boolean;
  resolved_value: string | null;
}

export interface ExtraFieldInfo {
  key: string;
  label: string;
  value: string;
  source_document_id: string;
  source_document_name: string;
  source_type_label: string;
  confidence: number;
  page_number: number;
}

export interface MissingFieldInfo {
  canonical_id: string;
  label: string;
  session_field_id: string;
  required: boolean;
}

export interface PrimaryFormInfo {
  schema_id: string;
  label: string;
}

export interface UnifiedProfileResponse {
  session_id: string;
  /** "empty" | "merged" | "conflicts" (open conflicts pending). */
  merge_status: string;
  /** The ONE form this session generates as final output (if selected). */
  primary_form: PrimaryFormInfo | null;
  documents: IntelligenceDocumentSummary[];
  fields: MergedFieldInfo[];
  /** Canonical fields still unanswered — the interview asks only these. */
  missing_fields: MissingFieldInfo[];
  /** Extended-profile values (evidence outside the canonical KYC model). */
  extra_fields: ExtraFieldInfo[];
  conflicts: FieldConflictInfo[];
  applied_field_ids: string[];
  progress_percentage: number;
  updated_at: string;
}

export interface IntelligenceProcessResponse {
  document: IntelligenceDocumentSummary;
  /** Session field ids applied from THIS document (for provenance). */
  applied_from_document: string[];
  profile: UnifiedProfileResponse;
}

/* --------------------------------------------------------------------- *
 * Authentication + Saved Conversations (Phase 12) — /auth and /chats
 * --------------------------------------------------------------------- */

export interface UserProfile {
  user_id: string;
  email: string;
  full_name: string;
  has_password: boolean;
  google_linked: boolean;
  created_at: string;
}

export interface AuthResponse {
  user: UserProfile;
  /** Short-lived JWT — held in memory only, never persisted client-side. */
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
}

export interface LogoutResponse {
  logged_out: boolean;
  sessions_revoked: number;
}

export interface ProvidersResponse {
  google: boolean;
}

export interface GoogleLoginResponse {
  auth_url: string;
}

export interface ChatCitation {
  document_name: string;
  source: string;
  page_number: number;
  similarity: number;
  snippet: string;
}

export interface ChatMessage {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  citations: ChatCitation[];
  confident: boolean | null;
  generator: string | null;
  created_at: string;
}

export interface ChatSummary {
  chat_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatDetailResponse {
  chat: ChatSummary;
  messages: ChatMessage[];
}

export interface ChatListResponse {
  total: number;
  chats: ChatSummary[];
}

export interface AskChatResponse {
  chat_id: string;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
}

export interface DeleteChatResponse {
  deleted: boolean;
  chat_id: string;
}

/* --------------------------------------------------------------------- *
 * Upload history + document types (Phase 13) — /upload/history
 * --------------------------------------------------------------------- */

/** User-selected document type, chosen BEFORE upload. */
export type UploadDocumentType =
  | "kyc_form"
  | "pan_card"
  | "aadhaar_card"
  | "passport"
  | "driving_licence"
  | "bank_statement"
  | "utility_bill"
  | "other";

export interface UploadHistoryItem {
  history_id: string;
  document_id: string;
  filename: string;
  document_type: UploadDocumentType;
  /** AI-detected type label (Phase 11 classifier), once known. */
  detected_type: string | null;
  file_size: number;
  ocr_status: "pending" | "completed" | "failed";
  processing_status: "uploaded" | "analyzed" | "prefilled" | "deleted";
  uploaded_at: string;
}

export interface UploadHistoryResponse {
  total: number;
  items: UploadHistoryItem[];
}
