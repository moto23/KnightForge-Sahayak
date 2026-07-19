"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, HelpCircle, RotateCcw, Send, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { AssetUploadCard } from "@/components/assets/asset-upload-card";
import { ChatBubble, TypingIndicator } from "@/components/shared/chat-bubble";
import { ErrorState, LoadingAnimation, SuccessState } from "@/components/shared/states";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { useAsync } from "@/hooks/use-async";
import { useBackendStatus } from "@/hooks/use-backend-status";
import { useKycSession } from "@/hooks/use-kyc-session";
import { toApiError } from "@/services/api-client";
import { assetsService, conversationService, sessionService } from "@/services";
import type { AssetRequirement, KYCField } from "@/types/api";

type UiMessage = {
  id: string;
  role: "assistant" | "user";
  content: string;
  /** Wall-clock time the message was added (rendered under the bubble). */
  at: string;
  /** Validation tint for assistant messages after an answer. */
  tone?: "accepted" | "rejected";
  /** Set on failure bubbles — the original text, offered for one-tap retry. */
  retryContent?: string;
};

let messageCounter = 0;
const nextId = () => `m-${++messageCounter}`;
const now = () =>
  new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/**
 * AI-Guided Completion Workspace (Phase 9B.1 — fully integrated).
 *
 * Uses the real /conversation endpoints: start (or resume mid-session),
 * reply (extraction + validation + next question in one call), explain.
 * The right column shows live progress from /session/{id}/progress.
 */
