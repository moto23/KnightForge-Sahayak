"use client";

import { motion } from "framer-motion";
import {
  FileOutput,
  Layers,
  MessageSquareText,
  ScanText,
  UploadCloud,
  type LucideIcon,
} from "lucide-react";

import { SectionShell } from "@/components/landing/section-shell";
import { Card } from "@/components/ui/card";
import { staggerContainer, fadeUp, viewportOnce } from "@/lib/motion";

const STEPS: { icon: LucideIcon; title: string; description: string }[] = [
  {
    icon: UploadCloud,
    title: "Your primary form",
    description:
      "Choose the KYC form you need to submit — CVL/CDSL, SBI, HDFC, ICICI or Axis — and upload your copy.",
  },
  {
    icon: Layers,
    title: "Supporting documents",
    description:
      "Add PAN, Aadhaar, passport, bank statement, utility bill and more — several at once. Each type is detected for you.",
  },
  {
    icon: ScanText,
    title: "Read & merged",
    description:
      "Sahayak reads each document and merges what it finds into one profile, tracking which document every value came from.",
  },
  {
    icon: MessageSquareText,
    title: "Asked only what's missing",
    description:
      "The AI-Guided Completion covers the gaps your form actually requires, while deterministic checks validate every answer.",
  },
  {
    icon: FileOutput,
    title: "Your completed form",
    description:
      "Answers are written onto a copy of the form you uploaded. Review it, edit, and save new versions as you go.",
  },
];

export function HowItWorks() {
  return (
    <SectionShell
      id="how-it-works"
      eyebrow="How it works"
      title="Five steps, and most of them run themselves"
      description="Sahayak does the reading, merging and rule-checking. You answer the handful of questions your documents couldn't."
    >
      <motion.ol
        variants={staggerContainer}
        initial="hidden"
        whileInView="visible"
        viewport={viewportOnce}
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5"
      >
        {STEPS.map((step, i) => (
          <motion.li key={step.title} variants={fadeUp} className="h-full">
            <Card className="group relative h-full p-5 transition-all duration-300 hover:-translate-y-1 hover:border-primary/50 hover:shadow-lg">
              <span className="absolute right-4 top-4 text-3xl font-bold text-muted-foreground/20 transition-colors group-hover:text-primary/30">
                {i + 1}
              </span>
              <span className="mb-4 grid size-11 place-items-center rounded-xl bg-gradient-to-br from-primary/15 to-accent/15 text-primary">
                <step.icon className="size-5.5" aria-hidden />
              </span>
              <h3 className="text-sm font-semibold">{step.title}</h3>
              <p className="mt-1.5 text-sm text-muted-foreground">
                {step.description}
              </p>
            </Card>
          </motion.li>
        ))}
      </motion.ol>
    </SectionShell>
  );
}
