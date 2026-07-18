"use client";

import { motion } from "framer-motion";

import { fadeUp, viewportOnce } from "@/lib/motion";
import { cn } from "@/lib/utils";

/** Consistent scroll-animated wrapper + heading for landing sections. */
export function SectionShell({
  id,
  eyebrow,
  title,
  description,
  children,
  className,
}: {
  id?: string;
  eyebrow: string;
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={cn("scroll-mt-24 py-16 sm:py-24", className)}>
      <div className="mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8">
        <motion.div
          variants={fadeUp}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          className="mx-auto mb-12 max-w-2xl text-center sm:mb-16"
        >
          <p className="text-gradient mb-3 text-sm font-semibold uppercase tracking-widest">
            {eyebrow}
          </p>
          <h2 className="text-balance text-3xl font-bold tracking-tight sm:text-4xl">
            {title}
          </h2>
          {description && (
            <p className="mt-4 text-pretty text-base text-muted-foreground sm:text-lg">
              {description}
            </p>
          )}
        </motion.div>
        {children}
      </div>
    </section>
  );
}
