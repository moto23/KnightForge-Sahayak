"use client";

import { ThemeProvider } from "next-themes";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "@/contexts/auth-context";

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
      <AuthProvider>
        <TooltipProvider delayDuration={200}>{children}</TooltipProvider>
        <Toaster />
      </AuthProvider>
    </ThemeProvider>
  );
}
