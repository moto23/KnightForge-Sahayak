"use client";

import * as React from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, ChevronDown } from "lucide-react";

import { SectionShell } from "@/components/landing/section-shell";
import { Button } from "@/components/ui/button";
import { GlassCard } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const FAQS = [
  {
    q: "Which forms does Sahayak support today?",
    a: "Five KYC forms can be set as your primary form: CVL/CDSL, SBI, HDFC, ICICI and Axis. Each one brings its own required fields and conditional questions. The architecture is schema-driven, so additional forms are added as data rather than code.",
  },
  {
    q: "What can I upload as supporting documents?",
    a: "PAN, Aadhaar, passport, driving licence, bank statement, utility bill, voter ID, ration card and other address proofs — several at once. You don't pick the type: Sahayak classifies each document, extracts what it can read, and merges the results into one profile.",
  },
  {
    q: "Do my documents get uploaded to the cloud?",
    a: "Your files stay on the Sahayak backend you deploy — they aren't sent to a third-party document service. When AI assistance is enabled, the text extracted from your documents (not the files themselves) is sent to Google Gemini so it can read fields semantically and answer questions. Without an AI key, Sahayak falls back to deterministic extraction and still works end to end.",
  },
  {
    q: "What if something is read incorrectly?",
    a: "Every extracted value carries a source document, a confidence score and a validation result. Values that fail validation are shown and flagged rather than filled in, and when two documents disagree you're asked to choose. Nothing is generated until you've reviewed the profile.",
  },
  {
    q: "Can I fill the form without uploading anything?",
    a: "Yes. Skip the uploads and the AI-Guided Completion walks you through the fields your chosen form requires, one question at a time.",
  },
  {
    q: "Is the generated PDF actually my form?",
    a: "Yes — when you upload your primary form, Sahayak fills a copy of that exact file. Its layout, fonts and legal text are untouched; only your answers are added. Your original upload is preserved, and each generation is saved as a new version so earlier ones remain available.",
  },
];

function FaqItem({
  q,
  a,
  open,
  onToggle,
  id,
}: {
  q: string;
  a: string;
  open: boolean;
  onToggle: () => void;
  id: string;
}) {
  return (
    <div className="border-b border-border last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={`${id}-panel`}
        className="flex w-full items-center justify-between gap-4 py-5 text-left text-sm font-medium transition-colors hover:text-primary sm:text-base"
      >
        {q}
        <ChevronDown
          aria-hidden
          className={cn(
            "size-4.5 shrink-0 text-muted-foreground transition-transform duration-300",
            open && "rotate-180 text-primary",
          )}
        />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={`${id}-panel`}
            role="region"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.28, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <p className="pb-5 pr-8 text-sm leading-relaxed text-muted-foreground">
              {a}
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function Faq() {
  const [openIndex, setOpenIndex] = React.useState<number | null>(0);

  return (
    <SectionShell id="faq" eyebrow="FAQ" title="Questions, answered">
      <div className="mx-auto max-w-3xl">
        <GlassCard className="px-6 sm:px-8">
          {FAQS.map((faq, i) => (
            <FaqItem
              key={faq.q}
              id={`faq-${i}`}
              q={faq.q}
              a={faq.a}
              open={openIndex === i}
              onToggle={() => setOpenIndex(openIndex === i ? null : i)}
            />
          ))}
        </GlassCard>

        {/* Final CTA */}
        <motion.div
          initial={{ opacity: 0, y: 14 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="mt-16 text-center"
        >
          <h3 className="text-balance text-2xl font-bold tracking-tight sm:text-3xl">
            Ready to never dread a form again?
          </h3>
          <p className="mx-auto mt-3 max-w-md text-muted-foreground">
            Upload one document and watch your KYC fill itself.
          </p>
          <Button variant="gradient" size="lg" className="mt-6" asChild>
            <Link href="/upload">
              Get started free <ArrowRight aria-hidden />
            </Link>
          </Button>
        </motion.div>
      </div>
    </SectionShell>
  );
}
