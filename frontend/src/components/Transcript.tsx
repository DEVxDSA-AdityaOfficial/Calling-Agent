"use client";

import { AnimatePresence, motion } from "motion/react";
import type { Turn } from "@/lib/api";
import { EASE } from "./motion";

export function Transcript({ turns, live }: { turns: Turn[]; live?: boolean }) {
  const visible = turns.filter((t) => t.content);
  if (!visible.length) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted">
        {live && <span className="flex gap-1">{[0, 1, 2].map((i) => (
          <motion.span key={i} className="h-1.5 w-1.5 rounded-full bg-muted" animate={{ opacity: [0.2, 1, 0.2] }} transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2 }} />
        ))}</span>}
        {live ? "Waiting for the conversation to start…" : "No transcript."}
      </p>
    );
  }
  return (
    <ol className="space-y-3">
      <AnimatePresence initial={false}>
        {visible.map((t, i) => {
          const agent = t.role === "agent";
          return (
            <motion.li key={`${i}-${t.role}`} layout
              initial={{ opacity: 0, y: 10, filter: "blur(3px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              transition={{ duration: 0.45, ease: EASE }}
              className="grid grid-cols-[72px_1fr] gap-3 text-sm">
              <span className={`pt-0.5 text-xs font-semibold uppercase tracking-wide ${agent ? "text-accent" : "text-muted"}`}>
                {agent ? "AI" : "Customer"}
              </span>
              <span className="leading-relaxed">{t.content}</span>
            </motion.li>
          );
        })}
      </AnimatePresence>
    </ol>
  );
}
