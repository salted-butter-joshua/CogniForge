import { useEffect, useMemo, useState } from "react";
import type { RunEvent, StepRecord, StepTimingEvent } from "../types";

const PIPELINE_STEPS = [
  "fetch_pages",
  "generate_material",
  "student_study",
  "prepare_exam",
  "fanout_persona_exams",
  "student_answer_batch",
  "aggregate_qa",
  "judge_score",
  "observer_analyze",
  "refine_material",
] as const;

export function useTiming(
  events: RunEvent[],
  runStartedAt?: number | null,
  isRunning?: boolean
) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!isRunning) return;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [isRunning]);

  const { records, currentStep, macroDurations } = useMemo(() => {
    const map = new Map<string, StepRecord>();
    let current: StepRecord | null = null;

    for (const e of events) {
      if (e.type === "step_start" && e.step) {
        const key = `${e.macro_iter ?? 0}:${e.batch ?? 0}:${e.step}`;
        const rec: StepRecord = {
          key,
          step: e.step,
          stepLabel: e.step_label || e.step,
          macroIter: e.macro_iter ?? 0,
          batch: e.batch ?? 0,
          startedAt: e.ts ?? 0,
          status: "running",
        };
        map.set(key, rec);
        current = rec;
      }
      if (e.type === "step_timing" && e.step) {
        const key = `${e.macro_iter ?? 0}:${e.batch ?? 0}:${e.step}`;
        const existing = map.get(key);
        const rec: StepRecord = {
          key,
          step: e.step,
          stepLabel: e.step_label || e.step,
          macroIter: e.macro_iter ?? 0,
          batch: e.batch ?? 0,
          durationMs: e.duration_ms ?? 0,
          startedAt: existing?.startedAt,
          status: e.outcome === "failed" ? "failed" : "done",
        };
        map.set(key, rec);
        if (current?.key === key) current = null;
      }
    }

    const records = [...map.values()].sort((a, b) => {
      if (a.macroIter !== b.macroIter) return a.macroIter - b.macroIter;
      if (a.batch !== b.batch) return a.batch - b.batch;
      const ai = PIPELINE_STEPS.indexOf(a.step as (typeof PIPELINE_STEPS)[number]);
      const bi = PIPELINE_STEPS.indexOf(b.step as (typeof PIPELINE_STEPS)[number]);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });

    const macroDurations = new Map<number, number>();
    for (const r of records) {
      if (r.durationMs) {
        macroDurations.set(
          r.macroIter,
          (macroDurations.get(r.macroIter) ?? 0) + r.durationMs
        );
      }
    }

    return { records, currentStep: current, macroDurations };
  }, [events]);

  const totalTrackedMs = records.reduce((s, r) => s + (r.durationMs ?? 0), 0);
  const runElapsedMs =
    runStartedAt && isRunning
      ? now - runStartedAt * 1000
      : runStartedAt
        ? (events.find((e) => e.type === "run_end")?.ts ?? Date.now() / 1000) *
            1000 -
          runStartedAt * 1000
        : totalTrackedMs;

  const currentStepElapsedMs = currentStep?.startedAt
    ? now - currentStep.startedAt * 1000
    : 0;

  const stepTotals = useMemo(() => {
    const totals = new Map<string, { label: string; ms: number; count: number }>();
    for (const r of records) {
      if (!r.durationMs) continue;
      const t = totals.get(r.step) ?? {
        label: r.stepLabel,
        ms: 0,
        count: 0,
      };
      t.ms += r.durationMs;
      t.count += 1;
      totals.set(r.step, t);
    }
    return [...totals.entries()]
      .map(([step, v]) => ({ step, ...v }))
      .sort((a, b) => b.ms - a.ms);
  }, [records]);

  const latestMacro = records.length
    ? Math.max(...records.map((r) => r.macroIter))
    : 0;

  return {
    records,
    currentStep,
    stepTotals,
    macroDurations,
    totalTrackedMs,
    runElapsedMs: Math.max(runElapsedMs, totalTrackedMs),
    currentStepElapsedMs,
    latestMacro,
    maxStepMs: Math.max(...stepTotals.map((s) => s.ms), 1),
  };
}

export function extractTimingEvents(events: RunEvent[]): StepTimingEvent[] {
  return events.filter(
    (e): e is StepTimingEvent => e.type === "step_timing" || e.type === "step_start"
  );
}
