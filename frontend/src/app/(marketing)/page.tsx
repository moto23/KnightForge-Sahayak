import type { Metadata } from "next";

import { Faq } from "@/components/landing/faq";
import { Features } from "@/components/landing/features";
import { Hero } from "@/components/landing/hero";
import { HowItWorks } from "@/components/landing/how-it-works";
import { TechStack, WorkflowViz } from "@/components/landing/workflow-viz";
import { Security, WhySahayak } from "@/components/landing/why-and-security";

export const metadata: Metadata = {
  title: "KnightForge Sahayak — Turn Complex KYC Forms into a Guided AI Experience",
};

export default function LandingPage() {
  return (
    <>
      <Hero />
      <HowItWorks />
      <Features />
      <WhySahayak />
      <Security />
      <WorkflowViz />
      <TechStack />
      <Faq />
    </>
  );
}
