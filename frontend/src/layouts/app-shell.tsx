"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { Menu, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";

import { BackendStatusBanner } from "@/components/shared/backend-status-banner";
import { ProfileMenu } from "@/components/navigation/profile-menu";
import { SidebarNav } from "@/components/navigation/sidebar";
import { ThemeToggle } from "@/components/shared/theme-toggle";
import { Button } from "@/components/ui/button";
import { APP_NAV } from "@/lib/navigation";

/** localStorage key for the desktop sidebar collapsed preference. */
const SIDEBAR_COLLAPSED_KEY = "kf.sidebar.collapsed";

/*
 * Collapsed-state store (Phase 13). useSyncExternalStore instead of
 * useState+useEffect: hydration-safe (server snapshot = expanded, client
 * snapshot applied on hydration without a mismatch) and no setState-in-effect.
 */
const collapsedListeners = new Set<() => void>();

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function subscribeCollapsed(listener: () => void): () => void {
  collapsedListeners.add(listener);
  return () => collapsedListeners.delete(listener);
}

function writeCollapsed(next: boolean) {
  try {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? "1" : "0");
  } catch {
    /* private mode / storage full — preference just won't persist */
  }
  collapsedListeners.forEach((listener) => listener());
}

/**
 * Authenticated workspace shell: fixed sidebar on ≥lg (collapsible to an
 * icon rail, preference persisted), slide-over drawer on mobile, sticky
 * glass topbar, and animated page transitions.
 *
 * Future modules (RAG chat panel, agent panel, admin, analytics) mount as new
 * routes + one nav entry — no restructuring needed.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const collapsed = React.useSyncExternalStore(
    subscribeCollapsed,
    readCollapsed,
    () => false,
  );
  const pathname = usePathname();

  const toggleCollapsed = React.useCallback(() => {
    writeCollapsed(!readCollapsed());
  }, []);

  const currentPage = APP_NAV.flatMap((s) => s.items).find(
    (item) => item.href === pathname,
  );

  return (
    <div className="flex min-h-dvh w-full">
      {/* Skip link for keyboard users */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:text-primary-foreground"
      >
        Skip to content
      </a>

      {/* Desktop sidebar — collapsible icon rail */}
      <aside
        className={`fixed inset-y-0 left-0 z-30 hidden border-r border-border bg-card/60 transition-[width] duration-200 lg:block ${collapsed ? "w-16" : "w-64"}`}
      >
        <SidebarNav collapsed={collapsed} />
      </aside>

      {/* Mobile drawer */}
      <AnimatePresence>
        {drawerOpen && (
          <>
            <motion.button
              type="button"
              aria-label="Close navigation"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setDrawerOpen(false)}
              className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
            />
            <motion.aside
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "tween", duration: 0.25, ease: "easeOut" }}
              className="glass fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] lg:hidden"
              aria-label="Navigation drawer"
            >
              <Button
                variant="ghost"
                size="icon"
                aria-label="Close menu"
                className="absolute right-3 top-3.5"
                onClick={() => setDrawerOpen(false)}
              >
                <X className="size-5" />
              </Button>
              <SidebarNav onNavigate={() => setDrawerOpen(false)} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      {/* Main column */}
      <div
        className={`flex min-w-0 flex-1 flex-col transition-[padding] duration-200 ${collapsed ? "lg:pl-16" : "lg:pl-64"}`}
      >
        {/* Topbar */}
        <header className="glass sticky top-0 z-20 flex h-16 items-center gap-3 px-4 sm:px-6">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            aria-label="Open navigation"
            onClick={() => setDrawerOpen(true)}
          >
            <Menu className="size-5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="hidden text-muted-foreground lg:inline-flex"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={toggleCollapsed}
          >
            {collapsed ? (
              <PanelLeftOpen className="size-5" />
            ) : (
              <PanelLeftClose className="size-5" />
            )}
          </Button>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold sm:text-base">
              {currentPage?.title ?? "Workspace"}
            </p>
            {currentPage?.description && (
              <p className="hidden truncate text-xs text-muted-foreground sm:block">
                {currentPage.description}
              </p>
            )}
          </div>
          <ThemeToggle />
          <ProfileMenu />
        </header>

        {/* Cold-start explainer — silent while the backend is warm. */}
        <BackendStatusBanner />

        {/* Animated page content */}
        <main id="main-content" className="flex-1">
          <AnimatePresence mode="wait">
            <motion.div
              key={pathname}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
              className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8 lg:px-8"
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}
