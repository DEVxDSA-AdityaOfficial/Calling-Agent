"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Agent, type CallDetail, type Options } from "@/lib/api";
import { IconPhone } from "./icons";
import { Alert, Spinner } from "./ui";

export function StartCallForm({ defaultAgentId }: { defaultAgentId?: string | null }) {
  const router = useRouter();
  const [agents, setAgents] = useState<Agent[]>();
  const [options, setOptions] = useState<Options>();
  const [agentId, setAgentId] = useState(defaultAgentId ?? "");
  const [toNumber, setToNumber] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  useEffect(() => {
    api<Options>("/options").then(setOptions).catch(() => {});
    api<Agent[]>("/agents")
      .then((list) => {
        setAgents(list);
        setAgentId((current) => current || String(list.find((a) => a.sync_status === "synced")?.id ?? ""));
      })
      .catch((e) => setError(e.message));
  }, []);

  const ready = agents?.filter((a) => a.sync_status === "synced") ?? [];
  const selected = ready.find((a) => String(a.id) === agentId);
  const viaTwilio = selected?.mode === "direct";

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const call = await api<CallDetail>("/calls", {
        method: "POST",
        body: JSON.stringify({ agent_id: Number(agentId), to_number: toNumber, customer_name: customerName || null, consent_confirmed: consent }),
      });
      router.push(`/calls/${call.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  if (agents && !ready.length) {
    return (
      <Alert kind="info">
        You need a ready agent first. <Link href="/agents/new" className="font-medium underline">Create one</Link>.
      </Alert>
    );
  }

  return (
    <form onSubmit={start} className="grid gap-4 md:grid-cols-2">
      {options && !options.from_number && !viaTwilio && (
        <div className="md:col-span-2">
          <Alert kind="warning">
            No caller number yet. Add one under <Link href="/settings/providers" className="font-medium underline">Settings → Retell AI</Link>.
          </Alert>
        </div>
      )}
      <div>
        <label className="label" htmlFor="agent">Agent</label>
        <select id="agent" className="input" required value={agentId} onChange={(e) => setAgentId(e.target.value)}>
          <option value="" disabled>Select an agent</option>
          {ready.map((a) => <option key={a.id} value={a.id}>{a.name} — {a.business_name}</option>)}
        </select>
      </div>
      <div>
        <label className="label" htmlFor="phone">Customer phone number</label>
        <input id="phone" className="input tabular-nums" type="tel" required placeholder="+91 98765 43210" autoComplete="off"
          value={toNumber} onChange={(e) => setToNumber(e.target.value)} />
        <p className="hint">
          Include the country code.
          {viaTwilio ? <> Calling from your Twilio number.</> : options?.from_number && <> Calling from {options.from_number}.</>}
          {options?.destination_allow_list && <> Only allow-listed numbers can be dialed.</>}
        </p>
      </div>
      <div>
        <label className="label" htmlFor="cname">Customer name <span className="font-normal text-muted">(optional)</span></label>
        <input id="cname" className="input" placeholder="e.g. Rohan Sharma" value={customerName} onChange={(e) => setCustomerName(e.target.value)} />
      </div>
      <label className="flex items-start gap-2.5 self-end rounded-xl bg-background p-3 text-xs leading-relaxed text-muted">
        <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--ink)]" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        <span>This person agreed to receive an automated AI call from us, and calling them now complies with applicable rules (TRAI/DND, TCPA, local calling hours).</span>
      </label>
      {error && <div className="md:col-span-2"><Alert>{error}</Alert></div>}
      <div className="md:col-span-2">
        <button type="submit" className="btn-primary" disabled={busy || !consent || !agentId}>
          {busy ? <Spinner /> : <IconPhone />} {busy ? "Starting call…" : "Start call"}
        </button>
      </div>
    </form>
  );
}
