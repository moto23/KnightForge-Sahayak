import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap transition-colors [&_svg]:size-3",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary/15 text-primary",
        accent: "border-transparent bg-accent/15 text-accent",
        success: "border-transparent bg-success/15 text-success",
        warning: "border-transparent bg-warning/15 text-warning",
        destructive: "border-transparent bg-destructive/15 text-destructive",
        outline: "border-border text-muted-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return (
    <span
      data-slot="badge"
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  );
}

/* ------------------------------------------------------------------ */
/* StatusBadge — semantic wrapper used across dashboard/progress/upload */
/* ------------------------------------------------------------------ */

export type Status =
  | "answered"
  | "prefilled"
  | "pending"
  | "invalid"
  | "processing"
  | "completed"
  | "in_progress"
  | "uploaded"
  | "analyzed"
  | "failed";

const STATUS_CONFIG: Record<Status, { label: string; variant: NonNullable<VariantProps<typeof badgeVariants>["variant"]>; pulse?: boolean }> = {
  answered: { label: "Answered", variant: "success" },
  prefilled: { label: "AI Prefilled", variant: "accent" },
  pending: { label: "Pending", variant: "outline" },
  invalid: { label: "Needs fix", variant: "destructive" },
  processing: { label: "Processing", variant: "warning", pulse: true },
  completed: { label: "Completed", variant: "success" },
  in_progress: { label: "In progress", variant: "default", pulse: true },
  uploaded: { label: "Uploaded", variant: "default" },
  analyzed: { label: "Analyzed", variant: "success" },
  failed: { label: "Failed", variant: "destructive" },
};

function StatusBadge({
  status,
  className,
}: {
  status: Status;
  className?: string;
}) {
  const config = STATUS_CONFIG[status];
  return (
    <Badge variant={config.variant} className={className}>
      <span
        aria-hidden
        className={cn(
          "size-1.5 rounded-full bg-current",
          config.pulse && "animate-pulse-glow",
        )}
      />
      {config.label}
    </Badge>
  );
}

export { Badge, badgeVariants, StatusBadge };
