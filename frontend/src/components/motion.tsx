"use client";

import { animate, motion, useInView, useMotionValue, useReducedMotion, useTransform } from "motion/react";
import { useEffect, useRef } from "react";

/** Shared easing: a soft "expo out" that reads as premium without feeling slow. */
export const EASE = [0.16, 1, 0.3, 1] as const;

export function FadeIn({ children, delay = 0, y = 12, className }: { children: React.ReactNode; delay?: number; y?: number; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y, filter: "blur(4px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      transition={{ duration: 0.6, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

/** Children animate in one after another. Wrap each child in <StaggerItem>. */
export function Stagger({ children, className, gap = 0.06 }: { children: React.ReactNode; className?: string; gap?: number }) {
  return (
    <motion.div className={className} initial="hidden" animate="show" variants={{ show: { transition: { staggerChildren: gap } } }}>
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, className }: { children: React.ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      variants={{
        hidden: reduce ? { opacity: 1 } : { opacity: 0, y: 14, scale: 0.98 },
        show: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.55, ease: EASE } },
      }}
    >
      {children}
    </motion.div>
  );
}

/** Number that counts up when it first scrolls into view. */
export function CountUp({ value, format = (n) => Math.round(n).toLocaleString() }: { value: number; format?: (n: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const mv = useMotionValue(0);
  const text = useTransform(mv, format);
  const reduce = useReducedMotion();
  useEffect(() => {
    if (!inView) return;
    if (reduce) {
      mv.set(value);
      return;
    }
    const controls = animate(mv, value, { duration: 1.1, ease: EASE });
    return () => controls.stop();
  }, [inView, value, mv, reduce]);
  return <motion.span ref={ref}>{text}</motion.span>;
}

/** Lift + soft shadow on hover for interactive cards. */
export function HoverCard({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <motion.div
      className={className}
      whileHover={{ y: -3, boxShadow: "0 12px 32px -12px rgba(17,17,20,0.18)" }}
      transition={{ type: "spring", stiffness: 400, damping: 30 }}
    >
      {children}
    </motion.div>
  );
}

/** Animated check mark (stroke draw) for success states. */
export function DrawCheck({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <motion.path d="m5 12.5 4.5 4.5L19 7.5" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.45, ease: EASE }} />
    </svg>
  );
}

/** Shimmering placeholder while data loads. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`relative overflow-hidden rounded-lg bg-zinc-200/60 ${className}`}><div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/70 to-transparent" /></div>;
}
