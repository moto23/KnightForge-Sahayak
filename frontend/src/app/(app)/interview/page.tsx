"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, HelpCircle, RotateCcw, Send, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { ChatBubble, TypingIndicator } from "@/components/shared/chat-bubble";
import { ErrorState, LoadingAnimation, SuccessState } from "@/components/shared/states";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { useKycSession } from "@/hooks/use-kyc-session";
import { toApiError } from "@/services/api-client";
import { conversationService, sessionService } from "@/services";
import type { KYCField } from "@/types/api";

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
 * AI Interview Workspace (Phase 9B.1 — fully integrated).
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
    fieldMap,
    ensureSession,
    adoptSession,
    refresh,
    markUserAnswered,
  } = useKycSession();

  const [messages, setMessages] = React.useState<UiMessage[]>([]);
  const [draft, setDraft] = React.useState("");
  const [typing, setTyping] = React.useState(false);
  const [phase, setPhase] = React.useState<"booting" | "ready" | "error">("booting");
  const [bootError, setBootError] = React.useState("");
  const [currentQuestion, setCurrentQuestion] = React.useState<KYCField | null>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const bootedRef = React.useRef(false);

  const completed = progress?.interview_status === "completed";

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
        // Resume: fetch the next question for the existing session.
        const next = await sessionService.nextQuestion(sessionId);
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
        await adoptSession(started.session_id);
      }
      await refresh();
      setPhase("ready");
    } catch (err) {
      setBootError(toApiError(err).message);
      setPhase("error");
    }
  }, [sessionId, adoptSession, refresh]);

  React.useEffect(() => {
    if (restoring || bootedRef.current) return;
    bootedRef.current = true;
    void boot();
  }, [restoring, boot]);

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

  if (restoring || phase === "booting") {
    return <LoadingAnimation label="Preparing your interview…" className="min-h-[50dvh]" />;
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

        {/* Composer */}
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
      </Card>

      {/* Live progress sidebar */}
      <div className="flex flex-col gap-4 lg:min-h-0">
        <Card>
          <CardContent className="space-y-2.5 p-4 sm:p-5">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">CVL Individual KYC</span>
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
