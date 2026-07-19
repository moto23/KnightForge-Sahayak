"use client";

import * as React from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, PencilLine, UploadCloud } from "lucide-react";

import { AssetUploadCard } from "@/components/assets/asset-upload-card";
import { PageHeader } from "@/components/shared/page-header";
import { ProgressCard } from "@/components/shared/progress-card";
import { EmptyState, ErrorState, LoadingAnimation } from "@/components/shared/states";
import { StatusBadge, type Status } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAsync } from "@/hooks/use-async";
import { useKycSession } from "@/hooks/use-kyc-session";
import { fadeUp, staggerContainer } from "@/lib/motion";
import { assetsService } from "@/services";
import type { AssetRequirement, KYCField } from "@/types/api";

type FieldRow = {
  field: KYCField;
  status: Status;
  value?: string;
  errorMessage?: string;
};

/**
 * Image fields are in the schema like any other, but a row showing the raw
 * asset id is meaningless. They are pulled out of the normal listing and shown
 * as upload cards instead — and only when the active form requires them.
 */
const ASSET_FIELD_IDS = new Set(["applicant_photo", "applicant_signature"]);

/**
 * Progress Dashboard (Phase 9B.1 — fully integrated).
 * Everything is derived live from the session + schema: answered fields,
 * AI-prefilled provenance, invalid attempts (with the validator's message)
 * and the pending list — grouped by real form sections.
 */
export default function ProgressPage() {
  const { session, progress, schema, prefilledIds, restoring, error, refresh } =
    useKycSession();
  const sessionId = session?.session_id ?? null;

  /**
   * What the active form requires. Empty unless a form asks for an image, and
   * a failure is silent — assets are a conditional extra, so a session with no
   * primary form simply shows nothing rather than an error.
   */
  const assetState = useAsync(
    (signal) =>
      sessionId
        ? assetsService
            .requirements(sessionId, signal)
            .then((r) => r.requirements)
            .catch(() => [] as AssetRequirement[])
        : Promise.resolve([] as AssetRequirement[]),
    [sessionId],
  );

  const onAssetChanged = React.useCallback(async () => {
    assetState.reload();
    await refresh();
  }, [assetState, refresh]);

  const requiredAssets = (assetState.data ?? []).filter((r) => r.required);

  if (restoring) {
    return <LoadingAnimation label="Loading your progress…" className="min-h-[50dvh]" />;
  }

  if (error && !session) {
    return (
      <ErrorState
        title="Couldn't load progress"
        description={error.message}
        onRetry={() => void refresh()}
        className="min-h-[50dvh]"
      />
    );
  }

  if (!session || !progress || !schema) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Progress"
          description="Every field of your form, its source and its validation state — nothing hidden."
        />
        <EmptyState
          title="No interview session yet"
          description="Start by uploading a document for AI prefill, or jump straight into the interview."
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
      </div>
    );
  }

  /* --- derive per-field rows from live data --------------------------- */
  const statusOf = (field: KYCField): FieldRow => {
    const answered = field.id in session.answers;
    const invalidAttempt = session.validation_errors[field.id];
    if (answered) {
      return {
        field,
        status: prefilledIds.has(field.id) ? "prefilled" : "answered",
        value: session.answers[field.id],
      };
    }
    if (invalidAttempt) {
      return {
        field,
        status: "invalid",
        value: invalidAttempt.value ?? undefined,
        errorMessage: invalidAttempt.message,
      };
    }
    return { field, status: "pending" };
  };

  const sections = schema.sections.map((section) => ({
    section,
    rows: section.fields
      .filter((f) => !ASSET_FIELD_IDS.has(f.id))
      .map(statusOf),
  }));

  const allRows = sections.flatMap((s) => s.rows);
  const prefilledCount = allRows.filter((r) => r.status === "prefilled").length;
  const invalidCount = progress.invalid_fields.length;
  const pendingCount = progress.pending_required_fields.length;
  const completed = progress.interview_status === "completed";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Progress"
        description="Every field of your form, its source and its validation state — nothing hidden."
        actions={
          completed ? (
            <Button variant="gradient" asChild>
              <Link href="/preview">
                Generate PDF <ArrowRight aria-hidden />
              </Link>
            </Button>
          ) : (
            <Button variant="gradient" asChild>
              <Link href="/interview">
                Finish remaining <ArrowRight aria-hidden />
              </Link>
            </Button>
          )
        }
      />

      {/* Summary row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <ProgressCard
          title={`Overall completion · ${completed ? "completed" : "in progress"}`}
          percent={progress.progress_percentage}
          answered={progress.completed_required_fields}
          total={progress.required_fields}
          className="sm:col-span-2"
        />
        <Card className="flex flex-col justify-center p-5">
          <p className="text-3xl font-bold tabular-nums text-accent">
            {prefilledCount}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            fields prefilled by AI from your documents
          </p>
        </Card>
        <Card className="flex flex-col justify-center p-5">
          <p className="text-3xl font-bold tabular-nums text-warning">
            {pendingCount + invalidCount}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {invalidCount > 0
              ? `${pendingCount} pending · ${invalidCount} need a fix`
              : "required fields still needing your attention"}
          </p>
        </Card>
      </div>

      {/* Photo / signature — shown ONLY when the active form requires them,
          so a form with no photo box never displays an empty photo slot. */}
      {sessionId && requiredAssets.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle>Photograph &amp; signature</CardTitle>
            <CardDescription>
              Your form has a place for {requiredAssets.length === 2
                ? "both of these"
                : "this"}
              . {requiredAssets.filter((r) => r.provided).length} of{" "}
              {requiredAssets.length} supplied.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
            {requiredAssets.map((requirement) => (
              <AssetUploadCard
                key={requirement.kind}
                sessionId={sessionId}
                requirement={requirement}
                onChanged={onAssetChanged}
              />
            ))}
          </CardContent>
        </Card>
      )}

      {/* Field sections (from the real schema) */}
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="visible"
        className="space-y-4"
      >
        {sections.map(({ section, rows }) => {
          const done = rows.filter(
            (r) => r.status === "answered" || r.status === "prefilled",
          ).length;
          return (
            <motion.div key={section.id} variants={fadeUp}>
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle>{section.title}</CardTitle>
                  <CardDescription>
                    {done} of {rows.length} complete
                    {section.description ? ` — ${section.description}` : ""}
                  </CardDescription>
                </CardHeader>
                <CardContent className="divide-y divide-border">
                  {rows.map(({ field, status, value, errorMessage }) => (
                    <div
                      key={field.id}
                      className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 py-3 first:pt-0 last:pb-0"
                    >
                      <div className="min-w-0 flex-1 basis-48">
                        <p className="flex items-center gap-1.5 text-sm font-medium">
                          {field.display_name}
                          {field.required && (
                            <span className="text-destructive" aria-label="required">
                              *
                            </span>
                          )}
                        </p>
                        {value && (
                          <p className="truncate font-mono text-xs text-muted-foreground">
                            {value}
                          </p>
                        )}
                        {errorMessage && (
                          <p className="text-xs text-destructive">{errorMessage}</p>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <StatusBadge status={status} />
                        {(status === "pending" || status === "invalid") && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-8"
                            aria-label={`Answer ${field.display_name} in the interview`}
                            asChild
                          >
                            <Link href="/interview">
                              <PencilLine className="size-4" />
                            </Link>
                          </Button>
                        )}
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </motion.div>
          );
        })}
      </motion.div>
    </div>
  );
}
