"use client";

import { motion } from "framer-motion";
import { Sparkles, User } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * AI Chat Bubble — the interview's core visual. Assistant messages sit left
 * with a gradient avatar; user messages sit right in the primary tint.
 */
export function ChatBubble({
  role,
  children,
  className,
}: {
  role: "assistant" | "user";
  children: React.ReactNode;
  className?: string;
}) {
  const isAssistant = role === "assistant";

  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      className={cn(
        "flex w-full gap-2.5 sm:gap-3",
        isAssistant ? "justify-start" : "justify-end",
        className,
      )}
    >
      {isAssistant && (
        <span
          aria-hidden
          className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-primary to-accent text-primary-foreground shadow-sm"
        >
          <Sparkles className="size-4" />
        </span>
      )}
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm sm:max-w-[75%]",
          isAssistant
            ? "rounded-tl-sm border border-border bg-card text-card-foreground"
            : "rounded-tr-sm bg-primary/15 text-foreground",
        )}
      >
        {children}
      </div>
      {!isAssistant && (
        <span
          aria-hidden
          className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground"
        >
          <User className="size-4" />
        </span>
      )}
    </motion.div>
  );
}

/** Three-dot typing indicator, rendered inside an assistant bubble. */
export function TypingIndicator({ className }: { className?: string }) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 py-1", className)}
      role="status"
      aria-label="Sahayak is typing"
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="typing-dot size-1.5 rounded-full bg-muted-foreground"
        />
      ))}
    </span>
  );
}
