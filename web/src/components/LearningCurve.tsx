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
import type { RunSummary } from "../types";

const COLORS = ["#22d3ee", "#fbbf24", "#a78bfa", "#34d399", "#f87171", "#60a5fa"];

interface Props {
  runs: RunSummary[];
  targetAccuracy?: number;
  liveHistory?: number[];
  liveMacro?: number;
}

export default function LearningCurve({
  runs,
  targetAccuracy = 0.95,
  liveHistory,
  liveMacro,
}: Props) {
  const chartData = buildChartData(runs, liveHistory, liveMacro);

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

  if (liveHistory && liveHistory.length > 0 && runs.length === 1) {
    // live series already merged in buildChartData
  }

  return (
    <div className="panel">
      <div className="panel-body" style={{ paddingBottom: 8 }}>
        <div className="chart-wrap">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 12, right: 24, left: 0, bottom: 8 }}>
              <CartesianGrid stroke="rgba(99,179,237,0.1)" strokeDasharray="3 3" />
              <XAxis
                dataKey="round"
                stroke="#8b9bb8"
                fontSize={12}
                label={{ value: "宏观迭代轮次", position: "insideBottom", offset: -2, fill: "#8b9bb8" }}
              />
              <YAxis
                stroke="#8b9bb8"
                fontSize={12}
                domain={[0, 100]}
                tickFormatter={(v) => `${v}%`}
              />
              <Tooltip
                contentStyle={{
                  background: "#0e1424",
                  border: "1px solid rgba(34,211,238,0.3)",
                  borderRadius: 10,
                  fontSize: 13,
                }}
                formatter={(value: number) => [`${value.toFixed(1)}%`, "正确率"]}
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
                  activeDot={{ r: 6 }}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
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
