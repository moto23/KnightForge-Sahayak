"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  History,
  LogIn,
  LogOut,
  Settings,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/auth-context";
import { toApiError } from "@/services/api-client";
import { cn } from "@/lib/utils";

const MENU_ITEMS = [
  { label: "Profile", href: "/settings", icon: UserRound },
  { label: "Settings", href: "/settings", icon: Settings },
  { label: "Upload History", href: "/upload#history", icon: History },
] as const;

/**
 * Top-right account menu (Phase 13). Signed in: avatar initial opens a
 * dropdown with the profile summary (name, email, provider) and quick links
 * (Profile / Settings / Upload History / Sign out). Guests get a plain
 * sign-in link — guest mode stays fully usable.
 */
export function ProfileMenu() {
  const router = useRouter();
  const { user, isAuthenticated, logout } = useAuth();
  const [open, setOpen] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);

  /* Close on outside click / Escape. */
  React.useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const signOut = async () => {
    setSigningOut(true);
    try {
      await logout();
      setOpen(false);
      toast.success("Signed out");
      router.push("/dashboard");
    } catch (err) {
      toast.error("Sign-out failed", { description: toApiError(err).message });
    } finally {
      setSigningOut(false);
    }
  };

  if (!isAuthenticated || !user) {
    return (
      <Button variant="outline" size="sm" asChild>
        <Link href="/signin">
          <LogIn aria-hidden /> Sign in
        </Link>
      </Button>
    );
  }

  const displayName = user.full_name || user.email;
  const initial = displayName.slice(0, 1).toUpperCase();
  const provider = user.google_linked
    ? user.has_password
      ? "Google + password"
      : "Google"
    : "Email";

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-label="Account menu"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "grid size-9 place-items-center rounded-full bg-primary/15 text-sm font-semibold text-primary transition-all hover:bg-primary/25",
          open && "ring-2 ring-primary/50",
        )}
      >
        {initial}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            role="menu"
            aria-label="Account"
            className="glass absolute right-0 top-11 z-50 w-64 overflow-hidden rounded-xl border border-border shadow-lg"
          >
            {/* Identity header */}
            <div className="flex items-center gap-3 border-b border-border px-4 py-3">
              <span className="grid size-10 shrink-0 place-items-center rounded-full bg-primary/15 text-sm font-semibold text-primary">
                {initial}
              </span>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{displayName}</p>
                <p className="truncate text-xs text-muted-foreground">{user.email}</p>
                <Badge variant="outline" className="mt-1">
                  {provider}
                </Badge>
              </div>
            </div>

            {/* Links */}
            <div className="p-1.5">
              {MENU_ITEMS.map((item) => (
                <Link
                  key={item.label}
                  href={item.href}
                  role="menuitem"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  <item.icon className="size-4" aria-hidden />
                  {item.label}
                </Link>
              ))}
              <button
                type="button"
                role="menuitem"
                disabled={signingOut}
                onClick={() => void signOut()}
                className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-60"
              >
                <LogOut className="size-4" aria-hidden />
                {signingOut ? "Signing out…" : "Sign out"}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
