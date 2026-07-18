import { cn } from "@/lib/utils";

export type TimelineItem = {
  id: string;
  title: string;
  description?: string;
  time?: string;
  tone?: "default" | "success" | "accent" | "warning";
};

const DOT_TONES: Record<NonNullable<TimelineItem["tone"]>, string> = {
  default: "bg-primary",
  success: "bg-success",
  accent: "bg-accent",
  warning: "bg-warning",
};

/** Vertical activity timeline (dashboard "recent activity", audit trails). */
export function Timeline({
  items,
  className,
}: {
  items: TimelineItem[];
  className?: string;
}) {
  return (
    <ol className={cn("relative space-y-5 pl-5", className)}>
      <span
        aria-hidden
        className="absolute left-[5px] top-1.5 h-[calc(100%-12px)] w-px bg-border"
      />
      {items.map((item) => (
        <li key={item.id} className="relative">
          <span
            aria-hidden
            className={cn(
              "absolute -left-5 top-1.5 size-[11px] rounded-full ring-4 ring-background",
              DOT_TONES[item.tone ?? "default"],
            )}
          />
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
            <p className="text-sm font-medium">{item.title}</p>
            {item.time && (
              <time className="text-xs text-muted-foreground">{item.time}</time>
            )}
          </div>
          {item.description && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {item.description}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
