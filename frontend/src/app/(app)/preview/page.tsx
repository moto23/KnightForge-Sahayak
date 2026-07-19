"use client";

import * as React from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowRight,
  Download,
  Pencil,
  FileCheck2,
  FileText,
  ListTodo,
  Sparkles,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { Celebration } from "@/components/shared/celebration";
import { PageHeader } from "@/components/shared/page-header";
import {
  EmptyState,
  ErrorState,
  LoadingAnimation,
  SuccessState,
} from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { SkeletonRow } from "@/components/ui/skeleton";
import { useAsync } from "@/hooks/use-async";
import { useKycSession } from "@/hooks/use-kyc-session";
import { downloadProtectedFile, toApiError } from "@/services/api-client";
import { pdfService } from "@/services";
import type { GeneratedPdfResponse } from "@/types/api";
import { formatBytes, formatDateTime } from "@/utils/format";

/**
 * PDF Preview (Phase 9B.1 — fully integrated).
 * Generate from the live session (409 → missing-fields gate), browse the
 * generated history, download the real file, delete with confirmation.
 */
export default function PreviewPage() {
  const { sessionId, progress, fieldMap, restoring } = useKycSession();

  // Pass the session so the backend can mark which record (if any) still
  // matches the CURRENT answers — the rest are immutable history.
  const pdfList = useAsync(
    (signal) => pdfService.list(sessionId, signal),
    [sessionId],
  );
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [lastGenerated, setLastGenerated] =
    React.useState<GeneratedPdfResponse | null>(null);
  const [generating, setGenerating] = React.useState(false);
  const [missingFields, setMissingFields] = React.useState<string[] | null>(null);
  const [celebrating, setCelebrating] = React.useState(false);

  // Selection is DERIVED (no state-sync effect): explicit choice if it still
  // exists, else the just-generated PDF, else the newest in the list.
  const pdfs = React.useMemo(() => pdfList.data ?? [], [pdfList.data]);
  const selected = React.useMemo<GeneratedPdfResponse | null>(() => {
    if (selectedId) {
      const fromList = pdfs.find((p) => p.pdf_id === selectedId);
      if (fromList) return fromList;
      if (lastGenerated?.pdf_id === selectedId) return lastGenerated;
    }
    return pdfs[0] ?? null;
  }, [pdfs, selectedId, lastGenerated]);

  const completed = progress?.interview_status === "completed";

  /* --- one-time completion celebration ---------------------------------- */

  /**
   * Which generated PDFs have already been celebrated, keyed by pdf_id.
   *
   * sessionStorage (not state) because the requirement is "once per newly
   * completed PDF", and state alone would replay the celebration on every
   * refresh or revisit. Each generation mints a fresh pdf_id, so a genuine new
   * version celebrates again while re-viewing an old one never does.
   *
   * Note this is only reached from the `generate()` success path — arriving at
   * /preview directly, or simply having an old PDF in history, never triggers
   * it, because no new pdf_id was produced.
   */
  const CELEBRATED_KEY = "sahayak:celebrated-pdfs";

  const alreadyCelebrated = (pdfId: string): boolean => {
    try {
      const raw = sessionStorage.getItem(CELEBRATED_KEY);
      return raw ? (JSON.parse(raw) as string[]).includes(pdfId) : false;
    } catch {
      return false; // storage blocked/full — degrade to celebrating
    }
  };

  const markCelebrated = (pdfId: string) => {
    try {
      const raw = sessionStorage.getItem(CELEBRATED_KEY);
      const seen = raw ? (JSON.parse(raw) as string[]) : [];
      sessionStorage.setItem(
        CELEBRATED_KEY,
        // Bounded: only the recent ids matter, and this must never grow
        // without limit in a long session.
        JSON.stringify([...seen, pdfId].slice(-20)),
      );
    } catch {
      /* non-fatal — worst case the celebration repeats once */
    }
  };

  /* --- generate -------------------------------------------------------- */
  const generate = async () => {
    if (!sessionId) {
      toast.error("No interview session yet", {
        description: "Complete the interview before generating the PDF.",
      });
      return;
    }
    setGenerating(true);
    setMissingFields(null);
    try {
      const result = await pdfService.generate(sessionId);
      toast.success("PDF generated", {
        description: `${result.pdf.fields_filled} fields placed onto your form.`,
      });
      pdfList.reload();
      setLastGenerated(result.pdf);
      setSelectedId(result.pdf.pdf_id);
      // Celebrate only a GENUINELY new, complete result. The backend already
      // refuses to generate an incomplete session (409, including any required
      // photo/signature), so reaching here means every requirement was met.
      if (!alreadyCelebrated(result.pdf.pdf_id)) {
        markCelebrated(result.pdf.pdf_id);
        setCelebrating(true);
      }
    } catch (err) {
      const apiError = toApiError(err);
      if (apiError.status === 409) {
        // interview_incomplete — extract the field ids from the message.
        const listPart = apiError.message.split(":").pop() ?? "";
        const ids = listPart
          .split(",")
          .map((s) => s.trim().replace(/\.$/, ""))
          .filter((s) => s.length > 0);
        setMissingFields(ids);
        toast.error("Interview not complete yet", {
          description: `${ids.length || "Some"} required fields are still missing.`,
        });
      } else {
        toast.error("Generation failed", { description: apiError.message });
      }
    } finally {
      setGenerating(false);
    }
  };

  /* --- delete ---------------------------------------------------------- */
  const deletePdf = async (pdf: GeneratedPdfResponse) => {
    try {
      await pdfService.remove(pdf.pdf_id);
      toast(`PDF ${pdf.pdf_id.slice(0, 8)} deleted`);
      pdfList.reload();
    } catch (err) {
      toast.error("Delete failed", { description: toApiError(err).message });
    }
  };

  if (restoring) {
    return <LoadingAnimation label="Loading…" className="min-h-[50dvh]" />;
  }

  /** Any version generated yet? Drives "Generate" vs "Save new version". */
  const hasAnyPdf = (pdfList.data?.length ?? 0) > 0 || lastGenerated !== null;

  const metadata: { label: string; value: string }[] = selected
    ? [
        { label: "Template", value: `${selected.template_id} v${selected.template_version}` },
        { label: "Pages", value: String(selected.page_count) },
        { label: "File size", value: formatBytes(selected.file_size) },
        { label: "Fields filled", value: String(selected.fields_filled) },
        { label: "Generated", value: formatDateTime(selected.generated_at) },
        { label: "Session", value: selected.generated_by_session.slice(0, 8) + "…" },
      ]
    : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="PDF Preview"
        description="Your validated answers, placed onto your own uploaded form — generate, review and download."
        actions={
          <>
            <Button
              variant="gradient"
              onClick={() => void generate()}
              loading={generating}
              disabled={!sessionId}
            >
              {generating ? (
                "Generating…"
              ) : (
                <>
                  <Sparkles aria-hidden />
                  {/* Regenerating never overwrites: it adds a new version
                      and the previous one stays in history. */}
                  {hasAnyPdf ? "Save new version" : "Generate PDF"}
                </>
              )}
            </Button>
            <Button variant="outline" asChild>
              <Link href="/progress">
                <Pencil aria-hidden /> Edit answers
              </Link>
            </Button>
            {selected && (
              <Button variant="outline"
                  onClick={() =>
                    void downloadProtectedFile(
                      selected.download_url,
                      `kyc-filled-${selected.pdf_id.slice(0, 8)}.pdf`,
                    ).catch((err) =>
                      toast.error("Couldn't download the PDF", {
                        description: toApiError(err).message,
                      }),
                    )
                  }
                >
                  <Download aria-hidden /> Download
                </Button>
            )}
          </>
        }
      />

      <Celebration
        show={celebrating}
        message="🎉 Your completed KYC form is ready to review."
        onDismiss={() => setCelebrating(false)}
      />

      {/* Incomplete gate (409) */}
      {missingFields && (
        <Card className="border-warning/40 bg-warning/5">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <ListTodo className="size-4.5 text-warning" aria-hidden />
              {missingFields.length} required field{missingFields.length === 1 ? " is" : "s are"} still missing
            </CardTitle>
            <CardDescription>
              The PDF is only generated from complete, validated sessions.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-2">
            {missingFields.slice(0, 8).map((id) => (
              <span
                key={id}
                className="rounded-full border border-border bg-card px-2.5 py-1 text-xs"
              >
                {fieldMap.get(id)?.display_name ?? id}
              </span>
            ))}
            {missingFields.length > 8 && (
              <span className="text-xs text-muted-foreground">
                +{missingFields.length - 8} more
              </span>
            )}
            <Button size="sm" variant="gradient" className="ml-auto" asChild>
              <Link href="/interview">
                Finish the interview <ArrowRight aria-hidden />
              </Link>
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Preview / status panel */}
        <Card className="lg:col-span-2">
          <CardContent className="p-4 sm:p-6">
            {generating ? (
              <LoadingAnimation
                label="Placing your answers onto the official form…"
                className="min-h-[24rem]"
              />
            ) : selected ? (
              <motion.div
                key={selected.pdf_id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35 }}
                className="mx-auto flex aspect-[1/1.2] w-full max-w-xl flex-col items-center justify-center gap-5 rounded-lg border border-border bg-gradient-to-b from-card to-muted/40 p-8 text-center"
              >
                <span className="grid size-20 place-items-center rounded-2xl bg-success/10 text-success glow-primary">
                  <FileCheck2 className="size-10" aria-hidden />
                </span>
                <div className="space-y-1.5">
                  <p className="text-lg font-semibold">
                    kyc-filled-{selected.pdf_id.slice(0, 8)}.pdf
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {selected.page_count} pages · {formatBytes(selected.file_size)} ·{" "}
                    {selected.fields_filled} fields placed on your form
                  </p>
                  <p className="text-xs text-muted-foreground">
                    The original template layout, fonts and legal text are untouched —
                    only your validated answers were added.
                  </p>
                  {!selected.is_current && (
                    // The file itself is never rewritten — it stays valid
                    // history. It just no longer reflects this session.
                    <p
                      className="flex items-center justify-center gap-1.5 text-xs text-warning"
                      role="status"
                    >
                      <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
                      Your answers or documents changed since this was made —
                      regenerate for an up-to-date form.
                    </p>
                  )}
                </div>
                <Button variant="gradient" size="lg"
                  onClick={() =>
                    void downloadProtectedFile(
                      selected.download_url,
                      `kyc-filled-${selected.pdf_id.slice(0, 8)}.pdf`,
                    ).catch((err) =>
                      toast.error("Couldn't download the PDF", {
                        description: toApiError(err).message,
                      }),
                    )
                  }
                >
                    <Download aria-hidden /> Download PDF
                </Button>
              </motion.div>
            ) : completed ? (
              <SuccessState
                title="Ready to generate"
                description="All required fields are validated. Click “Generate PDF” to fill the official form."
                className="min-h-[24rem]"
              />
            ) : (
              <EmptyState
                title="No PDF yet"
                description={
                  sessionId
                    ? "Finish the interview first — then your filled form is one click away."
                    : "Upload a document or start the interview to begin your KYC."
                }
                action={
                  <Button variant="outline" asChild>
                    <Link href={sessionId ? "/interview" : "/upload"}>
                      {sessionId ? "Continue interview" : "Get started"}{" "}
                      <ArrowRight aria-hidden />
                    </Link>
                  </Button>
                }
                className="min-h-[24rem]"
              />
            )}
          </CardContent>
        </Card>

        {/* Metadata + history */}
        <div className="space-y-4">
          {selected && (
            <Card>
              <CardHeader className="flex-row items-center gap-3 space-y-0">
                <span className="grid size-10 place-items-center rounded-lg bg-primary/15 text-primary">
                  <FileText className="size-5" aria-hidden />
                </span>
                <div>
                  <CardTitle className="text-sm">Document details</CardTitle>
                  <CardDescription>Generated metadata</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                <dl className="divide-y divide-border">
                  {metadata.map((row) => (
                    <div key={row.label} className="flex justify-between gap-4 py-2.5 text-sm">
                      <dt className="text-muted-foreground">{row.label}</dt>
                      <dd className="text-right font-medium">{row.value}</dd>
                    </div>
                  ))}
                </dl>

                <Dialog>
                  <DialogTrigger asChild>
                    <Button variant="destructive" className="mt-4 w-full">
                      <Trash2 aria-hidden /> Delete this PDF
                    </Button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>Delete generated PDF?</DialogTitle>
                      <DialogDescription>
                        This removes the file and its metadata from the server.
                        Your answers stay — you can regenerate anytime.
                      </DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                      <DialogClose asChild>
                        <Button variant="outline">Cancel</Button>
                      </DialogClose>
                      <DialogClose asChild>
                        <Button
                          variant="destructive"
                          onClick={() => void deletePdf(selected)}
                        >
                          Delete
                        </Button>
                      </DialogClose>
                    </DialogFooter>
                  </DialogContent>
                </Dialog>
              </CardContent>
            </Card>
          )}

          {/* History */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Generated history</CardTitle>
              <CardDescription>
                {pdfs.length === 0 ? "Nothing generated yet." : `${pdfs.length} PDF${pdfs.length > 1 ? "s" : ""}, newest first.`}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {pdfList.loading && (
                <div className="space-y-3">
                  <SkeletonRow />
                  <SkeletonRow />
                </div>
              )}
              {pdfList.error && (
                <ErrorState
                  title="Couldn't load history"
                  description={pdfList.error.message}
                  onRetry={pdfList.reload}
                />
              )}
              {!pdfList.loading &&
                !pdfList.error &&
                pdfs.map((pdf) => {
                  const isActive = selected?.pdf_id === pdf.pdf_id;
                  return (
                    <button
                      key={pdf.pdf_id}
                      type="button"
                      onClick={() => setSelectedId(pdf.pdf_id)}
                      aria-pressed={isActive}
                      className={
                        "flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors " +
                        (isActive
                          ? "border-primary/60 bg-primary/5"
                          : "border-border hover:bg-muted/40")
                      }
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">
                          kyc-filled-{pdf.pdf_id.slice(0, 8)}.pdf
                        </span>
                        <span className="block text-xs text-muted-foreground">
                          {formatDateTime(pdf.generated_at)} · {formatBytes(pdf.file_size)}
                        </span>
                      </span>
                      <FileText
                        className={
                          "size-4 shrink-0 " +
                          (isActive ? "text-primary" : "text-muted-foreground")
                        }
                        aria-hidden
                      />
                    </button>
                  );
                })}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
