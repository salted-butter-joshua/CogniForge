import { useEffect, useState } from "react";
import { listRuns } from "../api";
import LearningCurve from "./LearningCurve";
import type { RunSummary } from "../types";

export default function ComparePanel() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);

  const refresh = () => {
    setLoading(true);
    listRuns()
      .then((data) => {
        const finished = data.filter(
          (r) => r.accuracy_history.length > 0 && r.status !== "running"
        );
        setRuns(finished);
        if (selected.size === 0 && finished.length > 0) {
          setSelected(new Set(finished.slice(0, 3).map((r) => r.run_id)));
        }
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    refresh();
  }, []);

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
                选择不同参数配置的历史运行，对比学习曲线，评估哪些调整更有效
              </p>
            </div>
            <button className="btn" style={{ background: "var(--accent-dim)", color: "var(--accent)", border: "1px solid var(--border)" }} onClick={refresh}>
              刷新
            </button>
          </div>
          {loading ? (
            <p style={{ color: "var(--text-muted)" }}>加载中…</p>
          ) : runs.length === 0 ? (
            <p style={{ color: "var(--text-muted)" }}>暂无已完成的历史运行</p>
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
                      {r.status} · {r.accuracy_history.length} 轮 · 最高{" "}
                      {r.accuracy_history.length
                        ? (Math.max(...r.accuracy_history) * 100).toFixed(1)
                        : 0}
                      % · closed_book=
                      {String(r.params?.closed_book_exam ?? "?")}
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
