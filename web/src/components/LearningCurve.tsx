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
import type { ChapterProgress, RoundRecord, RunSummary } from "../types";

const COLORS = ["#818cf8", "#a855f7", "#22d3ee", "#34d399", "#fbbf24", "#ec4899"];
const DIFF_LABELS = ["入门", "基础", "进阶", "挑战", "综合"];

function diffLabel(level: number): string {
  return DIFF_LABELS[Math.max(0, Math.min(4, level))] ?? String(level);
}

interface Props {
  runs: RunSummary[];
  targetAccuracy?: number;
  chapterMasteryAccuracy?: number;
  liveHistory?: number[];
  liveMacro?: number;
  roundRecords?: RoundRecord[];
  chapterProgress?: ChapterProgress[];
  learningMode?: string;
}

export default function LearningCurve({
  runs,
  targetAccuracy = 0.95,
  chapterMasteryAccuracy = 0.98,
  liveHistory,
  liveMacro,
  roundRecords,
  chapterProgress,
  learningMode,
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

  const progress =
    chapterProgress && chapterProgress.length > 0
      ? chapterProgress
      : selectedRec?.chapter_progress;

  return (
    <div className="panel">
      {learningMode === "chapter_mastery" && progress && progress.length > 0 && (
        <ChapterMasteryPanel
          chapters={progress}
          threshold={chapterMasteryAccuracy}
        />
      )}
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
                label={{ value: `全局目标 ${(targetAccuracy * 100).toFixed(0)}%`, fill: "#fbbf24", fontSize: 11 }}
              />
              {learningMode === "chapter_mastery" && (
                <ReferenceLine
                  y={chapterMasteryAccuracy * 100}
                  stroke="#34d399"
                  strokeDasharray="4 4"
                  label={{
                    value: `章节过关 ${(chapterMasteryAccuracy * 100).toFixed(0)}%`,
                    fill: "#34d399",
                    fontSize: 11,
                  }}
                />
              )}
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
          {rec.chapter_title ? (
            <div style={{ color: "#aeb3dc" }}>
              章节：{rec.chapter_title}
              {typeof rec.chapter_accuracy === "number"
                ? ` · 章正确率 ${(rec.chapter_accuracy * 100).toFixed(1)}%`
                : ""}
              {typeof rec.plain_accuracy === "number"
                ? ` ·  plain ${(rec.plain_accuracy * 100).toFixed(1)}%`
                : ""}
            </div>
          ) : (
            <div style={{ color: "#aeb3dc" }}>课程窗口：L{rec.curriculum_level}</div>
          )}
          {rec.judge_anomaly && (
            <div style={{ color: "#f87171", marginTop: 4 }}>
              ⚠ Judge 异常：{rec.judge_anomaly_reason || "评分可能未生效"}
            </div>
          )}
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
          <span className="rd-label">课程窗口</span>
          {record.chapter_title || `L${record.curriculum_level}`}
        </div>
        {typeof record.chapter_accuracy === "number" && (
          <div>
            <span className="rd-label">章节正确率</span>
            {(record.chapter_accuracy * 100).toFixed(1)}%
          </div>
        )}
        <div>
          <span className="rd-label">出题数</span>
          {record.question_count}
        </div>
        <div>
          <span className="rd-label">加权正确率</span>
          {(record.accuracy * 100).toFixed(1)}%
        </div>
        {typeof record.plain_accuracy === "number" && (
          <div>
            <span className="rd-label">plain 正确率</span>
            {(record.plain_accuracy * 100).toFixed(1)}%
          </div>
        )}
      </div>
      {(record.judge_anomaly ||
        record.reinforce_wrong ||
        record.long_term_notes_chars != null) && (
        <div className="round-detail-grid">
          {record.judge_anomaly && (
            <div style={{ gridColumn: "1 / -1", color: "#f87171" }}>
              <span className="rd-label">Judge 异常</span>
              {record.judge_anomaly_reason || "全部 0 分且无评分理由"}
              {record.empty_judge_reason_count != null &&
                ` · 空理由 ${record.empty_judge_reason_count}/${record.question_count}`}
            </div>
          )}
          {record.reinforce_wrong != null && (
            <div>
              <span className="rd-label">巩固题</span>
              对 {record.reinforce_correct ?? 0} / 错 {record.reinforce_wrong ?? 0}
            </div>
          )}
          {record.long_term_notes_chars != null && (
            <div>
              <span className="rd-label">记忆字符</span>
              长期 {record.long_term_notes_chars} · 工作 {record.short_term_notes_chars ?? 0}
            </div>
          )}
          {record.chapter_relevant_count != null && (
            <div>
              <span className="rd-label">章内题</span>
              {record.chapter_relevant_count}/{record.chapter_total_scored ?? record.question_count}
              {record.chapter_evidence_fallback ? "（证据未标章，已回退全量）" : ""}
            </div>
          )}
        </div>
      )}
      {record.settings_snapshot && (
        <div className="round-detail-row" style={{ fontSize: "0.85rem", color: "#aeb3dc" }}>
          <span className="rd-label">当轮参数</span>
          章门槛{" "}
          {((record.settings_snapshot.chapter_mastery_accuracy as number) * 100).toFixed(0)}%
          · Judge T={String(record.settings_snapshot.judge_temperature)}
          · 语义宽松={String(record.settings_snapshot.judge_semantic_lenient)}
          · 长期记忆占比={String(record.settings_snapshot.exam_long_term_ratio)}
        </div>
      )}
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
      {record.wrong_samples && record.wrong_samples.length > 0 && (
        <div className="round-detail-wrong-list">
          <div className="rd-label" style={{ marginBottom: 8 }}>
            错题与完整 Judge 理由
          </div>
          {record.wrong_samples.map((w, i) => (
            <div key={i} className="wrong-sample-block">
              <div className="wrong-sample-q">{w.question}</div>
              <div className="wrong-sample-a">
                <span className="rd-label">答</span> {w.answer}
              </div>
              <div className="wrong-sample-r">
                <span className="rd-label">评</span> {w.judge_reason || "（无理由）"}
              </div>
            </div>
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

function ChapterMasteryPanel({
  chapters,
  threshold,
}: {
  chapters: ChapterProgress[];
  threshold: number;
}) {
  const mastered = chapters.filter((c) => c.mastered).length;
  return (
    <div className="chapter-mastery-panel">
      <div className="chapter-mastery-head">
        <strong>章节掌握进度</strong>
        <span>
          {mastered}/{chapters.length} 章已掌握 · 门槛 {(threshold * 100).toFixed(0)}%
        </span>
      </div>
      <div className="chapter-mastery-list">
        {chapters.map((ch) => {
          const pct = Math.round(Math.max(ch.best_accuracy, ch.accuracy) * 100);
          const barPct = Math.min(pct, 100);
          const done = ch.mastered;
          return (
            <div key={ch.chapter_id} className={`chapter-row ${done ? "mastered" : ""}`}>
              <div className="chapter-row-title" title={ch.chapter_title}>
                <span className="chapter-idx">{ch.chapter_index + 1}</span>
                {ch.chapter_title}
              </div>
              <div className="chapter-bar-wrap">
                <div
                  className={`chapter-bar ${done ? "done" : ""}`}
                  style={{ width: `${barPct}%` }}
                />
              </div>
              <div className="chapter-stats">
                {done ? "✓" : `${pct}%`}
                {ch.attempts > 0 && !done ? ` · ${ch.attempts}次` : ""}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
