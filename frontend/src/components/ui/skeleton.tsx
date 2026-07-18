import { cn } from "@/lib/utils";

/** Shimmering placeholder block for perceived-fast loading states. */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden
      className={cn("shimmer-bg rounded-lg", className)}
      {...props}
    />
  );
}

/** Ready-made skeleton for a card row (avatar + two lines). */
function SkeletonRow({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <Skeleton className="size-10 rounded-full" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-3.5 w-2/5" />
        <Skeleton className="h-3 w-3/5" />
      </div>
    </div>
  );
}

export { Skeleton, SkeletonRow };
