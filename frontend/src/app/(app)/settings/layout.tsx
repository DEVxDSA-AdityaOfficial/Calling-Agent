import { Suspense } from "react";
import { SettingsNav } from "./SettingsNav";

export default function SettingsLayout({ children }: LayoutProps<"/settings">) {
  return (
    <div className="flex flex-col gap-6 md:flex-row">
      <Suspense fallback={<div className="md:w-44" />}>
        <SettingsNav />
      </Suspense>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
