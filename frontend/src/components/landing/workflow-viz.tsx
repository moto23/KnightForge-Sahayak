"use client";

import { motion } from "framer-motion";
import { ArrowRight, Braces, Cpu, Database, FileText, Layers } from "lucide-react";

import { SectionShell } from "@/components/landing/section-shell";
import { Badge } from "@/components/ui/badge";
import { GlassCard } from "@/components/ui/card";
import { WORKFLOW_STEPS } from "@/lib/navigation";
import { fadeUp, staggerContainer, viewportOnce } from "@/lib/motion";

/** Animated end-to-end AI workflow pipeline visualization. */
export function WorkflowViz() {
  return (
    <SectionShell
      eyebrow="AI workflow"
      title="Watch a document become a finished form"
      description="Every stage hands validated, structured data to the next — the PDF is generated only from answers you approved."
    >
      <GlassCard glow className="p-6 sm:p-10">
        <motion.ol
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          className="flex flex-col items-stretch gap-3 lg:flex-row lg:items-center"
        >
          {WORKFLOW_STEPS.map((step, i) => (
            <motion.li
              key={step.key}
              variants={fadeUp}
              className="flex flex-1 flex-col items-center gap-3 lg:flex-row"
            >
              <div className="w-full rounded-xl border border-border bg-card/70 p-4 text-center transition-colors hover:border-primary/50 lg:text-left">
                <p className="text-sm font-semibold">{step.label}</p>
                <p className="mt-1 text-xs text-muted-foreground">{step.detail}</p>
              </div>
              {i < WORKFLOW_STEPS.length - 1 && (
                <motion.span
                  aria-hidden
                  className="text-primary max-lg:rotate-90"
                  animate={{ x: [0, 4, 0] }}
                  transition={{
                    duration: 1.6,
                    repeat: Infinity,
                    delay: i * 0.25,
                    ease: "easeInOut",
                  }}
                >
                  <ArrowRight className="size-5" />
                </motion.span>
              )}
            </motion.li>
          ))}
        </motion.ol>
        <p className="mt-6 text-center text-xs text-muted-foreground">
          Single source of truth: the final PDF is rendered from your validated
          answers — never straight from OCR.
        </p>
      </GlassCard>
    </SectionShell>
  );
}

const STACK = [
  { icon: Layers, label: "Next.js + TypeScript", detail: "App Router frontend" },
  { icon: Cpu, label: "FastAPI", detail: "Typed Python backend" },
  { icon: FileText, label: "OCR + PDF engines", detail: "Local document pipeline" },
  { icon: Braces, label: "Deterministic rules", detail: "Verhoeff, regex, schemas" },
  { icon: Database, label: "Clean architecture", detail: "Ports & adapters, swappable" },
];

export function TechStack() {
  return (
    <SectionShell
      eyebrow="Under the hood"
      title="A real engineering stack, not a demo hack"
    >
      <motion.ul
        variants={staggerContainer}
        initial="hidden"
        whileInView="visible"
        viewport={viewportOnce}
        className="mx-auto flex max-w-4xl flex-wrap items-center justify-center gap-3"
      >
        {STACK.map((item) => (
          <motion.li key={item.label} variants={fadeUp}>
            <Badge
              variant="outline"
              className="gap-2 rounded-xl px-4 py-2.5 text-sm hover:border-primary/50"
            >
              <item.icon className="size-4 text-primary" aria-hidden />
              <span className="font-medium text-foreground">{item.label}</span>
              <span className="hidden text-muted-foreground sm:inline">
                · {item.detail}
              </span>
            </Badge>
          </motion.li>
        ))}
      </motion.ul>
    </SectionShell>
  );
}
