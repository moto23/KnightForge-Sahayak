import Link from "next/link";

import { Logo } from "@/components/shared/logo";

const FOOTER_COLUMNS = [
  {
    heading: "Product",
    links: [
      { label: "How it works", href: "/#how-it-works" },
      { label: "Features", href: "/#features" },
      { label: "Security", href: "/#security" },
      { label: "FAQ", href: "/#faq" },
    ],
  },
  {
    heading: "Workspace",
    links: [
      { label: "Dashboard", href: "/dashboard" },
      { label: "Upload", href: "/upload" },
      { label: "AI Interview", href: "/interview" },
      { label: "PDF Preview", href: "/preview" },
    ],
  },
  {
    heading: "Company",
    links: [
      { label: "About", href: "/about" },
      { label: "Sign in", href: "/signin" },
      { label: "Settings", href: "/settings" },
    ],
  },
];

export function Footer() {
  return (
    <footer className="border-t border-border bg-card/40">
      <div className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-5">
          <div className="space-y-3 lg:col-span-2">
            <Logo />
            <p className="max-w-xs text-sm text-muted-foreground">
              The AI paperwork copilot that turns complex KYC forms into a
              guided conversation — upload, chat, download.
            </p>
          </div>
          {FOOTER_COLUMNS.map((column) => (
            <nav key={column.heading} aria-label={column.heading}>
              <h3 className="mb-3 text-sm font-semibold">{column.heading}</h3>
              <ul className="space-y-2">
                {column.links.map((link) => (
                  <li key={link.label}>
                    <Link
                      href={link.href}
                      className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
        <div className="mt-10 flex flex-col items-center justify-between gap-3 border-t border-border pt-6 sm:flex-row">
          <p className="text-xs text-muted-foreground">
            © 2026 KnightForge Sahayak. Built for the Codex Hackathon.
          </p>
          <p className="text-xs text-muted-foreground">
            Documents are processed locally — nothing leaves your machine.
          </p>
        </div>
      </div>
    </footer>
  );
}
