"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Download, Eye, FileText } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The KYC forms Sahayak can complete, served as static files from
 * `public/kyc-templates/`. These are the exact PDFs the placement manifests
 * were measured against, so a form downloaded here is one the generator is
 * known to fill correctly.
 *
 * Static assets rather than an API route on purpose: they are fixed reference
 * documents, identical for every user, and belong to no session — routing them
 * through the backend would imply they are user data.
 */
const TEMPLATES: { label: string; file: string; download: string }[] = [
  { label: "CVL KYC (CDSL)", file: "cvl-kyc-cdsl.pdf", download: "CVL-KYC-CDSL-Form.pdf" },
  {
    label: "SBI KYC Updation — Annexure A",
    file: "sbi-kyc.pdf",
    download: "SBI-KYC-Updation-Annexure-A.pdf",
  },
  { label: "HDFC KYC", file: "hdfc-kyc.pdf", download: "HDFC-KYC-Form.pdf" },
  {
    label: "ICICI KYC — Central KYC Registry",
    file: "icici-kyc.pdf",
    download: "ICICI-KYC-Central-KYC-Registry-Form.pdf",
  },
  {
    label: "Axis Bank KYC — Central KYC Registry",
    file: "axis-kyc.pdf",
    download: "Axis-Bank-KYC-Central-KYC-Registry-Form.pdf",
  },
];

const href = (file: string) => `/kyc-templates/${file}`;

/**
 * Compact template library for the Upload page header.
 *
 * Deliberately a plain popover rather than a headless-UI dependency: it needs
 * a trigger, outside-click/Escape dismissal and roving focus, all of which are
 * a few lines here and would otherwise add a package for one control.
 */
export function TemplateLibrary({ className }: { className?: string }) {
  const [open, setOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const menuRef = React.useRef<HTMLDivElement>(null);

  /* Dismiss on outside click and on Escape. Both listeners set state from an
     event callback, never synchronously during the effect. */
  React.useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      // Focus returns to the trigger so keyboard users are not dropped at the
      // top of the document.
      triggerRef.current?.focus();
    };

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  /** Arrow keys move between rows; Home/End jump to the ends. */
  const onMenuKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const keys = ["ArrowDown", "ArrowUp", "Home", "End"];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLAnchorElement>("a[data-menu-item]") ?? [],
    );
    if (items.length === 0) return;
    const current = items.indexOf(document.activeElement as HTMLAnchorElement);
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? items.length - 1
          : event.key === "ArrowDown"
            ? (current + 1 + items.length) % items.length
            : (current - 1 + items.length) % items.length;
    items[next]?.focus();
  };

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <Button
        ref={triggerRef}
        type="button"
        variant="outline"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <FileText aria-hidden />
        KYC form templates
        <ChevronDown
          className={cn("size-4 transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </Button>

      <AnimatePresence>
        {open && (
          <motion.div
            ref={menuRef}
            role="menu"
            aria-label="Supported KYC form templates"
            onKeyDown={onMenuKeyDown}
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.15, ease: [0.22, 1, 0.36, 1] }}
            className={
              // Right-aligned on desktop so it never runs off the header; full
              // width on narrow screens where the trigger stacks.
              "absolute right-0 z-50 mt-2 w-[min(20rem,calc(100vw-2rem))] " +
              "overflow-hidden rounded-xl border border-border bg-card shadow-xl"
            }
          >
            <div className="border-b border-border px-3 py-2.5">
              <p className="text-xs font-semibold">Supported KYC forms</p>
              <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                Need a form? Download a supported KYC template, then upload it
                below as your Primary Form.
              </p>
            </div>

            <ul className="p-1.5">
              {TEMPLATES.map((template) => (
                <li key={template.file}>
                  <div className="flex items-center gap-1 rounded-lg px-2 py-1.5 transition-colors hover:bg-muted/50">
                    <span className="min-w-0 flex-1 truncate text-sm">
                      {template.label}
                    </span>
                    <a
                      data-menu-item
                      role="menuitem"
                      href={href(template.file)}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={`View the ${template.label} template`}
                      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <Eye className="size-3.5" aria-hidden /> View
                    </a>
                    <a
                      data-menu-item
                      role="menuitem"
                      href={href(template.file)}
                      download={template.download}
                      aria-label={`Download the ${template.label} template`}
                      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <Download className="size-3.5" aria-hidden /> Download
                    </a>
                  </div>
                </li>
              ))}
            </ul>

            <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">
              Blank templates — separate from your uploaded documents and
              generated PDFs.
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
