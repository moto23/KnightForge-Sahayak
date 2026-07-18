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

const STATS = [
  { value: "21", label: "required fields handled for you" },
  { value: "70%+", label: "typically prefilled from one scan" },
  { value: "11", label: "deterministic validation rules" },
  { value: "<1 min", label: "from last answer to filled PDF" },
];

export function WhySahayak() {
  return (
    <SectionShell
      eyebrow="Why KnightForge Sahayak"
      title="Forms are hostile. Your copilot isn't."
      description="KYC rejections usually come from tiny mistakes — a malformed PAN, a missed checkbox, a wrong date format. Sahayak makes those mistakes impossible."
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

const SECURITY_POINTS = [
  {
    icon: HardDrive,
    title: "Local-first processing",
    description: "OCR and PDF generation run on your machine — documents never leave it.",
  },
  {
    icon: EyeOff,
    title: "No silent guessing",
    description: "Low-confidence extractions are asked, not assumed. You approve every value.",
  },
  {
    icon: ShieldCheck,
    title: "Deterministic checks",
    description: "Validation is code — Aadhaar checksums and PAN formats can't be hallucinated.",
  },
  {
    icon: ServerOff,
    title: "No tracking, no ads",
    description: "There is no analytics pixel watching you fill in your PAN number.",
  },
  {
    icon: Lock,
    title: "Your session, your data",
    description: "Delete a session and its documents and generated PDFs go with it.",
  },
  {
    icon: TimerReset,
    title: "Nothing retained",
    description: "Uploads exist only for the lifetime of your form-filling session.",
  },
];

export function Security() {
  return (
    <SectionShell
      id="security"
      eyebrow="Security & privacy"
      title="Built like it's handling your identity — because it is"
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
