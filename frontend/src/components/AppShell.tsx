"use client";

import { motion } from "motion/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError, type User } from "@/lib/api";
import { AuthContext } from "@/lib/auth";
import { APP_NAME } from "@/lib/format";
import { IconBot, IconHome, IconPhone, IconSettings, Waveform } from "./icons";

const NAV = [
  { href: "/", label: "Dashboard", icon: IconHome },
  { href: "/agents", label: "Agents", icon: IconBot },
  { href: "/calls", label: "Calls", icon: IconPhone },
  { href: "/settings/providers", label: "Settings", icon: IconSettings, match: "/settings" },
];

export function Logo({ dark = false }: { dark?: boolean }) {
  return (
    <span className={`flex items-center gap-2 font-semibold ${dark ? "text-white" : "text-foreground"}`}>
      <Waveform className="h-6 w-6 text-accent" />
      {APP_NAME}
    </span>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string>();

  useEffect(() => {
    api<User>("/auth/me")
      .then(setUser)
      .catch((e: ApiError) => {
        if (e.status === 401) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
        else setError(e.message);
      });
    // Only on first load: navigation inside the shell keeps the session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!user) {
    return (
      <div className="grid min-h-screen place-items-center bg-background text-sm text-muted">
        {error ?? "Loading…"}
      </div>
    );
  }

  return (
    <AuthContext.Provider value={{ user, setUser }}>
      <div className="flex min-h-screen">
        <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col bg-sidebar px-3 py-5 md:flex">
          <Link href="/" className="mb-8 px-2"><Logo dark /></Link>
          <nav className="flex flex-col gap-1">
            {NAV.map(({ href, label, icon: Icon, match }) => {
              const prefix = match ?? href;
              const active = href === "/" ? pathname === "/" : pathname.startsWith(prefix);
              return (
                <Link key={href} href={href}
                  className={`relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors ${
                    active ? "font-medium text-white" : "text-zinc-400 hover:text-white"
                  }`}>
                  {active && (
                    <motion.span layoutId="nav-active" className="absolute inset-0 rounded-xl bg-sidebar-active ring-1 ring-white/5"
                      transition={{ type: "spring", stiffness: 380, damping: 32 }} />
                  )}
                  <Icon className="relative h-[18px] w-[18px]" />
                  <span className="relative">{label}</span>
                </Link>
              );
            })}
          </nav>
          <Link href="/settings/profile" className="mt-auto flex items-center gap-3 rounded-xl px-2 py-2 text-sm text-zinc-300 hover:bg-sidebar-active">
            <span className="grid h-8 w-8 place-items-center rounded-full bg-zinc-700 text-xs font-semibold uppercase text-white">
              {user.name.charAt(0) || user.email.charAt(0)}
            </span>
            <span className="min-w-0">
              <span className="block truncate font-medium text-white">{user.name}</span>
              <span className="block truncate text-xs text-zinc-500">{user.email}</span>
            </span>
          </Link>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          {/* Mobile top bar */}
          <header className="flex items-center justify-between gap-3 bg-sidebar px-4 py-3 md:hidden">
            <Logo dark />
            <nav className="flex gap-1">
              {NAV.map(({ href, label, icon: Icon, match }) => {
                const active = href === "/" ? pathname === "/" : pathname.startsWith(match ?? href);
                return (
                  <Link key={href} href={href} aria-label={label}
                    className={`rounded-lg p-2 ${active ? "bg-sidebar-active text-white" : "text-zinc-400"}`}>
                    <Icon className="h-5 w-5" />
                  </Link>
                );
              })}
            </nav>
          </header>
          <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-8">{children}</main>
        </div>
      </div>
    </AuthContext.Provider>
  );
}
