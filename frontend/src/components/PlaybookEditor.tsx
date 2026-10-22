"use client";

import type { Playbook } from "@/lib/api";

const LISTS: { key: keyof Playbook; label: string }[] = [
  { key: "qualification_questions", label: "Qualification questions" },
  { key: "value_points", label: "How to explain the offering" },
  { key: "follow_up_questions", label: "Follow-up questions" },
  { key: "success_criteria", label: "Success criteria" },
];

/** Editable view of the AI-generated playbook. Lists are edited one item per line. */
export function PlaybookEditor({ value, onChange }: { value: Playbook; onChange: (p: Playbook) => void }) {
  const set = <K extends keyof Playbook>(key: K, v: Playbook[K]) => onChange({ ...value, [key]: v });

  return (
    <div className="space-y-5">
      <div>
        <label className="label">Opening</label>
        <textarea className="input min-h-16" value={value.opening} onChange={(e) => set("opening", e.target.value)} />
      </div>
      <div className="grid gap-5 md:grid-cols-2">
        {LISTS.map(({ key, label }) => (
          <div key={key}>
            <label className="label">{label}</label>
            <textarea className="input min-h-28" value={(value[key] as string[]).join("\n")}
              onChange={(e) => set(key, e.target.value.split("\n") as never)}
              onBlur={(e) => set(key, e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) as never)} />
            <p className="hint">One per line.</p>
          </div>
        ))}
      </div>
      <div>
        <label className="label">Objection handling</label>
        <div className="space-y-2">
          {value.objections.map((o, i) => (
            <div key={i} className="grid gap-2 rounded-xl bg-background p-2.5 md:grid-cols-[1fr_1.6fr_auto]">
              <input className="input" placeholder="Objection" value={o.objection}
                onChange={(e) => set("objections", value.objections.map((x, j) => (j === i ? { ...x, objection: e.target.value } : x)))} />
              <input className="input" placeholder="How to respond" value={o.response}
                onChange={(e) => set("objections", value.objections.map((x, j) => (j === i ? { ...x, response: e.target.value } : x)))} />
              <button type="button" className="btn-secondary px-3" aria-label="Remove objection"
                onClick={() => set("objections", value.objections.filter((_, j) => j !== i))}>×</button>
            </div>
          ))}
          <button type="button" className="text-sm font-medium text-accent hover:underline"
            onClick={() => set("objections", [...value.objections, { objection: "", response: "" }])}>+ Add objection</button>
        </div>
      </div>
      <div>
        <label className="label">Closing strategy</label>
        <textarea className="input min-h-16" value={value.closing_strategy} onChange={(e) => set("closing_strategy", e.target.value)} />
      </div>
    </div>
  );
}
