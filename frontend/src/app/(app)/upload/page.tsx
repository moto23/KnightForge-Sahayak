"use client";

import * as React from "react";
import Link from "next/link";
import { AnimatePresence } from "framer-motion";
import { ArrowRight, Info } from "lucide-react";
import { toast } from "sonner";

import { PageHeader } from "@/components/shared/page-header";
import { EmptyState, ErrorState } from "@/components/shared/states";
import { UploadCard } from "@/components/shared/upload-card";
import {
  DocumentCard,
  type WorkspaceDocument,
} from "@/components/upload/document-card";
import { DOCUMENT_TYPES, PRIMARY_FORMS } from "@/components/upload/document-types";
import { ProfilePanel } from "@/components/upload/profile-panel";
import { UploadHistoryPanel } from "@/components/upload/upload-history-panel";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { SkeletonRow } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useKycSession } from "@/hooks/use-kyc-session";
import { toApiError } from "@/services/api-client";
import { intelligenceService, ocrService, uploadService } from "@/services";
import type {
  FieldConflictInfo,
  UnifiedProfileResponse,
  UploadDocumentType,
} from "@/types/api";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const ALLOWED_TYPES = ["application/pdf", "image/png", "image/jpeg"];

/**
 * Upload Workspace (Phase 9B.1, extended by Phase 11 Universal Document
 * Intelligence). Upload multiple documents with real progress → OCR →
 * document classification (type badges) → canonical extraction → merge into
 * ONE unified profile → conflict cards → validated session prefill.
 */
