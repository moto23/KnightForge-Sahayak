import Link from "next/link";
import { Compass } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="bg-grid flex min-h-dvh flex-col items-center justify-center gap-6 px-4 text-center">
      <span className="grid size-16 place-items-center rounded-2xl bg-gradient-to-br from-primary/15 to-accent/15 text-primary">
        <Compass className="size-8" aria-hidden />
      </span>
      <div className="space-y-2">
        <p className="text-gradient text-5xl font-bold tracking-tight">404</p>
        <h1 className="text-xl font-semibold">This page wandered off the form</h1>
        <p className="mx-auto max-w-sm text-sm text-muted-foreground">
          The page you&apos;re looking for doesn&apos;t exist. Your KYC progress is safe.
        </p>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Button variant="gradient" asChild>
          <Link href="/dashboard">Go to dashboard</Link>
        </Button>
        <Button variant="outline" asChild>
          <Link href="/">Back to home</Link>
        </Button>
      </div>
    </div>
  );
}
