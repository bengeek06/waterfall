import type { Metadata } from "next";
import { Space_Grotesk, Source_Serif_4 } from "next/font/google";
import { AppShell } from "@/components/app-shell";
import "./globals.css";

const titleFont = Space_Grotesk({
  variable: "--font-title",
  subsets: ["latin"],
});

const textFont = Source_Serif_4({
  variable: "--font-text",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Waterfall Console",
  description: "Console de gestion Waterfall",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="fr" className={`${titleFont.variable} ${textFont.variable}`}>
      <body>
        <div className="app-bg" />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
