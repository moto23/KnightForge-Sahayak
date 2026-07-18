import Link from "next/link";
import { ShieldCheck } from "lucide-react";

import { cn } from "@/lib/utils";

/** Brand lockup — icon chip + wordmark. `compact` hides the wordmark. */
export function Logo({
  compact = false,
  className,
  href = "/",
}: {
  compact?: boolean;
  className?: string;
  href?: string;
}) {
  return (
    <Link
      href={href}
      className={cn("group inline-flex items-center gap-2.5", className)}
      aria-label="KnightForge Sahayak — home"
    >
      <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-primary to-accent text-primary-foreground shadow-md glow-primary transition-transform group-hover:scale-105">
        <ShieldCheck className="size-5" aria-hidden />
      </span>
      {!compact && (
        <span className="flex flex-col leading-none">
          <span className="text-sm font-bold tracking-tight">KnightForge</span>
          <span className="text-gradient text-xs font-semibold tracking-widest uppercase">
            Sahayak
          </span>
        </span>
      )}
    </Link>
  );
}
