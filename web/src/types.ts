export interface CrawlPreviewSeed {
  url: string;
  discovered_total: number;
  curriculum_mode: string;
  parts: string[];
  entries_preview: Array<{
    display_title: string;
    url: string;
    part_title?: string;
  }>;
  error?: string;
}

export interface CrawlPreview {
  seeds: CrawlPreviewSeed[];
  discovered_total: number;
  crawl_enabled: boolean;
}

export interface ParamField {
  key: string;
  label: string;
  description: string;
  type: "float" | "int" | "bool" | "text";
  default: unknown;
  min?: number;
  max?: number;
  step?: number;
  group: string;
  visible_when_key?: string;
  visible_when_equals?: unknown;
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

export interface RoundRecord {
  macro_iter: number;
  accuracy: number;
  plain_accuracy: number;
  batch_accuracy?: number;
  chapter_accuracy?: number;
  difficulty_level: number;
  curriculum_level: number;
  current_chapter_index?: number;
  chapter_title?: string;
  question_count: number;
  correct: number;
  weak_topics: string[];
  topic_counts: Record<string, number>;
  persona_counts: Record<string, number>;
  chapter_progress?: ChapterProgress[];
  chapter_relevant_count?: number;
  chapter_total_scored?: number;
  chapter_evidence_fallback?: boolean;
  judge_anomaly?: boolean;
  judge_anomaly_reason?: string;
  empty_judge_reason_count?: number;
  avg_judge_score?: number;
  reinforce_correct?: number;
  reinforce_wrong?: number;
  reinforce_pool_size?: number;
  long_term_notes_chars?: number;
  short_term_notes_chars?: number;
  token_round_total?: number;
  token_round_input?: number;
  token_round_output?: number;
  token_cumulative_total?: number;
  token_cumulative_input?: number;
  token_cumulative_output?: number;
  token_calls_round?: number;
  tokens_by_step_round?: Record<string, number>;
  settings_snapshot?: Record<string, unknown>;
  wrong_samples?: Array<{
    question: string;
    answer: string;
    judge_reason: string;
    judge_score?: number;
    topic_tag?: string;
  }>;
}

export interface ChapterProgress {
  chapter_id: string;
  chapter_title: string;
  chapter_index: number;
  mastered: boolean;
  accuracy: number;
  best_accuracy: number;
  attempts: number;
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
  current_questions?: number;
  token_total?: number;
  token_input?: number;
  token_output?: number;
  token_calls?: number;
  tokens_by_step?: Record<string, number>;
  accuracy_history: number[];
  round_records?: RoundRecord[];
  chapter_mastery?: Record<string, unknown>;
  chapter_progress?: ChapterProgress[];
  current_chapter_index?: number;
  learning_mode?: string;
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

export type TabId = "launch" | "logs" | "tokens" | "curve" | "compare";
