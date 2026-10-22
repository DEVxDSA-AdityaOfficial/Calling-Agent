"use client";

import { motion, useReducedMotion } from "motion/react";

/**
 * Live-call orb. Ringing: slow breathing + expanding rings. Connected: rotating conic glow and an
 * animated waveform. Pure vector/CSS, so it stays crisp at any size (sharper than a GIF).
 */
export function CallOrb({ state }: { state: "ringing" | "connected" | "idle" }) {
  const reduce = useReducedMotion();
  const live = state === "connected";
  const bars = [0.45, 0.8, 1, 0.65, 0.9, 0.5, 0.7];
  return (
    <div className="relative grid h-52 w-52 place-items-center" aria-hidden>
      {/* expanding rings */}
      {!reduce &&
        [0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="absolute inset-6 rounded-full border border-accent/30"
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: live ? 1.45 : 1.3, opacity: [0, 0.6, 0] }}
            transition={{ duration: live ? 2.4 : 3, repeat: Infinity, delay: i * (live ? 0.8 : 1), ease: "easeOut" }}
          />
        ))}
      {/* rotating conic glow */}
      <span className={`absolute inset-8 rounded-full bg-[conic-gradient(from_0deg,#6d5dfc,#a78bfa,#38bdf8,#6d5dfc)] opacity-60 blur-2xl ${live ? "animate-orb" : ""}`} />
      {/* breathing core */}
      <motion.span
        className="absolute inset-10 rounded-full bg-gradient-to-br from-white via-accent-soft to-white shadow-[0_20px_60px_-15px_rgba(109,93,252,0.55)]"
        animate={reduce ? undefined : { scale: live ? [1, 1.04, 1] : [1, 1.025, 1] }}
        transition={{ duration: live ? 1.6 : 2.6, repeat: Infinity, ease: "easeInOut" }}
      />
      <span className="relative flex h-12 items-center gap-1.5">
        {bars.map((h, i) => (
          <motion.span
            key={i}
            className="w-1.5 rounded-full bg-gradient-to-t from-accent to-violet-400"
            style={{ height: `${h * 100}%` }}
            animate={reduce || !live ? { scaleY: state === "ringing" ? [0.35, 0.55, 0.35] : 0.35 } : { scaleY: [0.3, 1, 0.45, 0.85, 0.3] }}
            transition={{ duration: live ? 1.1 : 1.8, repeat: Infinity, delay: i * 0.09, ease: "easeInOut" }}
          />
        ))}
      </span>
    </div>
  );
}
