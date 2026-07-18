"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Sparkles } from "lucide-react";

import { Logo } from "@/components/shared/logo";
import { APP_NAV } from "@/lib/navigation";
import { cn } from "@/lib/utils";

/**
 * Workspace sidebar navigation. Rendered inline on ≥lg screens and inside a
 * slide-over drawer on mobile (see AppShell). `onNavigate` closes the drawer.
 * `collapsed` (Phase 13) switches to an icon-only rail — labels become
 * tooltips via `title`, and the RAG promo shrinks to its icon.
 */
export function SidebarNav({
  onNavigate,
  collapsed = false,
  className,
}: {
  onNavigate?: () => void;
  collapsed?: boolean;
  className?: string;
}) {
  const pathname = usePathname();

  return (
    <div className={cn("flex h-full flex-col", className)}>
      <div className={cn("flex h-16 items-center", collapsed ? "justify-center px-2" : "px-5")}>
        <Logo href="/dashboard" compact={collapsed} />
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-4" aria-label="Workspace">
        {APP_NAV.map((section) => (
          <div key={section.label}>
            {!collapsed && (
              <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                {section.label}
              </p>
            )}
            <ul className="space-y-0.5">
              {section.items.map((item) => {
                const active = pathname === item.href;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      title={collapsed ? item.title : undefined}
                      className={cn(
                        "group flex items-center gap-3 rounded-lg py-2.5 text-sm font-medium transition-all",
                        collapsed ? "justify-center px-2" : "px-3",
                        active
                          ? "bg-primary/12 text-primary shadow-[inset_2px_0_0_var(--primary)]"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground",
                      )}
                    >
                      <item.icon
                        className={cn(
                          "size-4.5 shrink-0 transition-transform group-hover:scale-110",
                          active && "text-primary",
                        )}
                        aria-hidden
                      />
                      {!collapsed && <span className="truncate">{item.title}</span>}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* RAG slot (Phase 10): the Knowledge Chat panel is live. */}
      <Link
        href="/knowledge"
        onClick={onNavigate}
        aria-current={pathname === "/knowledge" ? "page" : undefined}
        title={collapsed ? "Knowledge Chat" : undefined}
        className={cn(
          "group m-3 block rounded-xl border transition-colors",
          collapsed ? "grid place-items-center p-2.5" : "p-3.5",
          pathname === "/knowledge"
            ? "border-primary/60 bg-primary/5"
            : "border-border bg-muted/40 hover:border-primary/40 hover:bg-primary/5",
        )}
      >
        <p className="flex items-center gap-1.5 text-xs font-semibold">
          <Sparkles className="size-3.5 text-accent" aria-hidden />
          {!collapsed && "Knowledge Chat"}
        </p>
        {!collapsed && (
          <p className="mt-1 text-xs text-muted-foreground">
            Ask anything about KYC rules — answers cited from official documents.
          </p>
        )}
      </Link>
    </div>
  );
}
