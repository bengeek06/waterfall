import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { Space_Grotesk, Source_Serif_4 } from "next/font/google";
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
        <header className="topbar">
          <Link href="/" className="brand" aria-label="Accueil Waterfall">
            <Image
              src="/waterfall_logo.svg"
              alt="Waterfall"
              width={154}
              height={36}
              priority
            />
          </Link>
          <nav className="menu">
            <Link href="/login">Login</Link>
            <Link href="/users">Utilisateurs</Link>
            <Link href="/resources">Ressources</Link>
            <Link href="/projects">Projets</Link>
          </nav>
        </header>
        <main className="shell">{children}</main>
      </body>
    </html>
  );
}
