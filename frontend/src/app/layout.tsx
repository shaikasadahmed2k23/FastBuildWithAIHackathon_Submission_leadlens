import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata } from "next";

import { ApiGate } from "@/components/api-gate";
import { Sidebar } from "@/components/sidebar";

import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "LeadLens",
  description: "Clean, rank and act on CRM leads with cited, verifiable explanations.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="font-sans">
        <Providers>
          <Sidebar />
          <main className="min-h-screen pl-[216px]">
            <ApiGate>{children}</ApiGate>
          </main>
        </Providers>
      </body>
    </html>
  );
}
