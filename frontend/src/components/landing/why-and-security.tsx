"use client";

import { motion } from "framer-motion";
import {
  EyeOff,
  HardDrive,
  Lock,
  ServerOff,
  ShieldCheck,
  TimerReset,
} from "lucide-react";

import { SectionShell } from "@/components/landing/section-shell";
import { Card, GlassCard } from "@/components/ui/card";
import { fadeUp, staggerContainer, viewportOnce } from "@/lib/motion";

/**
 * Every figure here must be verifiable from the shipped product — a demo is
 * not the place for invented metrics. Counts match the installed form and
 * document schemas; the qualitative ones describe behaviour you can observe.
 */
const STATS = [
  { value: "5", label: "KYC forms supported as your primary form" },
  { value: "9+", label: "supporting document types detected automatically" },
  { value: "Per form", label: "required fields — not one fixed checklist" },
  { value: "Cited", label: "every knowledge answer links to its source" },
];

export function WhySahayak() {
  return (
    <SectionShell
      eyebrow="Why KnightForge Sahayak"
      title="Forms are hostile. Your copilot isn't."
      description="KYC rejections usually come from small mistakes — a malformed PAN, a missed checkbox, a date in the wrong format. Sahayak checks each one as you go and asks when it isn't sure."
    >
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        whileInView="visible"
        viewport={viewportOnce}
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        {STATS.map((stat) => (
          <motion.div key={stat.label} variants={fadeUp}>
            <Card className="h-full p-6 text-center">
              <p className="text-gradient text-3xl font-bold tracking-tight sm:text-4xl">
                {stat.value}
              </p>
              <p className="mt-2 text-sm text-muted-foreground">{stat.label}</p>
            </Card>
          </motion.div>
        ))}
      </motion.div>
    </SectionShell>
  );
}

/**
 * Only claims the current architecture can actually stand behind. Sahayak
 * runs on a backend you deploy, and when AI assistance is enabled the
 * EXTRACTED TEXT is sent to Google Gemini — so "nothing ever leaves your
 * machine" would be untrue. Saying so plainly is worth more than a
 * comfortable promise.
 */
const SECURITY_POINTS = [
  {
    icon: HardDrive,
    title: "Runs on your own backend",
    description:
      "Uploads, OCR, validation and PDF generation happen on the Sahayak server you deploy — not a third-party document service.",
  },
  {
    icon: ServerOff,
    title: "AI sees text, never your files",
    description:
      "With AI enabled, only extracted text is sent to Google Gemini for reading and answering. Your original scans stay on your backend.",
  },
  {
    icon: TimerReset,
    title: "Works without AI too",
    description:
      "No AI key configured? Extraction falls back to deterministic schema matching and the workflow keeps running end to end.",
  },
  {
    icon: EyeOff,
    title: "No silent guessing",
    description:
      "Values that fail validation are shown and flagged rather than filled in. Conflicting documents ask you to choose.",
  },
  {
    icon: ShieldCheck,
    title: "Deterministic checks",
    description:
      "PAN format, Aadhaar checksum, IFSC, PIN and dates are verified in code — rules an AI cannot talk its way around.",
  },
  {
    icon: Lock,
    title: "You control what's kept",
    description:
      "Delete a document and every value only it supported disappears everywhere. Delete the session to remove its data.",
  },
];

export function Security() {
  return (
    <SectionShell
      id="security"
      eyebrow="Security & privacy"
      title="Built like it's handling your identity — because it is"
      description="Straight answers about where your documents go and what the system can actually promise."
    >
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        whileInView="visible"
        viewport={viewportOnce}
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        {SECURITY_POINTS.map((point) => (
          <motion.div key={point.title} variants={fadeUp} className="h-full">
            <GlassCard className="h-full p-6">
              <span className="mb-3 inline-grid size-10 place-items-center rounded-lg bg-success/10 text-success">
                <point.icon className="size-5" aria-hidden />
              </span>
              <h3 className="text-sm font-semibold">{point.title}</h3>
              <p className="mt-1.5 text-sm text-muted-foreground">
                {point.description}
              </p>
            </GlassCard>
          </motion.div>
        ))}
      </motion.div>
    </SectionShell>
  );
}
