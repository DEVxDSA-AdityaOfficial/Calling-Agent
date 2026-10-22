"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AgentBuilder } from "@/components/AgentBuilder";
import { Alert } from "@/components/ui";
import { api, type Agent } from "@/lib/api";

export default function EditAgentPage() {
  const { id } = useParams<{ id: string }>();
  const [agent, setAgent] = useState<Agent>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    api<Agent>(`/agents/${id}`).then(setAgent).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <Alert>{error}</Alert>;
  if (!agent) return <p className="text-muted">Loading…</p>;
  return <AgentBuilder key={agent.id} agent={agent} />;
}
