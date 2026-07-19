"use client";

import { ThemeProvider } from "next-themes";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "@/contexts/auth-context";
import { BackendStatusProvider } from "@/hooks/use-backend-status";

/**
 * Client-side app providers. Dark mode is the DEFAULT; next-themes toggles
 * the `.dark` class on <html> and persists the user's choice. AuthProvider
 * (Phase 12) restores a persisted login via the HttpOnly refresh cookie —
 * guests simply stay signed out and everything keeps working.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="dark"
      enableSystem={false}
      disableTransitionOnChange
    >
      {/*
        One backend probe for the whole app. Previously the shell banner and
        the dashboard pill each ran their own, which is how the UI managed to
        say "Waking up Sahayak" and "Backend offline" at the same time.
      */}
      <BackendStatusProvider>
        <AuthProvider>
          <TooltipProvider delayDuration={200}>{children}</TooltipProvider>
          <Toaster />
        </AuthProvider>
      </BackendStatusProvider>
    </ThemeProvider>
  );
}
