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
    a: "The MVP is laser-focused on the CVL Individual KYC form — the one everyone needs for mutual funds and demat accounts. The architecture is schema-driven, so new forms are added as data, not code.",
  },
  {
    q: "Do my documents get uploaded to the cloud?",
    a: "No. OCR, validation and PDF generation all run locally. Your Aadhaar and PAN never travel anywhere.",
  },
  {
    q: "What if the OCR reads something wrong?",
    a: "Every extracted value carries a confidence score and passes deterministic validation. Anything below the bar is never prefilled — the AI simply asks you instead, and you can review every field before generating the PDF.",
  },
  {
    q: "Can I fill the form without uploading anything?",
    a: "Absolutely. Skip the upload and the AI interview will walk you through all fields from scratch, one friendly question at a time.",
  },
  {
    q: "Is the generated PDF actually the official form?",
    a: "Yes — your answers are overlaid onto the original template. The layout, fonts and legal text are untouched; only your data is added, exactly where a pen would put it.",
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
