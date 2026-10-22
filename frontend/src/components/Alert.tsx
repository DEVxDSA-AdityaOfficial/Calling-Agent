export function Alert({ kind = "error", children }: { kind?: "error" | "info" | "warning"; children: React.ReactNode }) {
  const styles = {
    error: "border-rose-500/30 bg-rose-500/10 text-rose-800 dark:text-rose-200",
    warning: "border-amber-500/30 bg-amber-500/10 text-amber-900 dark:text-amber-200",
    info: "border-sky-500/30 bg-sky-500/10 text-sky-900 dark:text-sky-200",
  }[kind];
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`rounded-lg border px-4 py-3 text-sm ${styles}`}>
      {children}
    </div>
  );
}
