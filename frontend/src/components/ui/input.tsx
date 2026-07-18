import * as React from "react";

import { cn } from "@/lib/utils";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "flex h-10 w-full rounded-lg border border-input bg-card px-3.5 py-2 text-sm text-foreground shadow-xs transition-colors",
        "placeholder:text-muted-foreground",
        "focus-visible:border-ring focus-visible:outline-2 focus-visible:outline-ring/60",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "aria-invalid:border-destructive aria-invalid:outline-destructive/50",
        className,
      )}
      {...props}
    />
  );
}

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex min-h-20 w-full rounded-lg border border-input bg-card px-3.5 py-2.5 text-sm text-foreground shadow-xs transition-colors",
        "placeholder:text-muted-foreground",
        "focus-visible:border-ring focus-visible:outline-2 focus-visible:outline-ring/60",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export { Input, Textarea };
