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
import {
  PRIMARY_FORMS,
  SUPPORTING_DOCUMENT_HINTS,
} from "@/components/upload/document-types";
import { ProfilePanel } from "@/components/upload/profile-panel";
import { TemplateLibrary } from "@/components/upload/template-library";
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
  const [historyKey, setHistoryKey] = React.useState(0);
  // Phase 13: ONE primary form is the final output; documents are evidence.
  const [primaryForm, setPrimaryForm] = React.useState<string>(PRIMARY_FORMS[0].value);
  // Last primary-form id the backend has confirmed for this session.
  const syncedFormRef = React.useRef<string | null>(null);
  // Latest profile snapshot, readable by the document-list load regardless of
  // which of the two concurrent requests resolves first.
  const profileRef = React.useRef<UnifiedProfileResponse | null>(null);

  const labelOf = React.useCallback(
    (fieldId: string) => fieldMap.get(fieldId)?.display_name ?? fieldId,
    [fieldMap],
  );

  /**
   * The primary form file, if one was attached (at most one by construction).
   * A REJECTED file does not count — it was never accepted as the primary
   * form, so the dropzone must stay open for the user to try the right one.
   */
  const primaryDoc = docs.find((d) => d.isPrimary && d.phase !== "rejected") ?? null;

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
    // Scoped to THIS session: an unscoped list pulls in documents from
    // earlier workflows, which is how a stale bank statement appeared
    // beside a freshly selected PAN + Aadhaar.
    if (!sessionId) return [];
    const { documents } = await uploadService.list(sessionId);
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
          // Fetched lazily below with the auth header — a raw URL in an
          // <img src> is an anonymous request and 404s for owned files.
          previewUrl: null,
        };
      }),
    );
  }, [sessionId]);

  /* --- unified profile (Phase 11) -------------------------------------- */

  /** Store a profile snapshot and restore doc-type badges from it. */
  const applyProfileSnapshot = React.useCallback(
    (snapshot: UnifiedProfileResponse) => {
      setProfile(snapshot);
      // Also kept in a ref: the profile can now land BEFORE the document
      // list, and a snapshot that arrives first would otherwise patch an
      // empty list and lose every doc-type badge.
      profileRef.current = snapshot;
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

  /**
   * Re-fetch the merged profile — the authoritative recompute. Returns the
   * snapshot so callers (delete) can act on what survived.
   */
  const refreshProfile = React.useCallback(
    async (sid: string): Promise<UnifiedProfileResponse | null> => {
      try {
        const snapshot = await intelligenceService.profile(sid);
        applyProfileSnapshot(snapshot);
        return snapshot;
      } catch {
        /* profile is progressive enhancement — the list keeps working */
        return null;
      }
    },
    [applyProfileSnapshot],
  );

  /*
   * The merged profile depends only on the session id, never on the document
   * list — but waiting for listState === "ready" chained it behind the list
   * AND every per-document understanding fetch, so the doc-type badges landed
   * two round trips late. It now starts as soon as a session exists.
   *
   * Ordering is no longer guaranteed, so both directions are covered: the
   * snapshot is kept in a ref for docs that arrive after it (see
   * fetchExisting's consumer), while applyProfileSnapshot still patches docs
   * that arrived before it.
   */
  React.useEffect(() => {
    if (!sessionId) return;
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
  }, [sessionId, applyProfileSnapshot]);

  React.useEffect(() => {
    let cancelled = false;
    fetchExisting()
      .then((restored) => {
        if (cancelled) return;
        // Apply any profile snapshot that won the race (see the profile
        // effect) so badges survive either arrival order.
        const snapshot = profileRef.current;
        setDocs(
          snapshot
            ? restored.map((d) => {
                const summary = snapshot.documents.find(
                  (doc) => doc.document_id === d.documentId,
                );
                return summary ? { ...d, docType: summary.document_type } : d;
              })
            : restored,
        );
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

  /** Shape/size gate shared by both dropzones. */
  const isUploadable = (file: File) => {
    if (!ALLOWED_TYPES.includes(file.type)) {
      toast.error(`${file.name}: unsupported type`, {
        description: "Please upload a PDF, PNG or JPG.",
      });
      return false;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      toast.error(`${file.name}: too large`, {
        description: "Maximum file size is 10 MB.",
      });
      return false;
    }
    return true;
  };

  /**
   * Supporting documents: one OR many at once, with no type to choose —
   * the backend classifies each file independently. Each runs its own
   * pipeline, so a failure on one never blocks the others.
   */
  const handleFiles = (files: File[]) => {
    for (const file of files.filter(isUploadable)) {
      void processFile(file, "other"); // placeholder; the classifier decides
    }
  };

  /**
   * The primary form itself (blank, partly filled or filled) — at most ONE
   * file, and never gated on a supporting-document type: uploading only your
   * primary form is a complete, valid workflow on its own.
   */
  const handlePrimaryFile = (files: File[]) => {
    const [file, ...rest] = files;
    if (!file) return;
    if (rest.length > 0) {
      toast.warning("Only one primary form", {
        description: `Using ${file.name}. Add the rest as supporting documents.`,
      });
    }
    if (!isUploadable(file)) return;
    void processFile(file, "kyc_form", { primary: true });
  };

  const processFile = async (
    file: File,
    selectedType: UploadDocumentType,
    options: { primary?: boolean } = {},
  ) => {
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
        isPrimary: options.primary === true,
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
      // Keep the LOCAL object URL from the file the user just chose: it is
      // already correct, costs no round trip, and needs no auth header.
      patchDoc(key, { documentId, phase: "processing" });
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
      const result = await intelligenceService.process(
        documentId,
        sid,
        options.primary === true,
      );
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
    } catch (err) {
      const apiError = toApiError(err);
      // The backend judges the SLOT by document content, not by filename. A
      // PAN card dropped into the primary box (or a real KYC form dropped into
      // supporting) is refused before it can activate or merge — so the file
      // is discarded here rather than left sitting in a slot it doesn't
      // belong to. Per-file: other uploads in the same batch are unaffected.
      if (
        apiError.code === "not_a_primary_form" ||
        apiError.code === "primary_form_in_supporting_slot"
      ) {
        // The backend document is deleted straight away — a rejected file is
        // not part of this session. The card then keeps its explanation but
        // MUST forget the document id: leaving it set made the card's Delete
        // button call DELETE /upload/{id} on a document that no longer exists,
        // which failed with "Document '<id>' was not found." From here on the
        // card is purely local and its action is a dismiss.
        let serverCopyRemoved = true;
        try {
          await uploadService.remove(documentId);
        } catch {
          // Already gone, or the call failed. Either way the id is no longer
          // safe to delete again; the card stays dismissible locally.
          serverCopyRemoved = false;
        }
        patchDoc(key, {
          phase: "rejected",
          documentId: null,
          previewUrl: null,
          errorMessage: apiError.message,
          serverCopyRemoved,
        });
        setHistoryKey((k) => k + 1);
        toast.error(`${file.name} wasn't accepted here`, {
          description: apiError.message,
        });
      }
      /* anything else: intelligence is progressive enhancement — manual
         prefill still works, so the document stays as analyzed */
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
    // A rejected card has no backend document (it was removed the moment it
    // was refused), so "delete" here is a local dismiss. Calling the API would
    // 404 on an id that is deliberately gone.
    if (doc.phase === "rejected" || !doc.documentId) {
      setDocs((prev) => prev.filter((d) => d.key !== doc.key));
      if (doc.previewUrl?.startsWith("blob:")) URL.revokeObjectURL(doc.previewUrl);
      return;
    }
    const previous = docs;
    // Optimistic removal with rollback on failure.
    setDocs((prev) => prev.filter((d) => d.key !== doc.key));
    try {
      await uploadService.remove(doc.documentId);
      if (doc.previewUrl?.startsWith("blob:")) URL.revokeObjectURL(doc.previewUrl);

      // ONE authoritative recomputation, in this order:
      //   1. the backend re-derives the whole profile from the REMAINING
      //      evidence — pruning this document, re-merging, re-resolving
      //      conflicts, and retracting only values it still owns and that
      //      nothing else supports;
      //   2. whatever it still reports as applied is protected;
      //   3. the legacy rollback then sweeps only unowned leftovers.
      // Doing it the other way round deleted values by field name and lost
      // ones a second document still supported.
      let cleared = 0;
      let stillApplied: string[] = [];
      try {
        if (sessionId) {
          const snapshot = await refreshProfile(sessionId);
          stillApplied = snapshot?.applied_field_ids ?? [];
        }
      } catch {
        /* refresh() on the next page visit re-syncs */
      }
      try {
        cleared = await rollbackPrefill(doc.documentId, stillApplied);
      } catch {
        /* refresh() on the next page visit re-syncs */
      }
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
          <>
            {/* Blank supported forms, for users who don't have one to hand.
                Kept in the header beside "Skip to interview" so the journey
                reads: get a form -> upload it -> add documents -> generate. */}
            <TemplateLibrary />
            <Button variant="outline" asChild>
              <Link href="/interview">
                Skip to interview <ArrowRight aria-hidden />
              </Link>
            </Button>
          </>
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

              {/* Optional: upload the form itself (blank, part-filled or
                  filled). At most one — and never gated on a supporting
                  type, so "primary form only" is a valid workflow. */}
              <div className="mt-4 border-t border-border pt-4">
                <p className="mb-2 text-xs text-muted-foreground">
                  {primaryDoc
                    ? `Attached: ${primaryDoc.filename} — any values already on it are extracted and prefilled.`
                    : "Optional: attach your copy of this form (blank, partly filled or filled). Anything already filled in is read and prefilled."}
                </p>
                {!primaryDoc && (
                  // Points at the header dropdown: without this the template
                  // library is only discoverable by chance.
                  <p className="mb-2 text-xs text-muted-foreground">
                    Don&apos;t have the form? Grab a blank one from{" "}
                    <span className="font-medium text-foreground">
                      KYC form templates
                    </span>{" "}
                    at the top of this page.
                  </p>
                )}
                {!primaryDoc && (
                  <UploadCard
                    onFiles={handlePrimaryFile}
                    className="min-h-32 sm:min-h-36"
                  />
                )}
              </div>
            </CardContent>
          </Card>

          {/* Supporting documents: no type picker — the classifier decides. */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">2. Supporting documents</CardTitle>
              <CardDescription>
                Upload one or multiple supporting documents. Sahayak
                automatically detects each document type, extracts its fields,
                and merges verified information into your profile.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {/* Informational only — NOT selectable. Backend auto-detection
                  stays authoritative, so these just answer "what can I put
                  here?" without implying a choice that would be ignored. */}
              <ul
                className="flex flex-wrap gap-1.5"
                aria-label="Document types Sahayak detects automatically"
              >
                {SUPPORTING_DOCUMENT_HINTS.map((hint) => (
                  <li
                    key={hint}
                    className="rounded-full border border-border bg-muted/40 px-2.5 py-1 text-xs text-muted-foreground"
                  >
                    {hint}
                  </li>
                ))}
              </ul>
              <UploadCard onFiles={handleFiles} />
            </CardContent>
          </Card>

          <Card>
            <CardContent className="flex gap-3 p-4">
              <Info className="mt-0.5 size-4.5 shrink-0 text-accent" aria-hidden />
              <p className="text-sm text-muted-foreground">
                Best results: a clear, well-lit scan. Your files stay on your
                Sahayak backend — you can delete any of them at any time.
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
