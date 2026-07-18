"use client";

import { motion } from "framer-motion";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { clampPercent } from "@/utils/format";

/**
 * Progress Card — animated ring + linear bar summarizing form completion.
 * Used on the dashboard and progress pages.
 */
export function ProgressCard({
  title,
  percent,
  answered,
  total,
  className,
}: {
  title: string;
  percent: number;
  answered: number;
  total: number;
  className?: string;
}) {
  const value = clampPercent(percent);
  const R = 30;
  const CIRC = 2 * Math.PI * R;

  return (
    <Card className={cn("overflow-hidden", className)}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex items-center gap-5">
        {/* Animated progress ring */}
        <svg
          viewBox="0 0 72 72"
          className="size-18 shrink-0 -rotate-90"
          role="img"
          aria-label={`${value}% complete`}
        >
          <circle
            cx="36"
            cy="36"
            r={R}
            fill="none"
            strokeWidth="7"
            className="stroke-muted"
          />
          <motion.circle
            cx="36"
            cy="36"
            r={R}
            fill="none"
            strokeWidth="7"
            strokeLinecap="round"
            className="stroke-primary"
            strokeDasharray={CIRC}
            initial={{ strokeDashoffset: CIRC }}
            animate={{ strokeDashoffset: CIRC * (1 - value / 100) }}
            transition={{ duration: 1.1, ease: [0.22, 1, 0.36, 1] }}
          />
        </svg>
        <div className="min-w-0 flex-1 space-y-2">
          <p className="text-2xl font-bold tabular-nums tracking-tight">
            {value}%
          </p>
          <Progress value={value} aria-hidden />
          <p className="text-xs text-muted-foreground">
            {answered} of {total} required fields complete
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
