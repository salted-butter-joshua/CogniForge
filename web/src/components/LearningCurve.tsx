import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { RoundRecord, RunSummary } from "../types";

const COLORS = ["#818cf8", "#a855f7", "#22d3ee", "#34d399", "#fbbf24", "#ec4899"];
const DIFF_LABELS = ["入门", "基础", "进阶", "挑战", "综合"];

function diffLabel(level: number): string {
  return DIFF_LABELS[Math.max(0, Math.min(4, level))] ?? String(level);
}

interface Props {
  runs: RunSummary[];
  targetAccuracy?: number;
  liveHistory?: number[];
  liveMacro?: number;
  roundRecords?: RoundRecord[];
}

export default function LearningCurve({
  runs,
  targetAccuracy = 0.95,
  liveHistory,
  liveMacro,
  roundRecords,
}: Props) {
  const [selectedRound, setSelectedRound] = useState<number | null>(null);
  const chartData = buildChartData(runs, liveHistory, liveMacro);
  const single = !!roundRecords && roundRecords.length > 0;

  if (chartData.length === 0) {
    return (
      <div className="panel">
        <div className="empty-state">
          <p>暂无学习曲线数据</p>
          <p style={{ marginTop: 8, fontSize: "0.85rem" }}>
            完成至少一轮 Judge 评分后，将按宏观迭代轮次绘制加权正确率
          </p>
        </div>
      </div>
    );
  }

  const seriesKeys = runs
    .filter((r) => r.accuracy_history.length > 0)
    .map((r) => r.label || r.task_id);

  const selectedRec =
    single && selectedRound
      ? roundRecords!.find((r) => r.macro_iter === selectedRound - 1) ?? null
      : null;

  return (
    <div className="panel">
      <div className="panel-body" style={{ paddingBottom: 8 }}>
        <div className="chart-wrap">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={chartData}
              margin={{ top: 12, right: 24, left: 0, bottom: 8 }}
              onClick={(s: { activeLabel?: string | number }) => {
                if (!single) return;
                const r = Number(s?.activeLabel);
                if (r) setSelectedRound(r);
              }}
            >
              <CartesianGrid stroke="rgba(139,140,248,0.12)" strokeDasharray="3 3" />
              <XAxis
                dataKey="round"
                stroke="#aeb3dc"
                fontSize={12}
                label={{ value: "宏观迭代轮次", position: "insideBottom", offset: -2, fill: "#aeb3dc" }}
              />
              <YAxis
                stroke="#aeb3dc"
                fontSize={12}
                domain={[0, 100]}
                tickFormatter={(v) => `${v}%`}
              />
              <Tooltip
                content={single ? <RoundTooltip records={roundRecords!} /> : undefined}
                formatter={
                  !single ? (value: number) => [`${value.toFixed(1)}%`, "正确率"] : undefined
                }
                contentStyle={{
                  background: "#14162e",
                  border: "1px solid rgba(139,140,248,0.35)",
                  borderRadius: 10,
                  fontSize: 13,
                }}
              />
              <Legend />
              <ReferenceLine
                y={targetAccuracy * 100}
                stroke="#fbbf24"
                strokeDasharray="6 4"
                label={{ value: `目标 ${(targetAccuracy * 100).toFixed(0)}%`, fill: "#fbbf24", fontSize: 11 }}
              />
              {seriesKeys.map((key, i) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={COLORS[i % COLORS.length]}
                  strokeWidth={2.5}
                  dot={{ r: 4, fill: COLORS[i % COLORS.length] }}
                  activeDot={{ r: 6, cursor: single ? "pointer" : "default" }}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        {single && <RoundDetail record={selectedRec} picked={selectedRound !== null} />}
      </div>
    </div>
  );
}

function RoundTooltip({
  records,
  active,
  payload,
  label,
}: {
  records: RoundRecord[];
  active?: boolean;
  payload?: { value?: number }[];
  label?: string | number;
}) {
  if (!active || !payload || !payload.length) return null;
  const round = Number(label);
  const rec = records.find((r) => r.macro_iter === round - 1);
  const acc = payload[0]?.value;
  const topics = rec ? Object.entries(rec.topic_counts || {}).slice(0, 4) : [];
  return (
    <div
      style={{
        background: "#14162e",
        border: "1px solid rgba(139,140,248,0.35)",
        borderRadius: 10,
        padding: "10px 12px",
        fontSize: 12.5,
        maxWidth: 280,
        color: "#f5f6ff",
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: 4 }}>
        第 {round} 轮 · 正确率 {typeof acc === "number" ? acc.toFixed(1) : acc}%
      </div>
      {rec ? (
        <>
          <div style={{ color: "#aeb3dc" }}>
            难度：<b style={{ color: "#c4b5fd" }}>{diffLabel(rec.difficulty_level)}</b>（L
            {rec.difficulty_level}） · 出题 {rec.question_count} · 答对 {rec.correct}
          </div>
          <div style={{ color: "#aeb3dc" }}>课程窗口：L{rec.curriculum_level}</div>
          {topics.length > 0 && (
            <div style={{ marginTop: 4, color: "#aeb3dc" }}>
              题型：{topics.map(([k, v]) => `${k}×${v}`).join("，")}
            </div>
          )}
          <div style={{ marginTop: 5, color: "#6f74a6", fontSize: 11 }}>点击该点查看完整详情</div>
        </>
      ) : (
        <div style={{ color: "#6f74a6" }}>该轮暂无明细</div>
      )}
    </div>
  );
}

function RoundDetail({ record, picked }: { record: RoundRecord | null; picked: boolean }) {
  if (!record) {
    return (
      <div className="round-detail-hint">
        {picked ? "该轮暂无详情" : "💡 点击曲线上的点，查看该轮的难度、题型分布与薄弱点"}
      </div>
    );
  }
  const topics = Object.entries(record.topic_counts || {});
  return (
    <div className="round-detail">
      <div className="round-detail-head">
        <strong>第 {record.macro_iter + 1} 轮详情</strong>
        <span>
          正确率 {(record.accuracy * 100).toFixed(1)}%（{record.correct}/{record.question_count}）
        </span>
      </div>
      <div className="round-detail-grid">
        <div>
          <span className="rd-label">难度</span>
          {diffLabel(record.difficulty_level)}（L{record.difficulty_level}）
        </div>
        <div>
          <span className="rd-label">课程窗口</span>L{record.curriculum_level}
        </div>
        <div>
          <span className="rd-label">出题数</span>
          {record.question_count}
        </div>
        <div>
          <span className="rd-label">加权正确率</span>
          {(record.accuracy * 100).toFixed(1)}%
        </div>
      </div>
      {topics.length > 0 && (
        <div className="round-detail-row">
          <span className="rd-label">题型分布</span>
          {topics.map(([k, v]) => (
            <span key={k} className="rd-chip">
              {k} ×{v}
            </span>
          ))}
        </div>
      )}
      {record.weak_topics?.length > 0 && (
        <div className="round-detail-row">
          <span className="rd-label">薄弱点</span>
          {record.weak_topics.map((t) => (
            <span key={t} className="rd-chip warn">
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function buildChartData(
  runs: RunSummary[],
  liveHistory?: number[],
  liveMacro?: number
) {
  const enriched = runs.map((r) => {
    if (liveHistory && liveHistory.length > 0 && runs.length === 1) {
      return { ...r, accuracy_history: liveHistory, macro_iter: liveMacro ?? r.macro_iter };
    }
    return r;
  });

  const withData = enriched.filter((r) => r.accuracy_history.length > 0);
  if (withData.length === 0) return [];

  const maxLen = Math.max(...withData.map((r) => r.accuracy_history.length));
  const rows: Record<string, number | string>[] = [];

  for (let i = 0; i < maxLen; i++) {
    const row: Record<string, number | string> = { round: i + 1 };
    for (const r of withData) {
      const key = r.label || r.task_id;
      if (i < r.accuracy_history.length) {
        row[key] = Math.round(r.accuracy_history[i] * 1000) / 10;
      }
    }
    rows.push(row);
  }
  return rows;
}
