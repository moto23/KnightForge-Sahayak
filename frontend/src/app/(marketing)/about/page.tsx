import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, Compass, HeartHandshake, Target } from "lucide-react";

import { SectionShell } from "@/components/landing/section-shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export const metadata: Metadata = {
  title: "About",
  description:
    "Why KnightForge Sahayak exists and how it turns paperwork into a conversation.",
};

const VALUES = [
  {
    icon: Target,
    title: "The problem",
    body: "Millions of KYC forms are rejected for trivial errors — a stray digit in a PAN, a date in the wrong boxes, a missed checkbox. The cost lands on the people least equipped to fight bureaucracy.",
  },
  {
    icon: Compass,
    title: "The approach",
    body: "Treat the form as software: a typed schema, deterministic validation, OCR with honest confidence scores, and an AI interviewer that only asks what's actually missing.",
  },
  {
    icon: HeartHandshake,
    title: "The promise",
    body: "Sahayak means 'helper'. It never guesses on your behalf, never sends your documents anywhere, and always shows you the finished form before you sign it.",
  },
];

export default function AboutPage() {
  return (
    <div className="pt-16">
      <SectionShell
        eyebrow="About"
        title="Paperwork shouldn't require a translator"
        description="KnightForge Sahayak is an AI paperwork copilot built for the Codex Hackathon 2026 — starting with the one form nearly every Indian investor has to fight through: the CVL Individual KYC."
      >
        <div className="mx-auto grid max-w-5xl gap-4 md:grid-cols-3">
          {VALUES.map((value) => (
            <Card key={value.title} className="p-6">
              <span className="mb-4 inline-grid size-11 place-items-center rounded-xl bg-gradient-to-br from-primary/15 to-accent/15 text-primary">
                <value.icon className="size-5.5" aria-hidden />
              </span>
              <h2 className="text-base font-semibold">{value.title}</h2>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {value.body}
              </p>
            </Card>
          ))}
        </div>

        <div className="mt-14 text-center">
          <Button variant="gradient" size="lg" asChild>
            <Link href="/dashboard">
              Explore the workspace <ArrowRight aria-hidden />
            </Link>
          </Button>
        </div>
      </SectionShell>
    </div>
  );
}
