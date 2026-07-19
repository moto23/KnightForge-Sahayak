"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, CheckCircle2, FileCheck2, Sparkles } from "lucide-react";

import { ChatBubble } from "@/components/shared/chat-bubble";
import { GlassCard } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { fadeUp, staggerContainer } from "@/lib/motion";

/** Hero + live product demo preview. */
export function Hero() {
  return (
    <section className="bg-grid relative overflow-hidden pb-20 pt-32 sm:pb-28 sm:pt-40">
      {/* Ambient brand glow */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-[-20%] h-[32rem] w-[52rem] -translate-x-1/2 rounded-full bg-primary/20 blur-[140px] animate-pulse-glow"
      />

      <div className="relative mx-auto grid w-full max-w-7xl items-center gap-14 px-4 sm:px-6 lg:grid-cols-2 lg:gap-10 lg:px-8">
        {/* Copy */}
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
          className="text-center lg:text-left"
        >
          <motion.div variants={fadeUp}>
            <Badge variant="outline" className="mb-5 border-primary/40 py-1 pl-1.5 pr-3">
              <span className="rounded-full bg-primary/15 px-2 py-0.5 text-primary">New</span>
              AI Paperwork Copilot for Indian KYC
            </Badge>
          </motion.div>

          <motion.h1
            variants={fadeUp}
            className="text-balance text-4xl font-bold leading-[1.08] tracking-tight sm:text-5xl xl:text-6xl"
          >
            Turn Complex KYC Forms into a{" "}
            <span className="text-gradient">Guided AI Experience.</span>
          </motion.h1>

          <motion.p
            variants={fadeUp}
            className="mx-auto mt-5 max-w-xl text-pretty text-base text-muted-foreground sm:text-lg lg:mx-0"
          >
            Upload your KYC form and the documents you already have. Sahayak
            detects each one, prefills what it can verify, asks you only about
            the gaps — and returns a completed copy of your own form.
          </motion.p>

          <motion.div
            variants={fadeUp}
            className="mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center lg:justify-start"
          >
            <Button variant="gradient" size="lg" asChild>
              <Link href="/upload">
                Start your KYC <ArrowRight aria-hidden />
              </Link>
            </Button>
            <Button variant="outline" size="lg" asChild>
              <Link href="/#how-it-works">See how it works</Link>
            </Button>
          </motion.div>

          <motion.ul
            variants={fadeUp}
            className="mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-muted-foreground lg:justify-start"
          >
            {[
              "CVL, SBI, HDFC, ICICI & Axis",
              "Deterministic validation",
              "No form knowledge needed",
            ].map(
              (point) => (
                <li key={point} className="flex items-center gap-1.5">
                  <CheckCircle2 className="size-4 text-success" aria-hidden />
                  {point}
                </li>
              ),
            )}
          </motion.ul>
        </motion.div>

        {/* Product demo preview */}
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.25, ease: [0.22, 1, 0.36, 1] }}
          className="relative mx-auto w-full max-w-lg"
        >
          <GlassCard glow className="relative p-5 sm:p-6">
            {/* Window chrome */}
            <div className="mb-4 flex items-center justify-between">
              <div className="flex gap-1.5" aria-hidden>
                <span className="size-2.5 rounded-full bg-destructive/70" />
                <span className="size-2.5 rounded-full bg-warning/70" />
                <span className="size-2.5 rounded-full bg-success/70" />
              </div>
              <Badge variant="accent">
                <Sparkles aria-hidden /> AI-Guided Completion
              </Badge>
            </div>

            <div className="space-y-3">
              <ChatBubble role="assistant">
                I read your PAN and Aadhaar and filled in what they confirm.
                What is your gross annual income range?
              </ChatBubble>
              <ChatBubble role="user">Between 10 and 25 lakhs.</ChatBubble>
              <ChatBubble role="assistant">
                Got it — <strong>₹10–25 Lac</strong> ✓ validated. Just a couple
                of questions left.
              </ChatBubble>
            </div>

            <div className="mt-5 rounded-xl border border-border bg-card/70 p-3.5">
              <div className="mb-2 flex items-center justify-between text-xs">
                {/* Illustrative preview — the real workspace shows the form
                    you chose and its own required-field count. */}
                <span className="font-medium">Your KYC form</span>
                <span className="text-muted-foreground">Almost complete</span>
              </div>
              <Progress value={90} aria-label="Illustration: form 90% complete" />
            </div>
          </GlassCard>

          {/* Floating PDF-ready chip */}
          <motion.div
            aria-hidden
            className="absolute -bottom-5 -left-3 sm:-left-8"
            animate={{ y: [0, -8, 0] }}
            transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
          >
            <GlassCard className="flex items-center gap-2.5 rounded-xl px-3.5 py-2.5">
              <FileCheck2 className="size-5 text-success" />
              <div className="text-left">
                <p className="text-xs font-semibold">kyc-filled.pdf</p>
                <p className="text-[11px] text-muted-foreground">Ready to sign</p>
              </div>
            </GlassCard>
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}
