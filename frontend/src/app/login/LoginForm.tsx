"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { motion } from "motion/react";
import { Logo } from "@/components/AppShell";
import { EASE } from "@/components/motion";
import { type BrandId, brandName, ProviderLogo } from "@/components/ProviderLogo";
import { IconArrowRight, IconLock, IconMail, IconUser } from "@/components/icons";
import { Alert, Spinner } from "@/components/ui";
import { api, type User } from "@/lib/api";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await api<User>(mode === "login" ? "/auth/login" : "/auth/signup", {
        method: "POST",
        body: JSON.stringify(mode === "login" ? { email, password } : { name, email, password }),
      });
      const next = params.get("next");
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="relative grid min-h-screen place-items-center overflow-hidden bg-background px-4 py-12">
      <motion.div aria-hidden className="pointer-events-none absolute -left-40 top-1/3 h-96 w-96 rounded-full bg-accent/15 blur-3xl"
        animate={{ x: [0, 40, 0], y: [0, -30, 0] }} transition={{ duration: 14, repeat: Infinity, ease: "easeInOut" }} />
      <motion.div aria-hidden className="pointer-events-none absolute -right-32 bottom-0 h-80 w-80 rounded-full bg-sky-300/20 blur-3xl"
        animate={{ x: [0, -30, 0], y: [0, 20, 0] }} transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }} />

      <motion.div className="relative w-full max-w-md text-center"
        initial={{ opacity: 0, y: 16, filter: "blur(6px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }} transition={{ duration: 0.8, ease: EASE }}>
        <div className="mb-8 flex justify-center text-lg"><Logo /></div>
        <h1 className="text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
          Turn your script
          <br />
          into real conversations
        </h1>
        <p className="mt-3 text-muted">AI calling agents. Your providers. Your control.</p>

        <form onSubmit={submit} className="card mt-8 p-6 text-left sm:p-7">
          <div className="mb-6 grid grid-cols-2 border-b border-border text-sm">
            {(["login", "signup"] as const).map((m) => (
              <button key={m} type="button" onClick={() => { setMode(m); setError(undefined); }}
                className={`-mb-px border-b-2 pb-3 font-medium transition ${mode === m ? "border-accent text-foreground" : "border-transparent text-muted hover:text-foreground"}`}>
                {m === "login" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>

          <div className="space-y-3">
            {mode === "signup" && (
              <Field icon={<IconUser />}>
                <input className="input pl-10" required placeholder="Your name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
            )}
            <Field icon={<IconMail />}>
              <input className="input pl-10" type="email" required placeholder="you@company.com" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field icon={<IconLock />}>
              <input className="input pl-10" type="password" required minLength={mode === "signup" ? 8 : 1}
                placeholder={mode === "signup" ? "Password (min. 8 characters)" : "Password"}
                autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
          </div>

          {error && <div className="mt-4"><Alert>{error}</Alert></div>}

          <button type="submit" className="btn-primary mt-5 w-full py-3" disabled={busy}>
            {busy ? <Spinner /> : <>{mode === "login" ? "Sign in" : "Create account"} <IconArrowRight /></>}
          </button>
          <p className="mt-5 text-center text-xs text-muted">
            Use this platform only to call people who have agreed to hear from you.
          </p>
        </form>

        <div className="mt-8">
          <p className="mb-3 text-xs font-medium uppercase tracking-wider text-muted">Works with your providers</p>
          <div className="flex flex-wrap justify-center gap-2">
            {(["twilio", "retell", "sarvam", "openai", "elevenlabs"] as BrandId[]).map((b, i) => (
              <motion.span key={b} title={brandName(b)}
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 + i * 0.07, duration: 0.5, ease: EASE }}
                whileHover={{ y: -3 }}>
                <ProviderLogo id={b} size="md" className="bg-white shadow-sm" />
              </motion.span>
            ))}
          </div>
        </div>
      </motion.div>
    </div>
  );
}

function Field({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="relative">
      <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-zinc-400">{icon}</span>
      {children}
    </div>
  );
}
