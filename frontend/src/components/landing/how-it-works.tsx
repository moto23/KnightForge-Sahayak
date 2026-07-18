"use client";

import { motion } from "framer-motion";
import {
  FileOutput,
  MessageSquareText,
  ScanText,
  ShieldCheck,
  UploadCloud,
  type LucideIcon,
} from "lucide-react";

import { SectionShell } from "@/components/landing/section-shell";
import { Card } from "@/components/ui/card";
import { staggerContainer, fadeUp, viewportOnce } from "@/lib/motion";

const STEPS: { icon: LucideIcon; title: string; description: string }[] = [
  {
    icon: UploadCloud,
    title: "Upload",
    description: "Drop any KYC scan or ID document — PDF or photo.",
  },
  {
    icon: ScanText,
    title: "OCR",
    description: "Text is read locally and mapped to real form fields.",
  },
  {
    icon: MessageSquareText,
    title: "AI Interview",
    description: "A friendly chat asks only what's still missing.",
  },
  {
    icon: ShieldCheck,
    title: "Validation",
    description: "PAN, Aadhaar, PIN — every field checked deterministically.",
  },
  {
    icon: FileOutput,
    title: "PDF",
    description: "Your answers are placed pixel-perfectly onto the official form.",
  },
];

export function HowItWorks() {
  return (
    <SectionShell
      id="how-it-works"
      eyebrow="How it works"
      title="Five steps. Zero form anxiety."
      description="Sahayak does the reading, remembering and rule-checking — you just answer questions in plain language."
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
