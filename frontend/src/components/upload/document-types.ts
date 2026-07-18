/**
 * User-facing document types (Phase 13) — selected BEFORE upload and stored
 * with the upload-history row. One list, shared by the type selector and the
 * history panels so labels never drift.
 */

import type { UploadDocumentType } from "@/types/api";

export const DOCUMENT_TYPES: { value: UploadDocumentType; label: string }[] = [
  { value: "kyc_form", label: "KYC Form" },
  { value: "pan_card", label: "PAN Card" },
  { value: "aadhaar_card", label: "Aadhaar Card" },
  { value: "passport", label: "Passport" },
  { value: "driving_licence", label: "Driving Licence" },
  { value: "bank_statement", label: "Bank Statement" },
  { value: "utility_bill", label: "Utility Bill" },
  { value: "other", label: "Other" },
];

export const DOCUMENT_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  DOCUMENT_TYPES.map((t) => [t.value, t.label]),
);

/**
 * The PRIMARY forms a session can generate as its final output (backend
 * schema ids of kind "kyc_form"). Supporting documents are only evidence.
 */
export const PRIMARY_FORMS: { value: string; label: string }[] = [
  { value: "cvl_kyc", label: "CVL KYC (CDSL)" },
  { value: "sbi_kyc", label: "SBI KYC" },
  { value: "hdfc_kyc", label: "HDFC KYC" },
  { value: "icici_kyc", label: "ICICI KYC" },
  { value: "axis_kyc", label: "Axis KYC" },
];
