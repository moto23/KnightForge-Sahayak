"use client";

import * as React from "react";
import {
  Check,
  History,
  LogIn,
  MessageSquarePlus,
  Pencil,
  Search,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/auth-context";
import { toApiError } from "@/services/api-client";
import { chatsService } from "@/services";
import type { ChatSummary } from "@/types/api";

/**
 * Conversation history panel (Phase 12) — the signed-in sidebar of the
 * Knowledge Chat. Lists saved conversations (search, rename, delete,
 * continue). Guests see a gentle sign-in prompt instead — the assistant
 * itself works without an account.
 */
export function ChatHistoryPanel({
  activeChatId,
  refreshKey,
  onSelect,
  onNewChat,
  onDeleted,
}: {
  activeChatId: string | null;
  /** Bump to force a list reload (e.g. after the first message titles a chat). */
  refreshKey: number;
  onSelect: (chatId: string) => void;
  onNewChat: () => void;
  onDeleted: (chatId: string) => void;
}) {
  const { isAuthenticated, restoring } = useAuth();
  const [chats, setChats] = React.useState<ChatSummary[]>([]);
  const [query, setQuery] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [renamingId, setRenamingId] = React.useState<string | null>(null);
  const [renameDraft, setRenameDraft] = React.useState("");

  /* Load (and search) the list whenever auth state, query or key changes. */
  React.useEffect(() => {
    if (!isAuthenticated) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      chatsService
        .list(query, controller.signal)
        .then((response) => setChats(response.chats))
        .catch((err) => {
          const apiError = toApiError(err);
          if (!apiError.isCancelled) setChats([]);
        })
        .finally(() => setLoading(false));
    }, query ? 250 : 0); // debounce typing, load immediately otherwise
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [isAuthenticated, query, refreshKey]);

  /* Signed out: clear stale rows (adjust-state-during-render pattern). */
  const [wasAuthenticated, setWasAuthenticated] = React.useState(isAuthenticated);
  if (wasAuthenticated !== isAuthenticated) {
    setWasAuthenticated(isAuthenticated);
    if (!isAuthenticated) setChats([]);
  }

  const commitRename = async (chat: ChatSummary) => {
    const title = renameDraft.trim();
    setRenamingId(null);
    if (!title || title === chat.title) return;
    try {
      const updated = await chatsService.rename(chat.chat_id, title);
      setChats((prev) =>
        prev.map((c) => (c.chat_id === chat.chat_id ? updated : c)),
      );
    } catch (err) {
      toast.error("Couldn't rename", { description: toApiError(err).message });
    }
  };

  const remove = async (chat: ChatSummary) => {
    try {
      await chatsService.remove(chat.chat_id);
      setChats((prev) => prev.filter((c) => c.chat_id !== chat.chat_id));
      onDeleted(chat.chat_id);
      toast(`"${chat.title}" deleted`);
    } catch (err) {
      toast.error("Couldn't delete", { description: toApiError(err).message });
    }
  };

  if (restoring) return null;

  if (!isAuthenticated) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <History className="size-4 text-accent" aria-hidden /> Conversation history
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            You&apos;re chatting as a guest — answers work fully, but nothing is
            saved. Sign in to keep your conversations and continue them on any
            device.
          </p>
          <Button variant="outline" size="sm" className="w-full" asChild>
            <Link href="/signin">
              <LogIn aria-hidden /> Sign in to save history
            </Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="flex flex-col lg:min-h-0">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <History className="size-4 text-accent" aria-hidden /> Your conversations
          </CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={onNewChat}
            aria-label="Start a new conversation"
          >
            <MessageSquarePlus aria-hidden /> New
          </Button>
        </div>
        <div className="relative mt-2">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats…"
            aria-label="Search conversations"
            className="h-8 pl-8 text-xs"
          />
        </div>
      </CardHeader>
      <CardContent className="flex-1 space-y-1.5 lg:overflow-y-auto">
        {chats.length === 0 && (
          <p className="py-2 text-xs text-muted-foreground">
            {loading
              ? "Loading…"
              : query
                ? "No conversations match your search."
                : "No saved conversations yet — ask your first question."}
          </p>
        )}
        {chats.map((chat) => (
          <div
            key={chat.chat_id}
            className={cn(
              "group flex items-center gap-1.5 rounded-lg border border-transparent px-2 py-1.5 transition-colors",
              chat.chat_id === activeChatId
                ? "border-primary/50 bg-primary/10"
                : "hover:bg-muted/60",
            )}
          >
            {renamingId === chat.chat_id ? (
              <>
                <Input
                  value={renameDraft}
                  onChange={(e) => setRenameDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void commitRename(chat);
                    if (e.key === "Escape") setRenamingId(null);
                  }}
                  autoFocus
                  className="h-7 flex-1 text-xs"
                  aria-label="New title"
                />
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7"
                  aria-label="Save title"
                  onClick={() => void commitRename(chat)}
                >
                  <Check className="size-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7"
                  aria-label="Cancel rename"
                  onClick={() => setRenamingId(null)}
                >
                  <X className="size-3.5" />
                </Button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left"
                  onClick={() => onSelect(chat.chat_id)}
                >
                  <span className="block truncate text-xs font-medium">
                    {chat.title}
                  </span>
                  <span className="block text-[10px] text-muted-foreground">
                    {new Date(chat.updated_at).toLocaleString([], {
                      day: "2-digit",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                </button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 opacity-0 transition-opacity group-hover:opacity-100"
                  aria-label={`Rename ${chat.title}`}
                  onClick={() => {
                    setRenamingId(chat.chat_id);
                    setRenameDraft(chat.title);
                  }}
                >
                  <Pencil className="size-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 opacity-0 transition-opacity group-hover:opacity-100 hover:text-destructive"
                  aria-label={`Delete ${chat.title}`}
                  onClick={() => void remove(chat)}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
