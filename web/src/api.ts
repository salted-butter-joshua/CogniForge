import type { ParamSchema, RunSummary } from "./types";

const API = "/api";

export async function fetchSchema(): Promise<ParamSchema> {
  const r = await fetch(`${API}/config/schema`);
  if (!r.ok) throw new Error("Failed to load config schema");
  return r.json();
}

export async function listRuns(): Promise<RunSummary[]> {
  const r = await fetch(`${API}/runs`);
  if (!r.ok) throw new Error("Failed to list runs");
  return r.json();
}

export async function getRun(runId: string): Promise<RunSummary> {
  const r = await fetch(`${API}/runs/${runId}`);
  if (!r.ok) throw new Error("Run not found");
  return r.json();
}

export async function startRun(body: Record<string, unknown>): Promise<{
  run_id: string;
  task_id: string;
  status: string;
}> {
  const r = await fetch(`${API}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to start run");
  }
  return r.json();
}

export async function stopRun(runId: string): Promise<void> {
  const r = await fetch(`${API}/runs/${runId}/stop`, { method: "POST" });
  if (!r.ok) throw new Error("Failed to stop run");
}

export function subscribeEvents(
  runId: string,
  onEvent: (data: unknown) => void,
  onError?: (err: Event) => void
): () => void {
  const es = new EventSource(`${API}/runs/${runId}/events`);
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch {
      /* ignore */
    }
  };
  es.onerror = (e) => {
    onError?.(e);
  };
  return () => es.close();
}
