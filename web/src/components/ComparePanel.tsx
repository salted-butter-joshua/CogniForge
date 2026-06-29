import { useCallback, useEffect, useState } from "react";
import { listRuns } from "../api";
import LearningCurve from "./LearningCurve";
import type { RunSummary } from "../types";

interface Props {
  activeRunId?: string | null;
  onSelectRun?: (run: RunSummary) => void;
}

export default function ComparePanel({ activeRunId, onSelectRun }: Props) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    setLoading(true);
    listRuns()
      .then((data) => {
        const comparable = data.filter(
          (r) =>
            r.status !== "running" &&
            (r.accuracy_history.length > 0 ||
              r.macro_iter > 0 ||
              r.batch_accuracy > 0 ||
              Boolean(r.phase))
        );
        setRuns(comparable);
        setSelected((prev) => {
          if (prev.size > 0) {
            const kept = new Set(
              [...prev].filter((id) => comparable.some((r) => r.run_id === id))
            );
            if (kept.size > 0) return kept;
          }
          if (activeRunId && comparable.some((r) => r.run_id === activeRunId)) {
            return new Set([activeRunId]);
          }
          return new Set(comparable.slice(0, 3).map((r) => r.run_id));
        });
      })
      .finally(() => setLoading(false));
  }, [activeRunId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectedRuns = runs.filter((r) => selected.has(r.run_id));

  return (
    <div className="content-scroll">
      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-body">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div>
              <strong>实验对比</strong>
              <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: 4 }}>
                选择不同参数配置的历史运行，对比学习曲线（含已中断、进行中的部分进度）
              </p>
            </div>
            <button className="btn" style={{ background: "var(--accent-dim)", color: "var(--accent)", border: "1px solid var(--border)" }} onClick={refresh}>
              刷新
            </button>
          </div>
          {loading ? (
            <p style={{ color: "var(--text-muted)" }}>加载中…</p>
          ) : runs.length === 0 ? (
            <p style={{ color: "var(--text-muted)" }}>暂无可对比的历史运行（请先完成或中断至少一次任务）</p>
          ) : (
            <div className="compare-list">
              {runs.map((r) => (
                <label key={r.run_id} className="compare-item">
                  <input
                    type="checkbox"
                    checked={selected.has(r.run_id)}
                    onChange={() => toggle(r.run_id)}
                  />
                  <div className="compare-meta">
                    <strong>{r.label || r.task_id}</strong>
                    <span>
                      {r.status} · {r.accuracy_history.length || 0} 轮 · 最高{" "}
                      {r.accuracy_history.length
                        ? (Math.max(...r.accuracy_history) * 100).toFixed(1)
                        : (r.batch_accuracy * 100).toFixed(1)}
                      %
                      {onSelectRun && (
                        <>
                          {" · "}
                          <button
                            type="button"
                            className="btn btn-ghost"
                            style={{ padding: 0, fontSize: "inherit", color: "var(--accent)" }}
                            onClick={(e) => {
                              e.preventDefault();
                              onSelectRun(r);
                            }}
                          >
                            查看
                          </button>
                        </>
                      )}
                    </span>
                  </div>
                </label>
              ))}
            </div>
          )}
        </div>
      </div>
      <LearningCurve runs={selectedRuns} />
    </div>
  );
}
