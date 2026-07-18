"use client";

import { useTheme } from "next-themes";
import { Toaster as Sonner, type ToasterProps } from "sonner";

/** App-wide toast host, themed to match the design system. */
function Toaster(props: ToasterProps) {
  const { resolvedTheme } = useTheme();

  return (
    <Sonner
      theme={(resolvedTheme as ToasterProps["theme"]) ?? "dark"}
      position="bottom-right"
      toastOptions={{
        classNames: {
          toast:
            "glass rounded-xl! border-border! text-foreground! shadow-lg!",
          description: "text-muted-foreground!",
        },
      }}
      {...props}
    />
  );
}

export { Toaster };