export default function UploadPage() {
  const {
    sessionId,
    ensureSession,
    refresh,
    markPrefilled,
    rollbackPrefill,
    fieldMap,
  } = useKycSession();

  const [docs, setDocs] = React.useState<WorkspaceDocument[]>([]);
  const [listState, setListState] = React.useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [listError, setListError] = React.useState<string>("");
  const [prefillingKey, setPrefillingKey] = React.useState<string | null>(null);
  const [profile, setProfile] = React.useState<UnifiedProfileResponse | null>(null);
  const [resolvingId, setResolvingId] = React.useState<string | null>(null);
  // Phase 13: the type must be chosen BEFORE uploading; stored with history.
  const [documentType, setDocumentType] =
    React.useState<UploadDocumentType | null>(null);
  const [historyKey, setHistoryKey] = React.useState(0);
  // Phase 13: ONE primary form is the final output; documents are evidence.
  const [primaryForm, setPrimaryForm] = React.useState<string>(PRIMARY_FORMS[0].value);
  // Last primary-form id the backend has confirmed for this session.
  const syncedFormRef = React.useRef<string | null>(null);

  const labelOf = React.useCallback(
    (fieldId: string) => fieldMap.get(fieldId)?.display_name ?? fieldId,
    [fieldMap],
  );

  const patchDoc = React.useCallback(
    (key: string, patch: Partial<WorkspaceDocument>) => {
      setDocs((prev) =>
        prev.map((d) => (d.key === key ? { ...d, ...patch } : d)),
      );
    },
    [],
  );

  /* --- initial load: existing documents + their cached extractions ---- */
  const fetchExisting = React.useCallback(async (): Promise<WorkspaceDocument[]> => {
    const { documents } = await uploadService.list();
    return Promise.all(
      documents.map(async (meta) => {
        // Cached understanding may or may not exist — 404 is normal.
        let extraction = null;
        try {
          extraction = await ocrService.getUnderstanding(meta.document_id);
        } catch {
          /* never processed — leave null */
        }
        return {
          key: meta.document_id,
          documentId: meta.document_id,
          filename: meta.original_filename,
          contentType: meta.content_type,
          sizeBytes: meta.file_size,
          phase: extraction ? ("analyzed" as const) : ("failed" as const),
          uploadPercent: 100,
          extraction,
          docType: null,
          errorMessage: extraction ? null : "Not analyzed yet — re-upload to process.",
          // Persistent preview: the backend serves the stored bytes back, so
          // "View document" survives OCR, refresh, and navigation.
          previewUrl: uploadService.fileUrl(meta.document_id),
        };
      }),
    );
  }, []);

  /* --- unified profile (Phase 11) -------------------------------------- */

  /** Store a profile snapshot and restore doc-type badges from it. */
  const applyProfileSnapshot = React.useCallback(
    (snapshot: UnifiedProfileResponse) => {
      setProfile(snapshot);
      if (snapshot.primary_form) {
        // The backend's stored choice wins (e.g. restored after a refresh).
        syncedFormRef.current = snapshot.primary_form.schema_id;
        setPrimaryForm(snapshot.primary_form.schema_id);
      }
      setDocs((prev) =>
        prev.map((d) => {
          const summary = snapshot.documents.find(
            (doc) => doc.document_id === d.documentId,
          );
          return summary ? { ...d, docType: summary.document_type } : d;
        }),
      );
    },
    [],
  );

  /** Persist the primary-form choice; deferred until a session exists. */
  const handleSelectPrimaryForm = async (formId: string) => {
    setPrimaryForm(formId);
    if (!sessionId) return; // synced later, on the first document process
    try {
      const snapshot = await intelligenceService.setPrimaryForm(sessionId, formId);
      applyProfileSnapshot(snapshot);
      syncedFormRef.current = formId;
    } catch {
      /* progressive enhancement — retried before the next document process */
    }
  };

  /** Re-fetch the merged profile (used after deletes / on demand). */
  const refreshProfile = React.useCallback(
    async (sid: string) => {
      try {
        applyProfileSnapshot(await intelligenceService.profile(sid));
      } catch {
        /* profile is progressive enhancement — the list keeps working */
      }
    },
    [applyProfileSnapshot],
  );

  React.useEffect(() => {
    if (!sessionId || listState !== "ready") return;
    let cancelled = false;
    intelligenceService
      .profile(sessionId)
      .then((snapshot) => {
        if (!cancelled) applyProfileSnapshot(snapshot);
      })
      .catch(() => {
        /* profile is progressive enhancement — the list keeps working */
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, listState, applyProfileSnapshot]);

  React.useEffect(() => {
    let cancelled = false;
    fetchExisting()
      .then((restored) => {
        if (cancelled) return;
        setDocs(restored);
        setListState("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setListError(toApiError(err).message);
        setListState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [fetchExisting]);

  const retryLoad = () => {
    setListState("loading");
    fetchExisting()
      .then((restored) => {
        setDocs(restored);
        setListState("ready");
      })
      .catch((err: unknown) => {
        setListError(toApiError(err).message);
        setListState("error");
      });
  };

  /* --- upload + OCR pipeline per file --------------------------------- */
  const handleFiles = (files: File[]) => {
    if (!documentType) {
      toast.error("Choose a document type first", {
        description: "Select what you're uploading — it's stored with your history.",
      });
      return;
    }
    for (const file of files) {
      if (!ALLOWED_TYPES.includes(file.type)) {
        toast.error(`${file.name}: unsupported type`, {
          description: "Please upload a PDF, PNG or JPG.",
        });
        continue;
      }
      if (file.size > MAX_UPLOAD_BYTES) {
        toast.error(`${file.name}: too large`, {
          description: "Maximum file size is 10 MB.",
        });
        continue;
      }
      void processFile(file, documentType);
    }
  };

  const processFile = async (file: File, selectedType: UploadDocumentType) => {
    const key = `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    // Temporary object URL so the preview works while the upload is in flight;
    // swapped for the backend's persistent file URL once storage confirms.
    const blobUrl = URL.createObjectURL(file);
    setDocs((prev) => [
      {
        key,
        documentId: null,
        filename: file.name,
        contentType: file.type,
        sizeBytes: file.size,
        phase: "uploading",
        uploadPercent: 0,
        extraction: null,
        docType: null,
        errorMessage: null,
        previewUrl: blobUrl,
      },
      ...prev,
    ]);

    // 1) Upload with progress
    let documentId: string;
    try {
      const uploaded = await uploadService.upload(file, selectedType, (percent) =>
        patchDoc(key, { uploadPercent: percent }),
      );
      documentId = uploaded.document.document_id;
      setHistoryKey((k) => k + 1); // history panel picks up the new row
      // Preview now points at the stored bytes — persistent across refresh.
      patchDoc(key, {
        documentId,
        phase: "processing",
        previewUrl: uploadService.fileUrl(documentId),
      });
      URL.revokeObjectURL(blobUrl);
      toast.success(`${file.name} uploaded`, {
        description: "Reading the document now…",
      });
    } catch (err) {
      const apiError = toApiError(err);
      patchDoc(key, { phase: "failed", errorMessage: apiError.message });
      toast.error(`Upload failed: ${file.name}`, { description: apiError.message });
      return;
    }

    // 2) OCR + structured extraction
    try {
      const extraction = await ocrService.extract(documentId);
      patchDoc(key, { phase: "analyzed", extraction });
      const accepted = extraction.extraction.fields_accepted;
      toast.success(`${file.name} analyzed`, {
        description:
          accepted > 0
            ? `${accepted} field${accepted > 1 ? "s" : ""} ready to prefill your form.`
            : extraction.extraction.fields_found === 0
              ? "The document was read, but no values were found to prefill — the interview will collect what's missing."
              : "Values were read but none passed validation confidently — you can review them on the card.",
      });
    } catch (err) {
      const apiError = toApiError(err);
      patchDoc(key, { phase: "failed", errorMessage: apiError.message });
      toast.error(`Could not read ${file.name}`, { description: apiError.message });
      return;
    }

    // 3) Universal Document Intelligence: classify the document, extract its
    //    canonical fields, and merge it into the session's unified profile.
    //    OCR is already cached, so this is fast.
    try {
      const sid = await ensureSession();
      // Make sure the backend knows which PRIMARY form this session builds
      // (chosen before a session existed, or changed since the last sync).
      if (syncedFormRef.current !== primaryForm) {
        try {
          await intelligenceService.setPrimaryForm(sid, primaryForm);
          syncedFormRef.current = primaryForm;
        } catch {
          /* non-fatal — the profile still merges; retried next time */
        }
      }
      const result = await intelligenceService.process(documentId, sid);
      patchDoc(key, { docType: result.document.document_type });
      // Provenance: deleting this document later rolls back exactly the
      // session answers whose merged value came from it.
      markPrefilled(result.applied_from_document, documentId);
      applyProfileSnapshot(result.profile);
      await refresh();
      const openConflicts = result.profile.conflicts.filter((c) => !c.resolved);
      if (openConflicts.length > 0) {
        toast.warning("Conflict detected", {
          description: `Your documents disagree about ${openConflicts
            .map((c) => c.label.toLowerCase())
            .join(", ")} — please choose the correct value below.`,
        });
      } else if (result.applied_from_document.length > 0) {
        toast.success(
          `Detected: ${result.document.document_type.label}`,
          {
            description: `${result.applied_from_document.length} merged value${result.applied_from_document.length === 1 ? "" : "s"} applied to your form.`,
          },
        );
      }
    } catch {
      /* intelligence is progressive enhancement — manual prefill still works */
    } finally {
      setHistoryKey((k) => k + 1); // OCR/processing statuses changed
    }
  };

  /* --- conflict resolution ---------------------------------------------- */
  const handleResolve = async (
    conflict: FieldConflictInfo,
    documentId: string,
  ) => {
    if (!sessionId || resolvingId) return;
    setResolvingId(conflict.canonical_id);
    try {
      const snapshot = await intelligenceService.resolve(
        sessionId,
        conflict.canonical_id,
        documentId,
      );
      applyProfileSnapshot(snapshot);
      const resolvedField = snapshot.fields.find(
        (f) => f.canonical_id === conflict.canonical_id,
      );
      if (resolvedField?.applied && resolvedField.session_field_id) {
        markPrefilled(
          [resolvedField.session_field_id],
          resolvedField.source_document_id,
        );
      }
      await refresh();
      toast.success(`${conflict.label} resolved`, {
        description: "The value you chose was applied to your form.",
      });
    } catch (err) {
      toast.error("Couldn't resolve the conflict", {
        description: toApiError(err).message,
      });
    } finally {
      setResolvingId(null);
    }
  };

  /* --- prefill --------------------------------------------------------- */
  const handlePrefill = async (doc: WorkspaceDocument) => {
    if (!doc.documentId) return;
    setPrefillingKey(doc.key);
    try {
      const sessionId = await ensureSession();
      const report = await ocrService.prefill(doc.documentId, sessionId);
      markPrefilled(
        report.prefilled.map((p) => p.field_id),
        doc.documentId,
      );
      await refresh();
      toast.success(
        `${report.prefilled_count} field${report.prefilled_count === 1 ? "" : "s"} prefilled`,
        {
          description:
            report.remaining_required.length === 0
              ? "All required fields are complete — you can generate the PDF!"
              : `${report.remaining_required.length} required field${report.remaining_required.length === 1 ? "" : "s"} left for the interview.`,
        },
      );
    } catch (err) {
      toast.error("Prefill failed", { description: toApiError(err).message });
    } finally {
      setPrefillingKey(null);
    }
  };

  /* --- delete ---------------------------------------------------------- */
  const handleDelete = async (doc: WorkspaceDocument) => {
    if (!doc.documentId) return;
    const previous = docs;
    // Optimistic removal with rollback on failure.
    setDocs((prev) => prev.filter((d) => d.key !== doc.key));
    try {
      await uploadService.remove(doc.documentId);
      if (doc.previewUrl?.startsWith("blob:")) URL.revokeObjectURL(doc.previewUrl);
      // Never leave stale session data: clear every answer this document
      // prefilled, then progress / next question recompute everywhere.
      // (The document is already gone — a rollback hiccup must not undo the UI.)
      let cleared = 0;
      try {
        cleared = await rollbackPrefill(doc.documentId);
      } catch {
        /* refresh() on the next page visit re-syncs */
      }
      // Re-merge the unified profile without this document (the backend
      // prunes it and retracts unsupported values automatically).
      if (sessionId) await refreshProfile(sessionId);
      setHistoryKey((k) => k + 1); // history row flips to "deleted"
      toast(`${doc.filename} removed`, {
        description:
          cleared > 0
            ? `${cleared} prefilled answer${cleared === 1 ? "" : "s"} from this document ${cleared === 1 ? "was" : "were"} cleared — progress updated.`
            : undefined,
      });
    } catch (err) {
      setDocs(previous);
      toast.error("Delete failed", { description: toApiError(err).message });
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Upload documents"
        description="Drop the KYC forms and ID documents you already have — Sahayak detects each one, merges them into a single profile, and prefills everything it can verify."
        actions={
          <Button variant="outline" asChild>
            <Link href="/interview">
              Skip to interview <ArrowRight aria-hidden />
            </Link>
          </Button>
        }
      />

      <div className="grid gap-6 lg:grid-cols-5">
        {/* Type selector + dropzone + tips */}
        <div className="space-y-4 lg:col-span-3">
          {/* Phase 13: ONE primary form = the final output of this session. */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">1. Primary form — your final output</CardTitle>
              <CardDescription>
                This is the form Sahayak will fill and generate for you.
                Everything you upload below is evidence used to autofill it.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div
                role="radiogroup"
                aria-label="Primary form"
                className="flex flex-wrap gap-2"
              >
                {PRIMARY_FORMS.map((form) => (
                  <button
                    key={form.value}
                    type="button"
                    role="radio"
                    aria-checked={primaryForm === form.value}
                    onClick={() => void handleSelectPrimaryForm(form.value)}
                    className={cn(
                      "rounded-full border px-3 py-1.5 text-xs font-medium transition-all",
                      primaryForm === form.value
                        ? "border-primary bg-primary/15 text-primary"
                        : "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground",
                    )}
                  >
                    {form.label}
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Supporting documents: pick the type BEFORE dropping the file. */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">
                2. Supporting documents — what are you uploading?
              </CardTitle>
              <CardDescription>
                Upload as many as you like — each is detected, fully extracted,
                and merged into one profile. The type is saved with your history.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div
                role="radiogroup"
                aria-label="Document type"
                className="flex flex-wrap gap-2"
              >
                {DOCUMENT_TYPES.map((type) => (
                  <button
                    key={type.value}
                    type="button"
                    role="radio"
                    aria-checked={documentType === type.value}
                    onClick={() => setDocumentType(type.value)}
                    className={cn(
                      "rounded-full border px-3 py-1.5 text-xs font-medium transition-all",
                      documentType === type.value
                        ? "border-primary bg-primary/15 text-primary"
                        : "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground",
                    )}
                  >
                    {type.label}
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Dimmed until a type is chosen — handleFiles enforces the rule. */}
          <div className={cn(!documentType && "opacity-60")}>
            <UploadCard onFiles={handleFiles} />
          </div>

          <Card>
            <CardContent className="flex gap-3 p-4">
              <Info className="mt-0.5 size-4.5 shrink-0 text-accent" aria-hidden />
              <p className="text-sm text-muted-foreground">
                {documentType
                  ? "Best results: a clear, well-lit scan. Files are processed locally and deleted when your session ends."
                  : "Step 2: choose the supporting-document type above, then drop your file."}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Documents list */}
        <div className="lg:col-span-2">
          <Card className="h-full">
            <CardHeader>
              <CardTitle>Your documents</CardTitle>
              <CardDescription>
                {listState === "ready" && docs.length === 0
                  ? "Nothing uploaded yet."
                  : listState === "ready"
                    ? `${docs.length} document${docs.length > 1 ? "s" : ""} in this session.`
                    : " "}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {listState === "loading" && (
                <div className="space-y-4" aria-label="Loading documents">
                  <SkeletonRow />
                  <SkeletonRow />
                </div>
              )}

              {listState === "error" && (
                <ErrorState
                  title="Couldn't load documents"
                  description={listError}
                  onRetry={retryLoad}
                />
              )}

              {listState === "ready" && docs.length === 0 && (
                <EmptyState
                  title="No documents yet"
                  description="Upload a scan on the left and it will appear here with its OCR status."
                />
              )}

              {listState === "ready" && (
                <AnimatePresence initial={false}>
                  {docs.map((doc) => (
                    <DocumentCard
                      key={doc.key}
                      doc={doc}
                      labelOf={labelOf}
                      onPrefill={(d) => void handlePrefill(d)}
                      onDelete={(d) => void handleDelete(d)}
                      prefillBusy={prefillingKey === doc.key}
                    />
                  ))}
                </AnimatePresence>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Unified KYC profile: merge status, provenance, conflict cards */}
      <ProfilePanel
        profile={profile}
        resolvingId={resolvingId}
        onResolve={(conflict, documentId) => void handleResolve(conflict, documentId)}
      />

      {/* Persistent per-account upload history (Phase 13, signed-in only) */}
      <UploadHistoryPanel refreshKey={historyKey} />
    </div>
  );
}
