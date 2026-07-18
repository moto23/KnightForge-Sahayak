import * as React from "react";

import { cn } from "@/lib/utils";

/** Standard opaque surface — the default card for content-dense areas. */
function Card({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card"
      className={cn(
        "rounded-xl border border-border bg-card text-card-foreground shadow-sm",
        className,
      )}
      {...props}
    />
  );
}

/**
 * GlassCard — frosted, glowing surface. Used with restraint: navigation,
 * dialogs and hero/key cards only (readability & perf over decoration).
 */
function GlassCard({
  className,
  glow = false,
  ...props
}: React.ComponentProps<"div"> & { glow?: boolean }) {
  return (
    <div
      data-slot="glass-card"
      className={cn("glass rounded-2xl", glow && "glow-primary", className)}
      {...props}
    />
  );
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn("flex flex-col gap-1.5 p-5 sm:p-6", className)}
      {...props}
    />
  );
}

function CardTitle({ className, ...props }: React.ComponentProps<"h3">) {
  return (
    <h3
      data-slot="card-title"
      className={cn("text-base font-semibold leading-tight tracking-tight", className)}
      {...props}
    />
  );
}

function CardDescription({ className, ...props }: React.ComponentProps<"p">) {
  return (
    <p
      data-slot="card-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-content"
      className={cn("p-5 pt-0 sm:p-6 sm:pt-0", className)}
      {...props}
    />
  );
}

function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={cn("flex items-center gap-3 p-5 pt-0 sm:p-6 sm:pt-0", className)}
      {...props}
    />
  );
}

export { Card, GlassCard, CardHeader, CardTitle, CardDescription, CardContent, CardFooter };
