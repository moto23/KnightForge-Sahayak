import { KycSessionProvider } from "@/contexts/kyc-session-context";
import { AppShell } from "@/layouts/app-shell";

export default function AppGroupLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <KycSessionProvider>
      <AppShell>{children}</AppShell>
    </KycSessionProvider>
  );
}
