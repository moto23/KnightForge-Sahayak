"use client";

import * as React from "react";
import {
  BookOpenText,
  Database,
  FileText,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";

import { ChatBubble, TypingIndicator } from "@/components/shared/chat-bubble";
import { ChatHistoryPanel } from "@/components/knowledge/chat-history-panel";
import {
  EmptyState,
  ErrorState,
  LoadingAnimation,
} from "@/components/shared/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/contexts/auth-context";
import { toApiError } from "@/services/api-client";
import { chatsService, knowledgeService } from "@/services";
import type {
  ChatMessage,
  KnowledgeCitation,
  KnowledgeStatusResponse,
} from "@/types/api";

type UiMessage = {
  id: string;
  role: "assistant" | "user";
  content: string;
  at: string;
  /** Assistant-only: the passages the answer is grounded in. */
  citations?: KnowledgeCitation[];
  /** Assistant-only: false = honest "I don't know" (nothing was guessed). */
  confident?: boolean;
  /** Assistant-only: "extractive-fallback" when the LLM was offline. */
  generator?: string;
};

let messageCounter = 0;
const nextId = () => `k-${++messageCounter}`;
const now = () =>
  new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

const WELCOME =
  "Hi! I answer questions about KYC rules, accepted documents and the KRA process — grounded in the official reference documents, with citations. If the documents don't cover something, I'll say so instead of guessing.";

const SUGGESTED_QUESTIONS = [
  "Which documents are accepted as proof of address?",
  "Is PAN mandatory for KYC?",
  "What does the KYC On-Hold status mean?",
  "How do I update my address after moving?",
];

/**
 * Knowledge Chat (Phase 10, extended by Phase 12) — RAG-grounded Q&A over
 * official KYC documents.
 *
 * Guest mode: exactly the Phase 10 behavior — /knowledge/query, answers with
 * citations, nothing saved, no sign-in required.
 *
 * Signed in: questions route through /chats/{id}/messages instead, which
 * persists both turns AND adds multi-turn memory (follow-ups are rewritten
 * into standalone questions server-side). The sidebar lists saved
 * conversations to continue, rename, delete, or search.
 */
export default function KnowledgePage() {
  const { isAuthenticated, restoring } = useAuth();
  const [status, setStatus] = React.useState<KnowledgeStatusResponse | null>(null);
  const [phase, setPhase] = React.useState<"booting" | "ready" | "error">("booting");
  const [bootError, setBootError] = React.useState("");
  const [messages, setMessages] = React.useState<UiMessage[]>([]);
  const [draft, setDraft] = React.useState("");
  const [typing, setTyping] = React.useState(false);
  const [indexing, setIndexing] = React.useState(false);
  const [activeChatId, setActiveChatId] = React.useState<string | null>(null);
  const [historyKey, setHistoryKey] = React.useState(0);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  /* Auto-scroll on new messages. */
  React.useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, typing]);

  /* --- boot: fetch engine status ---------------------------------------- */
  const boot = React.useCallback(async () => {
  try {
    const snapshot = await knowledgeService.status();

    React.startTransition(() => {
      setStatus(snapshot);

      if (snapshot.ready) {
        setMessages((prev) =>
          prev.length > 0
            ? prev
            : [
                {
                  id: nextId(),
                  role: "assistant",
                  at: now(),
                  content: WELCOME,
                },
              ],
        );
      }

      setPhase("ready");
    });
  } catch (err) {
    React.startTransition(() => {
      setBootError(toApiError(err).message);
      setPhase("error");
    });
  }
}, []);