export default function InterviewPage() {
  const {
    sessionId,
    session,
    progress,
    restoring,
    schema,
    fieldMap,
    ensureSession,
    adoptSession,
    refresh,
    markUserAnswered,
  } = useKycSession();
  const backend = useBackendStatus();

  const [messages, setMessages] = React.useState<UiMessage[]>([]);
  const [draft, setDraft] = React.useState("");
  const [typing, setTyping] = React.useState(false);
  const [phase, setPhase] = React.useState<"booting" | "ready" | "error">("booting");
  const [bootError, setBootError] = React.useState("");
  const [currentQuestion, setCurrentQuestion] = React.useState<KYCField | null>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const bootedRef = React.useRef(false);

  const completed = progress?.interview_status === "completed";

  /* --- form assets (photo / signature) --------------------------------- */

  /**
   * What this form requires. Only ever non-empty when the ACTIVE form actually
   * asks for an image; failures are silent, because assets are a conditional
   * extra rather than part of the core interview.
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
  const assetReqs = React.useMemo(
    () => assetState.data ?? [],
    [assetState.data],
  );

  /**
   * The asset the interview is asking for RIGHT NOW.
   *
   * An asset field cannot be answered by typing — its value is an uploaded
   * image — so when it comes up the composer is swapped for an upload card
   * rather than left accepting text that could never validate.
   */
  const activeAsset = React.useMemo(
    () =>
      currentQuestion?.field_type === "asset"
        ? (assetReqs.find((r) => r.field_id === currentQuestion.id) ?? null)
        : null,
    [currentQuestion, assetReqs],
  );

  /** After an upload/removal: re-sync progress AND the next question. */
  const onAssetChanged = React.useCallback(async () => {
    if (!sessionId) return;
    assetState.reload();
    try {
      const next = await sessionService.nextQuestion(sessionId);
      setCurrentQuestion(next.question);
    } catch {
      /* refresh() below still updates progress */
    }
    await refresh();
  }, [sessionId, assetState, refresh]);

  /**
   * The asset being asked for is already supplied — accept it and move on.
   *
   * Re-runs the same recompute every other answer uses, then asks for the next
   * question. Without this the conversation stalls: the field is answered, so
   * re-uploading changes nothing, and no other control advances it.
   */
  const keepingRef = React.useRef(false);
  const keepAssetAndContinue = React.useCallback(async () => {
    if (!sessionId || keepingRef.current) return;
    // One in-flight continue at a time. The button is disabled while it runs,
    // but a ref also survives a re-render, so the request cannot be doubled.
    keepingRef.current = true;
    try {
      // Recompute FIRST: the backend re-adopts an asset the session already
      // holds, so the field this question is asking about becomes answered
      // before we ask what comes next. Without that ordering the same asset
      // question came straight back.
      await refresh();
      const asked = currentQuestion?.id;
      const next = await sessionService.nextQuestion(sessionId);
      setCurrentQuestion(next.question);
      if (next.question && next.question.id === asked) {
        // The field is still outstanding, so nothing was actually settled.
        // Say so rather than repeating the question as if we had moved on.
        toast.error("That still needs an image", {
          description: "Please upload it to continue.",
        });
        return;
      }
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: "assistant",
          at: now(),
          content: next.completed
            ? "Perfect — that's everything. You can generate your completed form now."
            : next.question
              ? `Great, we'll keep the one you already uploaded.

${next.question.display_name}${next.question.help_text ? ` — ${next.question.help_text}` : ""}`
              : "Great, we'll keep the one you already uploaded.",
        },
      ]);
    } catch (err) {
      toast.error("Couldn't continue", { description: toApiError(err).message });
    } finally {
      keepingRef.current = false;
    }
  }, [sessionId, refresh, currentQuestion]);

  /* Auto-scroll on new messages. */
  React.useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, typing]);

  /* --- boot: start a conversation or resume the persisted session ----- */
  const boot = React.useCallback(async () => {
    setPhase("booting");
    try {
      if (sessionId) {
        /*
         * Resume: the next question and a fresh session/progress snapshot are
         * independent reads of the same session, so they overlap. This used
         * to be nextQuestion THEN refresh, which put two full round trips
         * back to back behind "Preparing your interview…".
         */
        const [next] = await Promise.all([
          sessionService.nextQuestion(sessionId),
          refresh(),
        ]);
        setCurrentQuestion(next.question);
        if (next.completed) {
          setMessages([
            {
              id: nextId(),
              role: "assistant",
              at: now(),
              content:
                "Welcome back! 🎉 Every required field is already answered — head to PDF Preview to generate your filled form.",
            },
          ]);
        } else {
          const question = next.question;
          setMessages([
            {
              id: nextId(),
              role: "assistant",
              at: now(),
              content: question
                ? `Welcome back! Let's continue — ${next.remaining_required} required field${next.remaining_required === 1 ? "" : "s"} to go.\n\n${question.display_name}${question.help_text ? ` — ${question.help_text}` : ""}${question.example ? ` (e.g. ${question.example})` : ""}`
                : "Welcome back! Let's continue.",
            },
          ]);
        }
      } else {
        // Fresh start via the AI conversation endpoint (creates the session).
        const started = await conversationService.start();
        setCurrentQuestion(started.question);
        setMessages([
          { id: nextId(), role: "assistant", at: now(), content: started.message },
        ]);
        // adoptSession already loads session + progress for the new id, so
        // the refresh() that used to run here was a second identical fetch.
        await adoptSession(started.session_id);
      }
      setPhase("ready");
    } catch (err) {
      setBootError(toApiError(err).message);
      setPhase("error");
    }
  }, [sessionId, adoptSession, refresh]);

  React.useEffect(() => {
    /*
     * Wait for the backend to be reachable before booting the interview.
     *
     * The fresh-start path POSTs /conversation/start, which CREATES a session
     * — non-idempotent, so the API client (correctly) never retries it. Fired
     * at a container that is still waking, that single attempt was spent
     * waiting on a queued request and abandoned at the client ceiling, which
     * is exactly the "Couldn't start the interview — the backend took too
     * long to respond" seen in production after minutes of waiting.
     *
     * The shared probe already absorbs the cold start with bounded retries on
     * an idempotent GET /health, so gating on it means the interview's own
     * requests only ever meet a backend that has answered. Raising the
     * timeout instead would have kept firing a one-shot mutation into a
     * sleeping container and just waited longer before giving up.
     */
    if (restoring || backend.isWaking || bootedRef.current) return;
    bootedRef.current = true;
    void boot();
  }, [restoring, backend.isWaking, boot]);

  /* --- send a reply ----------------------------------------------------- */
  const send = async (retryOf?: string) => {
    const content = (retryOf ?? draft).trim();
    if (!content || typing || phase !== "ready") return;
    if (!retryOf) setDraft("");
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", at: now(), content },
    ]);
    setTyping(true);
    try {
      const id = sessionId ?? (await ensureSession());
      const reply = await conversationService.reply(id, content);
      setCurrentQuestion(reply.next_question);
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: "assistant",
          at: now(),
          content: reply.message,
          tone:
            reply.accepted === true
              ? "accepted"
              : reply.accepted === false
                ? "rejected"
                : undefined,
        },
      ]);
      if (reply.accepted === true && reply.extraction?.field_id) {
        // The user answered this herself — it is no longer "AI prefilled",
        // so deleting a source document later must not clear it.
        markUserAnswered([reply.extraction.field_id]);
        const label =
          fieldMap.get(reply.extraction.field_id)?.display_name ??
          reply.extraction.field_id;
        toast.success(`${label} saved`, {
          description: reply.validation?.message,
        });
      }
      if (reply.interview_status === "completed") {
        toast.success("Interview complete! 🎉", {
          description: "You can now generate your filled PDF.",
        });
      }
      await refresh();
    } catch (err) {
      const apiError = toApiError(err);
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: "assistant",
          at: now(),
          content: `Sorry — I couldn't process that (${apiError.message}).`,
          tone: "rejected",
          retryContent: content,
        },
      ]);
      toast.error("Message failed", { description: apiError.message });
    } finally {
      setTyping(false);
    }
  };

  /* --- explain the current field ---------------------------------------- */
  const explain = async () => {
    if (!sessionId || typing) return;
    setTyping(true);
    try {
      const explanation = await conversationService.explain(sessionId);
      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: "assistant", at: now(), content: explanation.message },
      ]);
    } catch (err) {
      toast.error("Couldn't fetch an explanation", {
        description: toApiError(err).message,
      });
    } finally {
      setTyping(false);
    }
  };

  /* --- derived sidebar data ---------------------------------------------- */
  const pendingIds = progress?.pending_required_fields ?? [];
  const progressPercent = Math.round(progress?.progress_percentage ?? session?.progress_percentage ?? 0);

  /*
   * One spinner used to cover four different situations, so a cold start was
   * indistinguishable from a hang. Each state now says what is actually
   * happening, and a conclusively unreachable backend becomes a real error
   * with a retry rather than a spinner that never resolves.
   */
  if (backend.isOffline && phase !== "ready") {
    return (
      <ErrorState
        title="Sahayak's backend isn't responding"
        description="The server didn't answer after several attempts. It may still be starting up — try again in a moment."
        onRetry={() => {
          backend.retry();
          void boot();
        }}
        className="min-h-[50dvh]"
      />
    );
  }

  if (restoring || phase === "booting") {
    return (
      <LoadingAnimation
        label={
          backend.isWaking
            ? "Waking up Sahayak — the free-tier server sleeps when idle. This can take up to a minute."
            : restoring
              ? "Restoring your session…"
              : "Preparing your interview…"
        }
        className="min-h-[50dvh]"
      />
    );
  }

  if (phase === "error") {
    return (
      <ErrorState
        title="Couldn't start the interview"
        description={bootError}
        onRetry={() => void boot()}
        className="min-h-[50dvh]"
      />
    );
  }

  return (
    <div className="grid gap-6 lg:h-[calc(100dvh-10.5rem)] lg:grid-cols-3">
      {/* Chat column */}
      <Card className="flex min-h-[60dvh] flex-col lg:col-span-2 lg:min-h-0">
        <CardHeader className="flex-row items-center justify-between space-y-0 border-b border-border p-4 sm:p-4 sm:px-6">
          <div className="flex items-center gap-3">
            <span className="grid size-9 place-items-center rounded-full bg-gradient-to-br from-primary to-accent text-primary-foreground glow-primary">
              <Sparkles className="size-4.5" aria-hidden />
            </span>
            <div>
              <CardTitle className="text-sm">Sahayak</CardTitle>
              <p className="text-xs text-muted-foreground">
                {typing
                  ? "typing…"
                  : currentQuestion
                    ? `Asking: ${currentQuestion.display_name}`
                    : "Your KYC interviewer"}
              </p>
            </div>
          </div>
          <StatusBadge status={completed ? "completed" : "in_progress"} />
        </CardHeader>

        {/* Messages */}
        <div
          ref={scrollRef}
          className="flex-1 space-y-4 overflow-y-auto p-4 sm:p-6"
          role="log"
          aria-label="Interview conversation"
          aria-live="polite"
        >
          {messages.map((message) => (
            <ChatBubble key={message.id} role={message.role}>
              <span className="whitespace-pre-line">{message.content}</span>
              <span className="mt-1 flex items-center justify-between gap-3">
                <time className="block text-[10px] text-muted-foreground/80">
                  {message.at}
                </time>
                {message.retryContent && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-6 px-2 text-xs"
                    disabled={typing}
                    onClick={() => void send(message.retryContent)}
                  >
                    <RotateCcw className="size-3" aria-hidden /> Retry
                  </Button>
                )}
              </span>
            </ChatBubble>
          ))}
          {typing && (
            <ChatBubble role="assistant">
              <TypingIndicator />
            </ChatBubble>
          )}
        </div>

        {/* Asset step: this question wants an image, so the text composer is
            replaced rather than left accepting input that cannot validate. */}
        {activeAsset && sessionId && !completed ? (
          <div className="space-y-2 border-t border-border p-3 sm:p-4">
            <p className="text-xs text-muted-foreground">
              This one needs an image rather than a typed answer.
            </p>
            <AssetUploadCard
              sessionId={sessionId}
              requirement={activeAsset}
              onChanged={onAssetChanged}
              onKeepAndContinue={keepAssetAndContinue}
            />
          </div>
        ) : (
        /* Composer */
        <form
          className="flex items-center gap-2 border-t border-border p-3 sm:p-4"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Explain this question"
            title="Explain this question"
            disabled={typing || completed}
            onClick={() => void explain()}
          >
            <HelpCircle className="size-4.5" />
          </Button>
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={
              completed ? "Interview complete 🎉" : "Type your answer…"
            }
            aria-label="Your answer"
            className="flex-1"
            disabled={typing || completed}
          />
          <Button
            type="submit"
            variant="gradient"
            size="icon"
            aria-label="Send answer"
            disabled={!draft.trim() || typing || completed}
          >
            <Send className="size-4.5" />
          </Button>
        </form>
        )}
      </Card>

      {/* Live progress sidebar */}
      <div className="flex flex-col gap-4 lg:min-h-0">
        <Card>
          <CardContent className="space-y-2.5 p-4 sm:p-5">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">{schema?.title ?? "Your KYC form"}</span>
              <span className="tabular-nums text-muted-foreground">
                {progressPercent}%
              </span>
            </div>
            <Progress value={progressPercent} aria-label="Interview progress" />
            <p className="text-xs text-muted-foreground">
              {pendingIds.length} required field{pendingIds.length === 1 ? "" : "s"} remaining
            </p>
          </CardContent>
        </Card>

        {/* Photo / signature — rendered ONLY when this form requires them.
            Kept beside the chat so they can be supplied at any point, not
            just when the interview happens to reach them. */}
        {sessionId &&
          assetReqs
            // The one being asked right now already has a card in the chat
            // column — showing it twice reads as two separate uploads.
            .filter((r) => r.required && r.kind !== activeAsset?.kind)
            .map((requirement) => (
              <AssetUploadCard
                key={requirement.kind}
                sessionId={sessionId}
                requirement={requirement}
                onChanged={onAssetChanged}
              />
            ))}

        {completed ? (
          <SuccessState
            title="All required fields complete"
            description="Generate your filled, validated PDF now."
            action={
              <Button variant="gradient" asChild>
                <Link href="/preview">
                  Go to PDF Preview <ArrowRight aria-hidden />
                </Link>
              </Button>
            }
          />
        ) : (
          <Card className="flex-1 lg:min-h-0 lg:overflow-hidden">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Still to answer</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 lg:max-h-full lg:overflow-y-auto">
              {pendingIds.map((fieldId) => {
                const field = fieldMap.get(fieldId);
                const isCurrent = currentQuestion?.id === fieldId;
                return (
                  <div
                    key={fieldId}
                    className={
                      "flex items-center justify-between gap-3 rounded-lg border px-3 py-2.5 " +
                      (isCurrent
                        ? "border-primary/60 bg-primary/5"
                        : "border-border")
                    }
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm">
                        {field?.display_name ?? fieldId}
                      </p>
                      <p className="text-xs capitalize text-muted-foreground">
                        {field?.section?.replace(/_/g, " ") ?? ""}
                        {isCurrent ? " · asking now" : ""}
                      </p>
                    </div>
                    <StatusBadge status="pending" />
                  </div>
                );
              })}
              <Button variant="outline" size="sm" className="mt-2 w-full" asChild>
                <Link href="/progress">
                  View full progress <ArrowRight aria-hidden />
                </Link>
              </Button>
            </CardContent>
          </Card>
        )}

        <Button
          variant="ghost"
          size="sm"
          className="text-muted-foreground"
          onClick={() => {
            bootedRef.current = false;
            void boot();
          }}
        >
          <RotateCcw aria-hidden /> Reload conversation
        </Button>
      </div>
    </div>
  );
}
