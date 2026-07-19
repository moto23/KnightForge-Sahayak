"use client";

import { motion } from "framer-motion";
import {
  Bot,
  FileSearch,
  Languages,
  ListChecks,
  MapPin,
  Wand2,
  type LucideIcon,
} from "lucide-react";

import { SectionShell } from "@/components/landing/section-shell";
import { Card } from "@/components/ui/card";
import { fadeUp, staggerContainer, viewportOnce } from "@/lib/motion";

const FEATURES: { icon: LucideIcon; title: string; description: string }[] = [
  {
    icon: FileSearch,
    title: "Detects and reads any of your documents",
    description:
      "Drop in several at once. Sahayak works out what each one is — PAN, Aadhaar, passport, bank statement and more — and merges what it reads into a single profile.",
  },
  {
    icon: Bot,
    title: "Conversational interview",
    description:
      "No field jargon. Sahayak asks one clear question at a time and understands answers like “between 10 and 25 lakhs”.",
  },
  {
    icon: ListChecks,
    title: "Deterministic validation",
    description:
      "PAN format, Aadhaar Verhoeff checksum, PIN codes, dates — every rule enforced by code, not vibes.",
  },
  {
    icon: MapPin,
    title: "Your own form, completed",
    description:
      "Answers are written onto a copy of the form you uploaded — text fields, checkboxes and date boxes — leaving the original untouched.",
  },
  {
    icon: Wand2,
    title: "Smart prefill, honest gaps",
    description:
      "Every value shows which document it came from. What can't be verified is flagged rather than filled in, and you review before anything reaches your form.",
  },
  {
    icon: Languages,
    title: "Made for real people",
    description:
      "Plain-language guidance designed for first-time filers, families and anyone who dreads paperwork.",
  },
];

export function Features() {
  return (
    <SectionShell
      id="features"
      eyebrow="Core features"
      title="Everything a form-filler wishes existed"
      description="A complete pipeline — understanding, conversation, verification and generation — behind one simple experience."
    >
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        whileInView="visible"
        viewport={viewportOnce}
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        {FEATURES.map((feature) => (
          <motion.div key={feature.title} variants={fadeUp} className="h-full">
            <Card className="group h-full p-6 transition-all duration-300 hover:-translate-y-1 hover:border-primary/50 hover:shadow-lg">
              <span className="mb-4 inline-grid size-11 place-items-center rounded-xl bg-gradient-to-br from-primary/15 to-accent/15 text-primary transition-transform group-hover:scale-110">
                <feature.icon className="size-5.5" aria-hidden />
              </span>
              <h3 className="text-base font-semibold">{feature.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {feature.description}
              </p>
            </Card>
          </motion.div>
        ))}
      </motion.div>
    </SectionShell>
  );
}
