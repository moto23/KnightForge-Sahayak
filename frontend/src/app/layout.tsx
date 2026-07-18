import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { Providers } from "@/components/providers";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "KnightForge Sahayak — AI Paperwork Copilot",
    template: "%s · KnightForge Sahayak",
  },
  description:
    "Turn complex KYC forms into a guided AI experience. Upload a document, answer a friendly interview, and download a perfectly filled, validated PDF.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#090b12" },
    { media: "(prefers-color-scheme: light)", color: "#f7f8fb" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // suppressHydrationWarning: next-themes mutates <html class> before paint.
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} flex min-h-dvh flex-col antialiased`}
      >
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
