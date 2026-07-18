"use client";

import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

export type Step = {
  key: string;
  label: string;
  detail?: string;
};

/**
 * Workflow stepper (Upload → OCR → AI → Validation → PDF).
 * Horizontal on ≥sm screens, vertical on mobile. Purely presentational.
 */
export function Stepper({
  steps,
  activeIndex,
  className,
}: {
  steps: readonly Step[];
  activeIndex: number;
  className?: string;
}) {
  return (
    <ol
      className={cn(
        "flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-0",
        className,
      )}
      aria-label="Workflow progress"
    >
      {steps.map((step, i) => {
        const state =
          i < activeIndex ? "done" : i === activeIndex ? "active" : "todo";
        return (
          <li
            key={step.key}
            className="relative flex flex-1 items-start gap-3 sm:flex-col sm:items-center sm:gap-2 sm:text-center"
            aria-current={state === "active" ? "step" : undefined}
          >
            {/* Connector line to the next step */}
            {i < steps.length - 1 && (
              <span
                aria-hidden
                className={cn(
                  "absolute left-[15px] top-8 h-[calc(100%-16px)] w-px sm:left-[calc(50%+20px)] sm:top-[15px] sm:h-px sm:w-[calc(100%-40px)]",
                  i < activeIndex ? "bg-primary" : "bg-border",
                )}
              />
            )}
            <span
              className={cn(
                "z-10 grid size-8 shrink-0 place-items-center rounded-full border text-xs font-semibold transition-colors",
                state === "done" &&
                  "border-primary bg-primary text-primary-foreground",
                state === "active" &&
                  "border-primary bg-primary/15 text-primary glow-primary",
                state === "todo" &&
                  "border-border bg-card text-muted-foreground",
              )}
            >
              {state === "done" ? <Check className="size-4" aria-hidden /> : i + 1}
            </span>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span
                className={cn(
                  "text-sm font-medium",
                  state === "todo" && "text-muted-foreground",
                )}
              >
                {step.label}
              </span>
              {step.detail && (
                <span className="hidden text-xs text-muted-foreground md:block">
                  {step.detail}
                </span>
              )}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
