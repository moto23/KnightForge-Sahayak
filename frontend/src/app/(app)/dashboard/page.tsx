"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import {
  ArrowRight,
  FileText,
  MessageSquareText,
  RotateCcw,
  UploadCloud,
} from "lucide-react";
import { toast } from "sonner";

import { PageHeader } from "@/components/shared/page-header";
import { ProgressCard } from "@/components/shared/progress-card";
import { EmptyState, LoadingAnimation } from "@/components/shared/states";
import { Stepper } from "@/components/shared/stepper";
import { Timeline, type TimelineItem } from "@/components/shared/timeline";
import { UploadHistoryPanel } from "@/components/upload/upload-history-panel";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  GlassCard,
} from "@/components/ui/card";
import { useAsync } from "@/hooks/use-async";
import { useKycSession } from "@/hooks/use-kyc-session";
import { WORKFLOW_STEPS } from "@/lib/navigation";
import { fadeUp, staggerContainer } from "@/lib/motion";
import { absoluteUrl } from "@/services/api-client";
import { healthService, pdfService, uploadService } from "@/services";

/**
 * Dashboard (Phase 9B.1 — fully integrated).
 * Live session summary, workflow position, recent activity derived from the
 * real session state, and a backend health indicator.
 */
export default function DashboardPage() {
  const {
    session,
    progress,
    schema,
    fieldMap,
    prefilledIds,
    restoring,
    resetSession,
  } = useKycSession();

  const health = useAsync((signal) => healthService.check(signal), []);
  // Phase 13 resume inputs: what exists already (uploads / generated PDFs)?
  const uploads = useAsync(() => uploadService.list(), []);
  const pdfs = useAsync(
    (signal) => pdfService.list(session?.session_id ?? null, signal),
    [session?.session_id],
  );

  if (restoring) {
    return <LoadingAnimation label="Loading your workspace…" className="min-h-[50dvh]" />;
  }

  const backendOnline = !health.loading && !health.error;
  const completed = progress?.interview_status === "completed";

  /* ------------------------------------------------------------------ *
   * Resume logic (Phase 13): from the live workflow state, decide the ONE
   * next action. Checked from the end of the pipeline backwards:
   * PDF ready → download · interview complete → generate · answers exist
   * (valid or invalid) → continue/fix · docs uploaded but nothing applied
   * → run OCR/prefill · nothing at all → upload.
   * ------------------------------------------------------------------ */
  const uploadCount = uploads.data?.total ?? 0;
  // Only THIS session's PDF counts as "done" — someone else's generated file
  // (or a stale one from a previous run) must not short-circuit the flow.
  const sessionPdf =
    (session &&
      pdfs.data?.find((p) => p.generated_by_session === session.session_id)) ||
    null;
  const invalidCount = session
    ? Object.keys(session.validation_errors).filter(
        (fieldId) => !(fieldId in session.answers),
      ).length
    : 0;
  const answeredCount = session?.completed_fields.length ?? 0;

  const resume: {
    label: string;
    href: string;
    description: string;
    external?: boolean;
  } = sessionPdf && completed
    ? {
        label: "Download PDF",
        href: absoluteUrl(sessionPdf.download_url),
        description: "Your filled KYC form is ready.",
        external: true,
      }
    : completed
      ? {
          label: "Generate PDF",
          href: "/preview",
          description: "All required fields are complete — one click left.",
        }
      : invalidCount > 0
        ? {
            label: "Fix & validate",
            href: "/interview",
            description: `${invalidCount} field${invalidCount === 1 ? "" : "s"} need${invalidCount === 1 ? "s" : ""} a correction.`,
          }
        : answeredCount > 0
          ? {
              label: "Continue interview",
              href: "/interview",
              description: progress
                ? `${progress.pending_required_fields.length} required field${progress.pending_required_fields.length === 1 ? "" : "s"} left.`
                : "Pick up where you left off.",
            }
          : uploadCount > 0
            ? {
                label: "Continue OCR",
                href: "/upload",
                description: "Your documents are uploaded — extract and prefill from them.",
              }
            : {
                label: "Upload document",
                href: "/upload",
                description: "Start by uploading a KYC form or ID document.",
              };

  /* Workflow position: no session → step 0; answering → 2; done → 4. */
  const activeStep = !session
    ? 0
    : completed
      ? 4
      : prefilledIds.size > 0 || session.completed_fields.length > 0
        ? 2
        : 1;

  /* Recent activity from the live session (answer order, newest last). */
  const activity: TimelineItem[] = [];
  if (session) {
    for (const fieldId of session.completed_fields.slice(-4)) {
      const prefilledByAi = prefilledIds.has(fieldId);
      activity.push({
        id: `done-${fieldId}`,
        title: `${fieldMap.get(fieldId)?.display_name ?? fieldId} ${prefilledByAi ? "prefilled from your document" : "answered"}`,
        description: session.answers[fieldId],
        tone: prefilledByAi ? "accent" : "success",
      });
    }
    for (const [fieldId, attempt] of Object.entries(session.validation_errors)) {
      if (fieldId in session.answers) continue;
      activity.push({
        id: `invalid-${fieldId}`,
        title: `${fieldMap.get(fieldId)?.display_name ?? fieldId} needs a fix`,
        description: attempt.message,
        tone: "warning",
      });
    }
  }

  const quickActions = [
    {
      title: "Upload a document",
      description: "Let OCR prefill your form in seconds",
      href: "/upload",
      icon: UploadCloud,
    },
    {
      title: completed ? "Review the interview" : "Continue the interview",
      description: progress
        ? completed
          ? "All required fields are complete"
          : `${progress.pending_required_fields.length} required fields still need answers`
        : "Answer friendly questions one at a time",
      href: "/interview",
      icon: MessageSquareText,
    },
    {
      title: completed ? "Generate your PDF" : "PDF Preview",
      description: completed
        ? "Your filled form is one click away"
        : "See the filled form once complete",
      href: "/preview",
      icon: FileText,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Welcome back 👋"
        description={
          session
            ? completed
              ? "Your KYC is complete — generate and download the filled form."
              : "Your KYC is underway. Pick up where you left off."
            : "Start your KYC — upload your form and supporting documents, or jump straight into the AI-Guided Completion."
        }
        actions={
          <div className="flex items-center gap-2">
            <span
              className={
                "hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs sm:flex " +
                (backendOnline
                  ? "border-success/30 text-success"
                  : "border-destructive/30 text-destructive")
              }
              role="status"
            >
              <span
                className={
                  "size-1.5 rounded-full " +
                  (backendOnline ? "bg-success" : "bg-destructive animate-pulse-glow")
                }
                aria-hidden
              />
              {health.loading ? "Checking backend…" : backendOnline ? "Backend online" : "Backend offline"}
            </span>
            <Button variant="gradient" asChild>
              {resume.external ? (
                <a href={resume.href} title={resume.description}>
                  {resume.label} <ArrowRight aria-hidden />
                </a>
              ) : (
                <Link href={resume.href} title={resume.description}>
                  {resume.label} <ArrowRight aria-hidden />
                </Link>
              )}
            </Button>
          </div>
        }
      />

      {/* Workflow position */}
      <GlassCard className="p-5 sm:p-6">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-semibold">
            {schema?.title ?? "Your KYC form"}
          </p>
          <StatusBadge
            status={
              !session ? "pending" : completed ? "completed" : "in_progress"
            }
          />
        </div>
        <Stepper steps={WORKFLOW_STEPS} activeIndex={activeStep} />
        <p className="mt-4 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Next step:</span>{" "}
          {resume.label} — {resume.description}
        </p>
      </GlassCard>

      {!session ? (
        <EmptyState
          title="No active session"
          description="Upload a KYC scan for instant AI prefill, or answer everything conversationally — your progress is saved as you go."
          action={
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button variant="gradient" asChild>
                <Link href="/upload">
                  <UploadCloud aria-hidden /> Upload a document
                </Link>
              </Button>
              <Button variant="outline" asChild>
                <Link href="/interview">Start the interview</Link>
              </Button>
            </div>
          }
        />
      ) : (
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
          className="grid gap-4 lg:grid-cols-3"
        >
          {/* Progress summary */}
          <motion.div variants={fadeUp} className="lg:col-span-1">
            <ProgressCard
              title="Form completion"
              percent={progress?.progress_percentage ?? session.progress_percentage}
              answered={progress?.completed_required_fields ?? session.completed_fields.length}
              // Required-field counts vary per form — never assume a fixed
              // number; fall back to what the session itself reports.
              total={progress?.required_fields ?? session.completed_fields.length}
              className="h-full"
            />
          </motion.div>

          {/* Quick actions */}
          <motion.div variants={fadeUp} className="lg:col-span-2">
            <Card className="h-full">
              <CardHeader>
                <CardTitle>Quick actions</CardTitle>
                <CardDescription>Jump straight to the next step.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3 sm:grid-cols-3">
                {quickActions.map((action) => (
                  <Link
                    key={action.href}
                    href={action.href}
                    className="group flex flex-col gap-3 rounded-xl border border-border p-4 transition-all hover:-translate-y-0.5 hover:border-primary/50 hover:bg-muted/40"
                  >
                    <span className="grid size-10 place-items-center rounded-lg bg-gradient-to-br from-primary/15 to-accent/15 text-primary transition-transform group-hover:scale-110">
                      <action.icon className="size-5" aria-hidden />
                    </span>
                    <span>
                      <span className="block text-sm font-medium">{action.title}</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {action.description}
                      </span>
                    </span>
                  </Link>
                ))}
              </CardContent>
            </Card>
          </motion.div>

          {/* Recent activity */}
          <motion.div variants={fadeUp} className="lg:col-span-3">
            <Card>
              <CardHeader className="flex-row items-start justify-between space-y-0">
                <div className="space-y-1.5">
                  <CardTitle>Recent activity</CardTitle>
                  <CardDescription>
                    Derived live from your session — {session.completed_fields.length} fields answered so far.
                  </CardDescription>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground"
                  onClick={() => {
                    void resetSession().then(() =>
                      toast("Session cleared", {
                        description: "You can start a fresh KYC anytime.",
                      }),
                    );
                  }}
                >
                  <RotateCcw aria-hidden /> Start over
                </Button>
              </CardHeader>
              <CardContent>
                {activity.length > 0 ? (
                  <Timeline items={activity} />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    No answers yet — upload a document or start the interview.
                  </p>
                )}
              </CardContent>
            </Card>
          </motion.div>
        </motion.div>
      )}

      {/* Persistent upload history (Phase 13, signed-in accounts only) */}
      <UploadHistoryPanel
        limit={5}
        description="Your five most recent uploads — the full list lives on the Upload page."
      />
    </div>
  );
}
