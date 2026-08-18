"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { FolderKanban, LogOut, Menu, Settings2, Users, X } from "lucide-react";

import { clearSession } from "@/lib/session";

const navigation = [
  { href: "/projects", label: "Projets", icon: FolderKanban },
  { href: "/resources", label: "Ressources", icon: Settings2 },
  { href: "/users", label: "Utilisateurs", icon: Users },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  if (pathname === "/login") {
    return <main className="auth-shell">{children}</main>;
  }

  function signOut() {
    clearSession();
    router.push("/login");
  }

  return (
    <div className="workspace-shell">
      {sidebarOpen ? (
        <button className="sidebar-backdrop" type="button" aria-label="Fermer le menu" onClick={() => setSidebarOpen(false)} />
      ) : null}
      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <div className="sidebar-brand">
          <Link href="/projects" aria-label="Accueil Waterfall" onClick={() => setSidebarOpen(false)}>
            <Image src="/waterfall_logo.svg" alt="Waterfall" width={142} height={34} priority />
          </Link>
          <button className="icon-button sidebar-close" type="button" aria-label="Fermer le menu" onClick={() => setSidebarOpen(false)}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <p className="sidebar-section-label">Pilotage</p>
        <nav className="sidebar-nav" aria-label="Navigation principale">
          {navigation.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                className={`sidebar-link ${active ? "sidebar-link-active" : ""}`}
                aria-current={active ? "page" : undefined}
                onClick={() => setSidebarOpen(false)}
              >
                <Icon size={18} aria-hidden="true" />
                <span>{label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <span className="sidebar-caption">Console Waterfall</span>
          <button className="sidebar-link sidebar-action" type="button" onClick={signOut}>
            <LogOut size={18} aria-hidden="true" />
            <span>Se déconnecter</span>
          </button>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="workspace-header">
          <button className="icon-button menu-trigger" type="button" aria-label="Ouvrir le menu" onClick={() => setSidebarOpen(true)}>
            <Menu size={20} aria-hidden="true" />
          </button>
          <div className="header-context">
            <span className="header-kicker">Espace de travail</span>
            <strong>Gestion des projets</strong>
          </div>
          <Link href="/projects" className="header-user" aria-label="Retour aux projets">
            <span className="avatar">W</span>
            <span className="header-user-name">Waterfall</span>
          </Link>
        </header>
        <main className="shell">{children}</main>
      </div>
    </div>
  );
}