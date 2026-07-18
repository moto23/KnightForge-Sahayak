"use client";

import { motion } from "framer-motion";
import {
  AlertTriangle,
  CheckCircle2,
  Inbox,
  RotateCcw,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Shared frame for empty / error / success panels. */
function StateFrame({
  icon: Icon,
  iconClass,
  title,
  description,
  action,
  className,
}: {
  icon: LucideIcon;
  iconClass: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      role="status"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border p-8 text-center sm:p-12",
        className,
      )}
    >
      <span
        className={cn(
          "grid size-14 place-items-center rounded-2xl",
          iconClass,
        )}
      >
        <Icon className="size-7" aria-hidden />
      </span>
      <div className="space-y-1">
        <p className="text-base font-semibold">{title}</p>
        {description && (
          <p className="mx-auto max-w-sm text-sm text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {action}
    </motion.div>
  );
}

export function EmptyState(props: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <StateFrame
      icon={Inbox}
      iconClass="bg-muted text-muted-foreground"
      {...props}
    />
  );
}

export function ErrorState({
  onRetry,
  ...props
}: {
  title: string;
  description?: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <StateFrame
      icon={AlertTriangle}
      iconClass="bg-destructive/10 text-destructive"
      action={
        onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RotateCcw /> Try again
          </Button>
        )
      }
      {...props}
    />
  );
}

export function SuccessState(props: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <StateFrame
      icon={CheckCircle2}
      iconClass="bg-success/10 text-success"
      {...props}
    />
  );
}

/** Full-panel loading animation: orbiting dots around the brand glow. */
export function LoadingAnimation({
  label = "Loading…",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex flex-col items-center justify-center gap-4 p-10",
        className,
      )}
    >
      <span className="relative grid size-14 place-items-center">
        <span className="absolute inset-0 rounded-full bg-primary/15 animate-pulse-glow" />
        <motion.span
          className="absolute inset-0 rounded-full border-2 border-transparent border-t-primary border-r-accent"
          animate={{ rotate: 360 }}
          transition={{ duration: 1.1, repeat: Infinity, ease: "linear" }}
        />
        <span className="size-2.5 rounded-full bg-gradient-to-r from-primary to-accent" />
      </span>
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  );
}