React.useEffect(() => {
  queueMicrotask(() => {
    void boot();
  });
}, [boot]);

  /* --- build / rebuild the index ----------------------------------------- */
  const buildIndex = async () => {
    if (indexing) return;
    setIndexing(true);
    try {
      const report = await knowledgeService.buildIndex();
      toast.success("Knowledge index built", {
        description: `${report.chunks_indexed} chunks from ${report.documents_indexed} document${report.documents_indexed === 1 ? "" : "s"} in ${report.elapsed_seconds}s.`,
      });
      const snapshot = await knowledgeService.status();
      setStatus(snapshot);
      setMessages((prev) =>
        prev.length > 0
          ? prev
          : [{ id: nextId(), role: "assistant", at: now(), content: WELCOME }],
      );
    } catch (err) {
      toast.error("Indexing failed", { description: toApiError(err).message });
    } finally {
      setIndexing(false);
    }
  };

  /* --- saved conversations (Phase 12) ------------------------------------ */

  const fromPersisted = React.useCallback(
    (message: ChatMessage): UiMessage => ({
      id: message.message_id,
      role: message.role,
      content: message.content,
      at: new Date(message.created_at).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      }),
      citations: message.citations,
      confident: message.confident ?? undefined,
      generator: message.generator ?? undefined,
    }),
    [],
  );

  /** Continue a previous chat: load its transcript into the window. */
  const openChat = React.useCallback(
    async (chatId: string) => {
      try {
        const detail = await chatsService.get(chatId);
        setActiveChatId(chatId);
        setMessages(detail.messages.map(fromPersisted));
      } catch (err) {
        toast.error("Couldn't open the conversation", {
          description: toApiError(err).message,
        });
      }
    },
    [fromPersisted],
  );

  /** Start a fresh conversation (blank window; created on first question). */
  const newChat = React.useCallback(() => {
    setActiveChatId(null);
    setMessages([{ id: nextId(), role: "assistant", at: now(), content: WELCOME }]);
  }, []);

  /* Signing out mid-conversation: drop back to a guest window.
     (Adjust-state-during-render — avoids a setState-in-effect cascade.) */
  const [wasAuthenticated, setWasAuthenticated] = React.useState(isAuthenticated);
  if (wasAuthenticated !== isAuthenticated) {
    setWasAuthenticated(isAuthenticated);
    if (!isAuthenticated && activeChatId) {
      setActiveChatId(null);
      setMessages([{ id: nextId(), role: "assistant", at: now(), content: WELCOME }]);
    }
  }

  /* --- ask a question ----------------------------------------------------- */
  const ask = async (question?: string) => {
    const content = (question ?? draft).trim();
    if (!content || typing || !status?.ready) return;
    if (!question) setDraft("");
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", at: now(), content },
    ]);
    setTyping(true);
    try {
      if (isAuthenticated) {
        // Persisted path: create the conversation lazily, then ask inside it.
        let chatId = activeChatId;
        if (!chatId) {
          const created = await chatsService.create();
          chatId = created.chat_id;
          setActiveChatId(chatId);
        }
        const turn = await chatsService.ask(chatId, content);
        setMessages((prev) => [...prev, fromPersisted(turn.assistant_message)]);
        setHistoryKey((k) => k + 1); // titles/ordering changed
      } else {
        // Guest path: exactly the Phase 10 behavior — nothing saved.
        const reply = await knowledgeService.query(content);
        setMessages((prev) => [
          ...prev,
          {
            id: nextId(),
            role: "assistant",
            at: now(),
            content: reply.answer,
            citations: reply.citations,
            confident: reply.confident,
            generator: reply.generator,
          },
        ]);
      }
    } catch (err) {
      const apiError = toApiError(err);
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: "assistant",
          at: now(),
          content: `Sorry — I couldn't answer that (${apiError.message}).`,
          confident: false,
        },
      ]);
      toast.error("Question failed", { description: apiError.message });
    } finally {
      setTyping(false);
    }
  };

  if (phase === "booting") {
    return <LoadingAnimation label="Checking the knowledge base…" className="min-h-[50dvh]" />;
  }

  if (phase === "error") {
    return (
      <ErrorState
        title="Couldn't reach the knowledge engine"
        description={bootError}
        onRetry={() => void boot()}
        className="min-h-[50dvh]"
      />
    );
  }

  const ready = status?.ready === true;
  const installed = status?.dependencies_installed === true;

  return (
    <div className="grid gap-6 lg:h-[calc(100dvh-10.5rem)] lg:grid-cols-3">
      {/* Chat column */}
      <Card className="flex min-h-[60dvh] flex-col lg:col-span-2 lg:min-h-0">
        <CardHeader className="flex-row items-center justify-between space-y-0 border-b border-border p-4 sm:p-4 sm:px-6">
          <div className="flex items-center gap-3">
            <span className="grid size-9 place-items-center rounded-full bg-gradient-to-br from-primary to-accent text-primary-foreground glow-primary">
              <BookOpenText className="size-4.5" aria-hidden />
            </span>
            <div>
              <CardTitle className="text-sm">Knowledge Chat</CardTitle>
              <p className="text-xs text-muted-foreground">
                {typing
                  ? "searching the documents…"
                  : ready
                    ? `Grounded in ${status?.document_count} official document${status?.document_count === 1 ? "" : "s"}`
                    : "Not indexed yet"}
              </p>
            </div>
          </div>
          <Badge variant={ready ? "success" : "warning"}>
            <span aria-hidden className="size-1.5 rounded-full bg-current" />
            {ready ? "Ready" : installed ? "Needs indexing" : "Not installed"}
          </Badge>
        </CardHeader>

        {/* Messages / setup states */}
        {!installed ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <ErrorState
              title="RAG stack not installed"
              description="Install the knowledge dependencies on the backend, then restart it: pip install chromadb sentence-transformers"
              onRetry={() => void boot()}
              className="border-none"
            />
          </div>
        ) : !ready ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <EmptyState
              title="The knowledge base is empty"
              description="Build the vector index from the official KYC documents once — after that, every question is answered locally with citations."
              action={
                <Button variant="gradient" disabled={indexing} onClick={() => void buildIndex()}>
                  {indexing ? (
                    <>
                      <RefreshCw className="animate-spin" aria-hidden /> Indexing…
                    </>
                  ) : (
                    <>
                      <Database aria-hidden /> Build index
                    </>
                  )}
                </Button>
              }
              className="border-none"
            />
          </div>
        ) : (
          <div
            ref={scrollRef}
            className="flex-1 space-y-4 overflow-y-auto p-4 sm:p-6"
            role="log"
            aria-label="Knowledge conversation"
            aria-live="polite"
          >
            {messages.map((message) => (
              <ChatBubble key={message.id} role={message.role}>
                <span className="whitespace-pre-line">{message.content}</span>

                {message.role === "assistant" && message.confident === false && (
                  <span className="mt-2 block">
                    <Badge variant="warning">
                      <ShieldCheck aria-hidden /> Honest answer — not covered by the documents
                    </Badge>
                  </span>
                )}
                {message.generator === "extractive-fallback" && (
                  <span className="mt-2 block">
                    <Badge variant="outline">AI offline — verbatim excerpts</Badge>
                  </span>
                )}

                {message.citations && message.citations.length > 0 && (
                  <span className="mt-3 block space-y-1.5 border-t border-border pt-2.5">
                    <span className="block text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                      Sources
                    </span>
                    {message.citations.map((citation, index) => (
                      <span
                        key={`${citation.document_name}-${citation.page_number}-${index}`}
                        className="block rounded-lg border border-border bg-muted/40 px-2.5 py-1.5"
                      >
                        <span className="flex items-center gap-1.5 text-xs font-medium">
                          <FileText className="size-3 shrink-0 text-accent" aria-hidden />
                          <span className="truncate">
                            [{index + 1}] {citation.document_name}
                          </span>
                          <span className="ml-auto shrink-0 tabular-nums text-[10px] text-muted-foreground">
                            p.{citation.page_number} · {Math.round(citation.similarity * 100)}%
                          </span>
                        </span>
                        <span className="mt-0.5 line-clamp-2 block text-[11px] leading-snug text-muted-foreground">
                          {citation.snippet}
                        </span>
                      </span>
                    ))}
                  </span>
                )}

                <time className="mt-1 block text-[10px] text-muted-foreground/80">
                  {message.at}
                </time>
              </ChatBubble>
            ))}
            {typing && (
              <ChatBubble role="assistant">
                <TypingIndicator />
              </ChatBubble>
            )}
          </div>
        )}

        {/* Composer */}
        <form
          className="flex items-center gap-2 border-t border-border p-3 sm:p-4"
          onSubmit={(e) => {
            e.preventDefault();
            void ask();
          }}
        >
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={
              ready ? "Ask about KYC rules, documents, the KRA process…" : "Build the index to start asking"
            }
            aria-label="Your question"
            className="flex-1"
            disabled={typing || !ready}
          />
          <Button
            type="submit"
            variant="gradient"
            size="icon"
            aria-label="Ask question"
            disabled={!draft.trim() || typing || !ready}
          >
            <Send className="size-4.5" />
          </Button>
        </form>
      </Card>

      {/* Knowledge base sidebar */}
      <div className="flex flex-col gap-4 lg:min-h-0 lg:overflow-y-auto">
        {!restoring && (
          <ChatHistoryPanel
            activeChatId={activeChatId}
            refreshKey={historyKey}
            onSelect={(chatId) => void openChat(chatId)}
            onNewChat={newChat}
            onDeleted={(chatId) => {
              if (chatId === activeChatId) newChat();
            }}
          />
        )}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Database className="size-4 text-accent" aria-hidden /> Knowledge base
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Documents</span>
              <span className="tabular-nums">{status?.document_count ?? 0}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Chunks</span>
              <span className="tabular-nums">{status?.chunk_count ?? 0}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="shrink-0 text-muted-foreground">Embeddings</span>
              <span className="truncate text-xs" title={status?.embedding_model}>
                {status?.embedding_model.split("/").pop()}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Answering</span>
              <span className="text-xs">
                {status?.ai_available ? "AI + citations" : "Extractive (AI offline)"}
              </span>
            </div>
            {status?.last_indexed_at && (
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Last indexed</span>
                <span className="text-xs">
                  {new Date(status.last_indexed_at).toLocaleString([], {
                    day: "2-digit",
                    month: "short",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </div>
            )}
            <Button
              variant="outline"
              size="sm"
              className="mt-1 w-full"
              disabled={indexing || !installed}
              onClick={() => void buildIndex()}
            >
              <RefreshCw className={indexing ? "animate-spin" : undefined} aria-hidden />
              {indexing ? "Rebuilding…" : ready ? "Rebuild index" : "Build index"}
            </Button>
          </CardContent>
        </Card>

        {ready && (
          <Card className="flex-1 lg:min-h-0 lg:overflow-hidden">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Sparkles className="size-4 text-accent" aria-hidden /> Try asking
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 lg:max-h-full lg:overflow-y-auto">
              {SUGGESTED_QUESTIONS.map((question) => (
                <button
                  key={question}
                  type="button"
                  disabled={typing}
                  onClick={() => void ask(question)}
                  className="w-full rounded-lg border border-border px-3 py-2.5 text-left text-sm text-muted-foreground transition-colors hover:border-primary/60 hover:bg-primary/5 hover:text-foreground disabled:opacity-50"
                >
                  {question}
                </button>
              ))}
              <p className="pt-1 text-xs text-muted-foreground">
                {"Answers come only from the indexed official documents — every claim is cited, and “I don't know” is a valid answer."}
              </p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
