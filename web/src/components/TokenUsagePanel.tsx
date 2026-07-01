import { Coins, TrendingUp } from "lucide-react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { RoundRecord } from "../types";
import { formatTokens } from "../utils/format";

const STEP_LABELS: Record<string, string> = {
  fetch_pages: "抓取",
  generate_material: "资料",
  student_study: "学习",
  prepare_exam: "备考",
  fanout_persona_exams: "出题",
  student_answer_batch: "作答",
  aggregate_qa: "汇总",
  judge_score: "评分",
  observer_analyze: "观察",
  refine_material: "精炼",
  consolidate_chapter_notes: "巩固",
  other: "其他",
};

interface Props {
  roundRecords?: RoundRecord[];
  liveTokenTotal?: number;
  liveTokenInput?: number;
  liveTokenOutput?: number;
  isRunning?: boolean;
}

interface TokenRow {
  round: number;
  macro_iter: number;
  roundTotal: number;
  roundInput: number;
  roundOutput: number;
  cumulative: number;
  inProgress?: boolean;
}

export default function TokenUsagePanel({
  roundRecords = [],
  liveTokenTotal = 0,
  liveTokenInput = 0,
  liveTokenOutput = 0,
  isRunning = false,
}: Props) {
  const rows = buildTokenRows(roundRecords, liveTokenTotal, liveTokenInput, liveTokenOutput, isRunning);
  const completed = roundRecords.filter((r) => (r.token_round_total ?? 0) > 0);
  const lastCum =
    completed.length > 0
      ? completed[completed.length - 1].token_cumulative_total ?? 0
      : 0;
  const displayTotal = isRunning ? liveTokenTotal : lastCum || liveTokenTotal;
  const avgRound =
    completed.length > 0
      ? Math.round(
          completed.reduce((s, r) => s + (r.token_round_total ?? 0), 0) / completed.length
        )
      : 0;
  const inProgressRow = rows.find((r) => r.inProgress);
  const selectedRoundSteps =
    completed.length > 0
      ? completed[completed.length - 1].tokens_by_step_round ?? {}
      : {};

  if (rows.length === 0 && !isRunning) {
    return (
      <div className="token-panel empty">
        <Coins size={20} />
        <span>完成至少一轮 Judge 后将显示 Token 用量</span>
      </div>
    );
  }

  return (
    <div className="token-panel">
      <div className="token-hero">
        <TokenStat
          icon={<Coins size={18} />}
          label="累计 Token"
          value={formatTokens(displayTotal)}
          sub={
            isRunning
              ? `输入 ${formatTokens(liveTokenInput)} · 输出 ${formatTokens(liveTokenOutput)}`
              : completed.length
                ? `共 ${completed.length} 轮已完成`
                : "—"
          }
          gold
        />
        <TokenStat
          icon={<TrendingUp size={18} />}
          label="平均每轮"
          value={avgRound ? formatTokens(avgRound) : "—"}
          sub={completed.length ? `最近一轮 ${formatTokens(completed.at(-1)?.token_round_total ?? 0)}` : "—"}
        />
        {inProgressRow && (
          <TokenStat
            label="进行中轮次"
            value={formatTokens(inProgressRow.roundTotal)}
            sub={`M${String(inProgressRow.round).padStart(3, "0")} 尚未 Judge 结算`}
            accent
          />
        )}
      </div>

      {rows.length > 0 && (
        <div className="token-chart-wrap">
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart data={rows.filter((r) => !r.inProgress)} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="rgba(139,140,248,0.1)" strokeDasharray="3 3" />
              <XAxis
                dataKey="round"
                stroke="#aeb3dc"
                fontSize={11}
                tickFormatter={(v) => `M${String(v).padStart(3, "0")}`}
              />
              <YAxis
                yAxisId="left"
                stroke="#aeb3dc"
                fontSize={11}
                tickFormatter={(v) => formatTokens(v)}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                stroke="#34d399"
                fontSize={11}
                tickFormatter={(v) => formatTokens(v)}
              />
              <Tooltip
                formatter={(value: number, name: string) => [
                  formatTokens(value),
                  name === "roundTotal" ? "本轮" : "累计",
                ]}
                labelFormatter={(label) => `第 ${label} 轮`}
                contentStyle={{
                  background: "#14162e",
                  border: "1px solid rgba(139,140,248,0.35)",
                  borderRadius: 10,
                  fontSize: 12,
                }}
              />
              <Legend />
              <Bar
                yAxisId="left"
                dataKey="roundTotal"
                name="本轮 Token"
                fill="rgba(129,140,248,0.55)"
                radius={[4, 4, 0, 0]}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="cumulative"
                name="累计 Token"
                stroke="#34d399"
                strokeWidth={2}
                dot={{ r: 3 }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="token-table-wrap">
        <div className="token-table-header">
          <span>逐轮用量</span>
          <span className="muted">本轮增量 / 累计</span>
        </div>
        <table className="token-table">
          <colgroup>
            <col className="col-round" />
            <col span={5} className="col-num" />
          </colgroup>
          <thead>
            <tr>
              <th>轮次</th>
              <th className="num">本轮</th>
              <th className="num">累计</th>
              <th className="num">输入</th>
              <th className="num">输出</th>
              <th className="num">调用</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.macro_iter}-${row.inProgress ? "live" : "done"}`} className={row.inProgress ? "live-row" : ""}>
                <td>
                  M{String(row.round).padStart(3, "0")}
                  {row.inProgress && <span className="token-live-tag">进行中</span>}
                </td>
                <td className="num">{formatTokens(row.roundTotal)}</td>
                <td className="num cumulative">{formatTokens(row.cumulative)}</td>
                <td className="num muted">{formatTokens(row.roundInput)}</td>
                <td className="num muted">{formatTokens(row.roundOutput)}</td>
                <td className="num muted">
                  {row.inProgress
                    ? "—"
                    : roundRecords.find((r) => r.macro_iter === row.macro_iter)?.token_calls_round ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {Object.keys(selectedRoundSteps).length > 0 && (
        <div className="token-step-breakdown">
          <div className="token-table-header">
            <span>最近一轮 · 节点分布</span>
          </div>
          <div className="token-step-chips">
            {Object.entries(selectedRoundSteps)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 8)
              .map(([step, tok]) => (
                <span key={step} className="token-step-chip">
                  {STEP_LABELS[step] ?? step} {formatTokens(tok)}
                </span>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

function buildTokenRows(
  records: RoundRecord[],
  liveTotal: number,
  liveInput: number,
  liveOutput: number,
  isRunning: boolean
): TokenRow[] {
  const sorted = [...records].sort((a, b) => a.macro_iter - b.macro_iter);
  const rows: TokenRow[] = sorted.map((r) => ({
    round: r.macro_iter + 1,
    macro_iter: r.macro_iter,
    roundTotal: r.token_round_total ?? 0,
    roundInput: r.token_round_input ?? 0,
    roundOutput: r.token_round_output ?? 0,
    cumulative: r.token_cumulative_total ?? 0,
  }));

  if (isRunning && liveTotal > 0) {
    const lastCum = rows.length ? rows[rows.length - 1].cumulative : 0;
    const delta = Math.max(0, liveTotal - lastCum);
    if (delta > 0 || rows.length === 0) {
      rows.push({
        round: rows.length ? rows[rows.length - 1].macro_iter + 2 : 1,
        macro_iter: rows.length ? rows[rows.length - 1].macro_iter + 1 : 0,
        roundTotal: rows.length ? delta : liveTotal,
        roundInput: rows.length ? Math.max(0, liveInput - (sorted.at(-1)?.token_cumulative_input ?? 0)) : liveInput,
        roundOutput: rows.length ? Math.max(0, liveOutput - (sorted.at(-1)?.token_cumulative_output ?? 0)) : liveOutput,
        cumulative: liveTotal,
        inProgress: true,
      });
    }
  }
  return rows;
}

function TokenStat({
  icon,
  label,
  value,
  sub,
  gold,
  accent,
}: {
  icon?: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  gold?: boolean;
  accent?: boolean;
}) {
  return (
    <div className={`token-stat ${gold ? "gold" : ""} ${accent ? "accent" : ""}`}>
      <div className="token-stat-icon">{icon ?? null}</div>
      <div className="token-stat-body">
        <div className="token-stat-label">{label}</div>
        <div className="token-stat-value">{value}</div>
        {sub && <div className="token-stat-sub">{sub}</div>}
      </div>
    </div>
  );
}
