"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const ITEMS = [
  { href: "/settings/providers", label: "API & Providers" },
  { href: "/settings/profile", label: "Profile" },
];

export function SettingsNav() {
  const pathname = usePathname();
  return (
    <nav className="flex gap-1 md:w-44 md:flex-col md:pt-14">
      {ITEMS.map((i) => (
        <Link key={i.href} href={i.href}
          className={`rounded-xl px-3 py-2 text-sm ${pathname === i.href ? "bg-surface font-medium shadow-sm ring-1 ring-border" : "text-muted hover:text-foreground"}`}>
          {i.label}
        </Link>
      ))}
    </nav>
  );
}
