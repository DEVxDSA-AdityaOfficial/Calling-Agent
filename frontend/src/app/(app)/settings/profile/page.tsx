"use client";

import { useRouter } from "next/navigation";
import { IconLogout } from "@/components/icons";
import { PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useUser } from "@/lib/auth";

export default function ProfilePage() {
  const { user } = useUser();
  const router = useRouter();

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => {});
    router.replace("/login");
  }

  return (
    <>
      <PageHeader title="Profile" />
      <section className="card max-w-lg">
        <div className="flex items-center gap-4">
          <span className="grid h-12 w-12 place-items-center rounded-full bg-ink text-lg font-semibold uppercase text-white">{user.name.charAt(0)}</span>
          <div>
            <div className="font-semibold">{user.name}</div>
            <div className="text-sm text-muted">{user.email}</div>
          </div>
        </div>
        <button className="btn-secondary mt-6" onClick={logout}><IconLogout /> Sign out</button>
      </section>
    </>
  );
}
