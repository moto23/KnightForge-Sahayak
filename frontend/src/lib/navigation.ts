/**
 * Single source of truth for app navigation.
 *
 * The sidebar, mobile drawer and command surfaces all render from this list,
 * so adding a future module (RAG chat, agent panel, admin, analytics) is one
 * entry here — no layout restructuring.
 */

import {
  BookOpenText,
  FileText,
  Info,
  LayoutDashboard,
  ListChecks,
  MessageSquareText,
  Settings,
  UploadCloud,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  title: string;
  href: string;
  icon: LucideIcon;
  description: string;
  /** Marks entries reserved for later phases (rendered as "Soon"). */
  comingSoon?: boolean;
};

export type NavSection = {
  label: string;
  items: NavItem[];
};

export const APP_NAV: NavSection[] = [
  {
    label: "Workspace",
    items: [
      {
        title: "Dashboard",
        href: "/dashboard",
        icon: LayoutDashboard,
        description: "Overview of your KYC journey",
      },
      {
        title: "Upload",
        href: "/upload",
        icon: UploadCloud,
        description: "Upload documents for OCR prefill",
      },
      {
        title: "AI-Guided Completion",
        href: "/interview",
        icon: MessageSquareText,
        description: "Answer the remaining fields conversationally",
      },
      {
        title: "Progress",
        href: "/progress",
        icon: ListChecks,
        description: "Field-by-field completion status",
      },
      {
        title: "PDF Preview",
        href: "/preview",
        icon: FileText,
        description: "Review and download the filled form",
      },
      {
        title: "Knowledge Chat",
        href: "/knowledge",
        icon: BookOpenText,
        description: "Ask anything about KYC rules — cited answers",
      },
    ],
  },
  {
    label: "General",
    items: [
      {
        title: "Settings",
        href: "/settings",
        icon: Settings,
        description: "Appearance and preferences",
      },
      {
        title: "About",
        href: "/about",
        icon: Info,
        description: "How KnightForge Sahayak works",
      },
    ],
  },
];

/** Ordered product workflow — powers steppers and the landing visualization. */
export const WORKFLOW_STEPS = [
  { key: "upload", label: "Upload", detail: "Drop your existing KYC or ID document" },
  { key: "ocr", label: "Extract", detail: "Fields are read from your documents" },
  { key: "ai", label: "AI-Guided Completion", detail: "A guided chat fills the gaps" },
  { key: "validation", label: "Validation", detail: "Every field checked deterministically" },
  { key: "pdf", label: "PDF", detail: "Your filled, ready-to-sign form" },
] as const;
