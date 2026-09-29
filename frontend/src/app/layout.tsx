import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Source_Serif_4 } from "next/font/google";

import { ApiGate } from "@/components/api-gate";
import { Sidebar } from "@/components/sidebar";

import { Providers } from "./providers";
import "./globals.css";

const serif = Source_Serif_4({ subsets: ["latin"], variable: "--font-serif", display: "swap" });
const sans = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-sans", display: "swap" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "LeadLens",
  description: "Clean, rank and act on CRM leads with cited, verifiable explanations.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable} ${mono.variable}`}>
      <body className="font-sans">
        <Providers>
          <Sidebar />
          <main className="min-h-screen pl-[180px]">
            <ApiGate>{children}</ApiGate>
          </main>
        </Providers>
      </body>
    </html>
  );
}
