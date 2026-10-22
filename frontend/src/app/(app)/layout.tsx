import { Suspense } from "react";
import { AppShell } from "@/components/AppShell";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <Suspense fallback={<div className="min-h-screen bg-background" />}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
