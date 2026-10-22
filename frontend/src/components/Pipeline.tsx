"use client";

import { motion } from "motion/react";
import type { AgentMode, SttProviderId } from "@/lib/api";
import { brandName, type BrandId, ProviderLogo } from "./ProviderLogo";

/** The providers a call flows through, left to right, with a travelling pulse between them. */
export function Pipeline({ mode, stt, live = false }: { mode: AgentMode; stt?: SttProviderId | null; live?: boolean }) {
  const steps: { id: BrandId; role: string }[] =
    mode === "direct"
      ? [
          { id: "twilio", role: "Call" },
          { id: stt ?? "sarvam", role: "Speech-to-text" },
          { id: "openai", role: "Brain" },
          { id: "elevenlabs", role: "Voice" },
        ]
      : mode === "custom_brain"
        ? [{ id: "retell", role: "Call · speech · voice" }, { id: "openai", role: "Brain" }]
        : [{ id: "retell", role: "Call · speech · brain · voice" }];
  return (
    <div className="flex flex-wrap items-center justify-center gap-1.5">
      {steps.map((s, i) => (
        <div key={s.id + i} className="flex items-center gap-1.5">
          {i > 0 && (
            <span className="relative h-px w-6 overflow-hidden bg-border">
              {live && (
                <motion.span className="absolute inset-y-0 w-3 bg-accent"
                  animate={{ x: [-12, 24] }} transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.25, ease: "easeInOut" }} />
              )}
            </span>
          )}
          <span className="flex items-center gap-1.5 rounded-full bg-surface py-1 pl-1 pr-2.5 text-xs ring-1 ring-border" title={s.role}>
            <ProviderLogo id={s.id} size="xs" />
            <span className="font-medium">{brandName(s.id)}</span>
          </span>
        </div>
      ))}
    </div>
  );
}
