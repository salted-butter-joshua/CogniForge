import type { CrawlPreview, ParamSchema, RunSummary } from "./types";
import { formatApiError } from "./utils/apiError";

const API = "/api";

export async function fetchHealth(): Promise<{
  status: string;
  active_run?: string | null;
  api_keys_ok?: boolean;
  api_keys_hint?: string;
}> {
  const r = await fetch(`${API}/health`);
  if (!r.ok) throw new Error("API health check failed");
  return r.json();
}

export async function fetchSchema(): Promise<ParamSchema> {
  const r = await fetch(`${API}/config/schema`);
  if (!r.ok) throw new Error("Failed to load config schema");
  return r.json();
}

export async function previewCrawl(
  urls: string[],
  crawlEnabled: boolean
): Promise<CrawlPreview> {
  const r = await fetch(`${API}/crawl/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls, crawl_enabled: crawlEnabled }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(formatApiError(err.detail, "链接探测失败"));
  }
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
    throw new Error(formatApiError(err.detail, "启动任务失败"));
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
