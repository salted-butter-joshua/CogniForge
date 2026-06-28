import { Coins, Gauge, Layers, Timer } from "lucide-react";
import { formatDuration, formatTokens } from "../utils/format";
import type { StepRecord } from "../types";

interface Props {
  runElapsedMs: number;
  currentStep: StepRecord | null;
  currentStepElapsedMs: number;
  stepTotals: { step: string; label: string; ms: number; count: number }[];
  maxStepMs: number;
  totalTrackedMs: number;
  latestMacro: number;
  macroDurations: Map<number, number>;
  isRunning: boolean;
  tokenTotal: number;
  tokensByStep: Record<string, number>;
}

export default function TimingPanel({
  runElapsedMs,
  currentStep,
  currentStepElapsedMs,
  stepTotals,
  maxStepMs,
  totalTrackedMs,
  latestMacro,
  macroDurations,
  isRunning,
  tokenTotal,
  tokensByStep,
}: Props) {
  const macroMs = macroDurations.get(latestMacro) ?? 0;

  return (
    <div className="timing-panel">
      <div className="timing-hero">
        <TimingStat
          icon={<Timer size={18} />}
          label="总耗时"
          value={formatDuration(runElapsedMs)}
          highlight={isRunning}
          sub={isRunning ? "运行中" : "已结束"}
        />
        <TimingStat
          icon={<Gauge size={18} />}
          label="当前步骤"
          value={
            currentStep
              ? formatDuration(currentStepElapsedMs)
              : stepTotals.length
                ? "—"
                : "等待"
          }
          sub={currentStep?.stepLabel ?? (isRunning ? "空闲/等待" : "—")}
          accent
        />
        <TimingStat
          icon={<Layers size={18} />}
          label={`本轮 M${String(latestMacro + 1).padStart(3, "0")}`}
          value={formatDuration(macroMs)}
          sub={`已追踪 ${formatDuration(totalTrackedMs)}`}
        />
        <TimingStat
          icon={<Coins size={18} />}
          label="Token 总量"
          value={formatTokens(tokenTotal)}
          sub={`${stepTotals.reduce((s, t) => s + t.count, 0)} 步 · ${stepTotals.length} 类节点`}
          gold
        />
      </div>

      {stepTotals.length > 0 && (
        <div className="timing-breakdown">
          <div className="timing-breakdown-header">
            <span>步骤耗时 / Token 分布</span>
            <span className="muted">按累计时间排序</span>
          </div>
          <div className="timing-bars">
            {stepTotals.slice(0, 8).map((s) => {
              const tok = tokensByStep[s.step] ?? 0;
              return (
                <div key={s.step} className="timing-bar-row">
                  <div className="timing-bar-label" title={s.step}>
                    {s.label}
                    {s.count > 1 && <span className="timing-count">×{s.count}</span>}
                  </div>
                  <div className="timing-bar-track">
                    <div
                      className="timing-bar-fill"
                      style={{ width: `${Math.max(4, (s.ms / maxStepMs) * 100)}%` }}
                    />
                  </div>
                  <div className="timing-bar-value">{formatDuration(s.ms)}</div>
                  <div className="timing-bar-tokens">{tok ? formatTokens(tok) : "—"}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function TimingStat({
  icon,
  label,
  value,
  sub,
  highlight,
  accent,
  gold,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  highlight?: boolean;
  accent?: boolean;
  gold?: boolean;
}) {
  return (
    <div
      className={`timing-stat ${highlight ? "live" : ""} ${accent ? "accent" : ""} ${gold ? "gold" : ""}`}
    >
      <div className="timing-stat-icon">{icon}</div>
      <div className="timing-stat-body">
        <div className="timing-stat-label">{label}</div>
        <div className="timing-stat-value">{value}</div>
        {sub && <div className="timing-stat-sub">{sub}</div>}
      </div>
    </div>
  );
}
