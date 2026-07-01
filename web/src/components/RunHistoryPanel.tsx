import { History } from "lucide-react";
import type { RunSummary } from "../types";

const STATUS_LABEL: Record<string, string> = {
  running: "运行中",
  success: "成功",
  failed: "失败",
  cancelled: "已取消",
  cancelling: "停止中",
  stagnated: "停滞",
  max_iter_reached: "达上限",
  interrupted: "已中断",
};

interface Props {
  runs: RunSummary[];
  activeRunId: string | null;
  loading?: boolean;
  onSelect: (run: RunSummary) => void;
}

export default function RunHistoryPanel({
  runs,
  activeRunId,
  loading,
  onSelect,
}: Props) {
  if (loading) {
    return (
      <div className="run-history">
        <div className="run-history-title">
          <History size={14} />
          历史运行
        </div>
        <p className="run-history-empty">加载中…</p>
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="run-history">
        <div className="run-history-title">
          <History size={14} />
          历史运行
        </div>
        <p className="run-history-empty">暂无记录</p>
      </div>
    );
  }

  return (
    <div className="run-history">
      <div className="run-history-title">
        <History size={14} />
        历史运行
      </div>
      <ul className="run-history-list">
        {runs.slice(0, 12).map((run) => {
          const active = run.run_id === activeRunId;
          const rounds = run.accuracy_history?.length ?? 0;
          const pct =
            rounds > 0
              ? (Math.max(...run.accuracy_history) * 100).toFixed(0)
              : run.batch_accuracy > 0
                ? (run.batch_accuracy * 100).toFixed(0)
                : "—";
          return (
            <li key={run.run_id}>
              <button
                type="button"
                className={`run-history-item ${active ? "active" : ""}`}
                onClick={() => onSelect(run)}
              >
                <span className="run-history-label">
                  {run.label || run.task_id}
                </span>
                <span className="run-history-meta">
                  {STATUS_LABEL[run.status] ?? run.status}
                  {rounds > 0 ? ` · ${rounds}轮 · ${pct}%` : run.phase ? ` · ${run.phase}` : ""}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
