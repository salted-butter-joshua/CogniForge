import type { StepRecord } from "../types";

const PHASES = [
  { id: "ingest", label: "摄入", steps: ["fetch_pages", "generate_material"] },
  { id: "learn", label: "学习", steps: ["student_study", "prepare_exam"] },
  { id: "exam", label: "考试", steps: ["fanout_persona_exams", "student_answer_batch", "aggregate_qa"] },
  { id: "judge", label: "评判", steps: ["judge_score", "observer_analyze"] },
  { id: "refine", label: "补强", steps: ["refine_material"] },
] as const;

interface Props {
  records: StepRecord[];
  currentStep: StepRecord | null;
  macroIter: number;
}

export default function PipelineProgress({ records, currentStep, macroIter }: Props) {
  const doneSteps = new Set(
    records.filter((r) => r.status === "done" && r.macroIter === macroIter).map((r) => r.step)
  );
  const activeStep = currentStep?.macroIter === macroIter ? currentStep.step : null;

  return (
    <div className="pipeline-progress">
      {PHASES.map((phase, i) => {
        const phaseSteps = phase.steps;
        const allDone = phaseSteps.every((s) => doneSteps.has(s));
        const isActive = phaseSteps.some((s) => s === activeStep);
        const isPartial = phaseSteps.some((s) => doneSteps.has(s)) && !allDone;

        return (
          <div key={phase.id} className="pipeline-phase-wrap">
            {i > 0 && (
              <div
                className={`pipeline-connector ${allDone || isPartial ? "done" : ""}`}
              />
            )}
            <div
              className={`pipeline-phase ${allDone ? "done" : ""} ${isActive ? "active" : ""} ${isPartial ? "partial" : ""}`}
            >
              <div className="pipeline-dot" />
              <span>{phase.label}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
