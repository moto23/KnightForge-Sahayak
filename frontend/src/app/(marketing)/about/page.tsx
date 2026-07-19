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
    body: "Treat every form as data, not code. Each supported KYC form and document type is a schema describing its fields, aliases and rules — so the same pipeline reads a PAN card, an Aadhaar and a bank's KYC form, and adding another is a new schema rather than a new codebase.",
  },
  {
    icon: HeartHandshake,
    title: "The promise",
    body: "Sahayak means 'helper'. It shows where every value came from, flags what it couldn't verify instead of quietly filling it in, and always shows you the completed form before you sign it.",
  },
];

const TECHNICAL = [
  {
    term: "Schema-driven documents",
    detail:
      "Forms and identity documents are JSON schemas holding printed labels, aliases, value formats and validation hints. One extraction pipeline serves all of them.",
  },
  {
    term: "Hybrid extraction",
    detail:
      "OCR and layout analysis feed a deterministic label matcher, plus an optional AI pass that maps fields semantically when captions are worded differently.",
  },
  {
    term: "Canonical Profile",
    detail:
      "Values from every document merge into one profile — validated values first, then higher confidence — with the source document kept for each field.",
  },
  {
    term: "Deterministic validation",
    detail:
      "PAN format, Aadhaar checksum, IFSC, PIN codes and dates are checked in code, so an AI can never talk a malformed value through.",
  },
  {
    term: "Conflict resolution",
    detail:
      "When two documents disagree, nothing is silently overwritten — the conflict is surfaced and you choose the correct value.",
  },
  {
    term: "Provenance-aware edits",
    detail:
      "Delete a document and only the values it alone supported are withdrawn; anything another document or your own answer supports stays.",
  },
];

export default function AboutPage() {
  return (
    <div className="pt-16">
      <SectionShell
        eyebrow="About"
        title="Paperwork shouldn't require a translator"
        description="KnightForge Sahayak is an AI paperwork copilot built for the Codex Hackathon 2026. It takes the KYC form you actually have to submit — CVL/CDSL, SBI, HDFC, ICICI or Axis — reads the documents you already own, and gives you back a completed copy of that form."
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

        {/* Engineering detail lives here rather than in the product UI, where
            plain language matters more. */}
        <div className="mx-auto mt-14 max-w-3xl">
          <h2 className="text-base font-semibold">Under the hood</h2>
          <dl className="mt-4 grid gap-x-8 gap-y-4 sm:grid-cols-2">
            {TECHNICAL.map((item) => (
              <div key={item.term}>
                <dt className="text-sm font-medium">{item.term}</dt>
                <dd className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  {item.detail}
                </dd>
              </div>
            ))}
          </dl>
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
