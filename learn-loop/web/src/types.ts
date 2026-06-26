export interface ParamField {
  key: string;
  label: string;
  description: string;
  type: "float" | "int" | "bool" | "text";
  default: unknown;
  min?: number;
  max?: number;
  group: string;
}

export interface ParamPreset {
  id: string;
  label: string;
  description: string;
  values: Record<string, unknown>;
}

export interface ParamSchema {
  groups: string[];
  fields: ParamField[];
  presets?: ParamPreset[];
  default_preset?: string;
}

export interface RunSummary {
  run_id: string;
  task_id: string;
  status: string;
  urls: string[];
  goal: string;
  params: Record<string, unknown>;
  macro_iter: number;
  batch_accuracy: number;
  accuracy_history: number[];
  weak_topics: string[];
  phase: string;
  error_message: string;
  created_at: number;
  finished_at?: number | null;
  label: string;
}

export interface StepTimingEvent {
  type: "step_timing" | "step_start";
  step?: string;
  step_label?: string;
  duration_ms?: number;
  duration_label?: string;
  macro_iter?: number;
  batch?: number;
  outcome?: string;
  ts?: number;
}

export interface StepRecord {
  key: string;
  step: string;
  stepLabel: string;
  macroIter: number;
  batch: number;
  durationMs?: number;
  startedAt?: number;
  status: "running" | "done" | "failed";
}

export interface RunEvent {
  type: string;
  level?: string;
  message?: string;
  ts?: number;
  macro_iter?: number;
  batch?: number;
  accuracy?: number;
  accuracy_pct?: number;
  history?: number[];
  weak_topics?: string[];
  summary?: RunSummary;
  step?: string;
  step_label?: string;
  duration_ms?: number;
  duration_label?: string;
  outcome?: string;
  phase?: string;
}

export type TabId = "launch" | "logs" | "curve" | "compare";
