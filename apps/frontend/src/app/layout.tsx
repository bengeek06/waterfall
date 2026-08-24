import type { Metadata } from "next";
import { Space_Grotesk, Source_Serif_4, Inter, Roboto } from "next/font/google";
import { AppShell } from "@/components/app-shell";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";
import { cn } from "@/lib/utils";

const robotoHeading = Roboto({subsets:['latin'],variable:'--font-heading'});

const inter = Inter({subsets:['latin'],variable:'--font-sans'});

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
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
    ],
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="fr" className={cn(titleFont.variable, textFont.variable, "font-sans", inter.variable, robotoHeading.variable)}>
      <body>
        <div className="app-bg" />
        <TooltipProvider>
          <AppShell>{children}</AppShell>
        </TooltipProvider>
        <Toaster position="top-right" />
      </body>
    </html>
  );
}
