"use client";

import { motion } from "motion/react";
import Link from "next/link";
import type { Call } from "@/lib/api";
import { callResult, formatDuration, formatRelative } from "@/lib/format";
import { Pill } from "./ui";

export function CallsTable({ calls, empty }: { calls: Call[]; empty: React.ReactNode }) {
  if (!calls.length) return <div className="py-10 text-center text-sm text-muted">{empty}</div>;
  return (
    <div className="-mx-5 overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="text-xs text-muted">
          <tr className="border-b border-border">
            <th className="px-5 py-2.5 font-medium">Contact</th>
            <th className="px-3 py-2.5 font-medium">Agent</th>
            <th className="px-3 py-2.5 font-medium">Status</th>
            <th className="px-3 py-2.5 font-medium">Duration</th>
            <th className="px-5 py-2.5 font-medium">Time</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((c, i) => {
            const result = callResult(c);
            return (
              <motion.tr key={c.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: Math.min(i, 10) * 0.04, ease: [0.16, 1, 0.3, 1] }}
                className="group border-b border-border last:border-0 hover:bg-background/70">
                <td className="px-5 py-3.5">
                  <Link href={`/calls/${c.id}`} className="font-medium tabular-nums group-hover:text-accent">
                    {c.customer_name || c.to_number}
                  </Link>
                  {c.customer_name && <div className="text-xs tabular-nums text-muted">{c.to_number}</div>}
                </td>
                <td className="px-3 py-3.5">{c.agent_name ?? "—"}</td>
                <td className="px-3 py-3.5"><Pill tone={result.tone} live={result.live}>{result.label}</Pill></td>
                <td className="px-3 py-3.5 tabular-nums">{c.duration_ms ? formatDuration(c.duration_ms) : "—"}</td>
                <td className="whitespace-nowrap px-5 py-3.5 text-muted">{formatRelative(c.created_at)}</td>
              </motion.tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
