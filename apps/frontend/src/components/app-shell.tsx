"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { FolderKanban, LogOut, Settings2 } from "lucide-react";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarSeparator,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { getMe } from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";

const navigation = [{ href: "/projects", label: "Projets", icon: FolderKanban }];
const settingsItem = { href: "/resources", label: "Paramètres", icon: Settings2 };

function NavigationItem({
  href,
  label,
  Icon,
  active,
}: {
  href: string;
  label: string;
  Icon: typeof FolderKanban;
  active: boolean;
}) {
  const { setOpenMobile } = useSidebar();

  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        isActive={active}
        tooltip={label}
        render={<Link href={href} aria-current={active ? "page" : undefined} />}
        onClick={() => setOpenMobile(false)}
      >
        <Icon aria-hidden="true" />
        <span>{label}</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [userEmail, setUserEmail] = useState<string | null>(null);

  useEffect(() => {
    if (pathname === "/login") {
      return;
    }
    const session = getSession();
    if (!session) {
      return;
    }
    const onSessionRefresh = (next: SessionTokens) => setSession(next);
    getMe(session, onSessionRefresh)
      .then((me) => setUserEmail(me.email))
      .catch(() => {
        // Non-blocking: pages already handle redirecting on session expiry.
      });
  }, [pathname]);

  if (pathname === "/login") {
    return <main className="mx-auto grid min-h-svh w-full place-items-center px-4">{children}</main>;
  }

  function signOut() {
    clearSession();
    router.push("/login");
  }

  return (
    <SidebarProvider>
      <Sidebar collapsible="offcanvas">
        <SidebarHeader className="p-4">
          <Link href="/projects" aria-label="Accueil Waterfall" className="inline-flex h-9 items-center">
            <Image src="/waterfall_logo.svg" alt="Waterfall" width={142} height={34} priority />
          </Link>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarMenu>
              {navigation.map(({ href, label, icon: Icon }) => (
                <NavigationItem
                  key={href}
                  href={href}
                  label={label}
                  Icon={Icon}
                  active={pathname === href || pathname.startsWith(`${href}/`)}
                />
              ))}
            </SidebarMenu>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter>
          <SidebarMenu>
            <NavigationItem
              href={settingsItem.href}
              label={settingsItem.label}
              Icon={settingsItem.icon}
              active={pathname === settingsItem.href || pathname.startsWith(`${settingsItem.href}/`)}
            />
          </SidebarMenu>
          <SidebarSeparator />
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton tooltip="Se déconnecter" onClick={signOut}>
                <LogOut aria-hidden="true" />
                <span>Se déconnecter</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset className="bg-transparent">
        <header className="sticky top-0 z-10 flex min-h-16 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur md:px-6">
          <SidebarTrigger aria-label="Ouvrir ou fermer le menu" />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium text-muted-foreground">Espace de travail</p>
            <p className="truncate text-sm font-semibold">Gestion des projets</p>
          </div>
          <Link href="/projects" className="inline-flex items-center gap-2" aria-label="Retour aux projets">
            <span className="hidden text-sm text-muted-foreground sm:inline">
              {userEmail ?? "Waterfall"}
            </span>
            <span className="grid size-8 place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
              W
            </span>
          </Link>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-6">{children}</main>
      </SidebarInset>
    </SidebarProvider>
  );
}