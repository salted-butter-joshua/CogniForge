import {
  Activity,
  FlaskConical,
  Play,
  Rocket,
  ScrollText,
  Square,
  Timer,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchSchema,
  getRun,
  startRun,
  stopRun,
  subscribeEvents,
} from "./api";
import ComparePanel from "./components/ComparePanel";
import LearningCurve from "./components/LearningCurve";
import LogViewer from "./components/LogViewer";
import ParamFields from "./components/ParamFields";
import PipelineProgress from "./components/PipelineProgress";
import TimingPanel from "./components/TimingPanel";
import { useTiming } from "./hooks/useTiming";
import type { ParamPreset, RunEvent, RunSummary, TabId } from "./types";
import { formatDuration } from "./utils/format";

const DEFAULT_URLS = "https://docs.python.org/3/tutorial/index.html";

export default function App() {
  const [tab, setTab] = useState<TabId>("launch");
  const [fields, setFields] = useState<import("./types").ParamField[]>([]);
  const [presets, setPresets] = useState<ParamPreset[]>([]);
  const [activePreset, setActivePreset] = useState("development");
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [urlsText, setUrlsText] = useState(DEFAULT_URLS);
  const [goal, setGoal] = useState("掌握所提供文档的核心知识");
  const [label, setLabel] = useState("");

  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [activeSummary, setActiveSummary] = useState<RunSummary | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSchema().then((schema) => {
      setFields(schema.fields);
      setPresets(schema.presets ?? []);
      setActivePreset(schema.default_preset ?? "development");
      const defaults: Record<string, unknown> = {};
      for (const f of schema.fields) {
        defaults[f.key] = f.default;
      }
      setParams(defaults);
      const goalField = schema.fields.find((f) => f.key === "goal");
      if (goalField) setGoal(String(goalField.default));
    });
  }, []);

  const isRunning = activeSummary?.status === "running";

  const timing = useTiming(events, activeSummary?.created_at, isRunning);

  const liveHistory = useMemo(() => {
    const fromEvents = events
      .filter((e) => e.type === "metric" && e.history)
      .map((e) => e.history!)
      .pop();
    if (fromEvents) return fromEvents;
    return activeSummary?.accuracy_history ?? [];
  }, [events, activeSummary]);

  const handleEvent = useCallback(
    (raw: unknown) => {
      const e = raw as RunEvent;
      if (e.type === "_eof") return;
      if (e.type === "snapshot" && e.summary) {
        setActiveSummary(e.summary);
        return;
      }
      if (e.type === "run_end") {
        if (activeRunId) {
          getRun(activeRunId).then(setActiveSummary).catch(() => {});
        }
        return;
      }
      setEvents((prev) => [...prev.slice(-4000), e]);
    },
    [activeRunId]
  );

  useEffect(() => {
    if (!activeRunId) return;
    const unsub = subscribeEvents(activeRunId, handleEvent);
    const poll = setInterval(() => {
      getRun(activeRunId).then(setActiveSummary).catch(() => {});
    }, 5000);
    return () => {
      unsub();
      clearInterval(poll);
    };
  }, [activeRunId, handleEvent]);

  const applyPreset = (preset: ParamPreset) => {
    setActivePreset(preset.id);
    setParams((p) => ({ ...p, ...preset.values }));
  };

  const handleStart = async () => {
    setError(null);
    setStarting(true);
    setEvents([]);
    try {
      const urls = urlsText
        .split(/[\n,]+/)
        .map((u) => u.trim())
        .filter(Boolean);
      if (!urls.length) throw new Error("请至少输入一个 URL");

      const body = {
        ...params,
        urls,
        goal,
        label: label || `run-${Date.now().toString(36)}`,
      };
      const { run_id } = await startRun(body);
      setActiveRunId(run_id);
      const summary = await getRun(run_id);
      setActiveSummary(summary);
      setTab("logs");
    } catch (e) {
      setError(e instanceof Error ? e.message : "启动失败");
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async () => {
    if (!activeRunId) return;
    try {
      await stopRun(activeRunId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "停止失败");
    }
  };

  const setParam = (key: string, value: unknown) => {
    setParams((p) => ({ ...p, [key]: value }));
  };

  const navItems: { id: TabId; label: string; icon: React.ReactNode }[] = [
    { id: "launch", label: "启动", icon: <Rocket size={17} /> },
    { id: "logs", label: "监控", icon: <ScrollText size={17} /> },
    { id: "curve", label: "曲线", icon: <Activity size={17} /> },
    { id: "compare", label: "对比", icon: <FlaskConical size={17} /> },
  ];

  const titles: Record<TabId, { title: string; sub: string }> = {
    launch: {
      title: "启动控制台",
      sub: "开发调试预设已启用 — 少题量、大批次，单轮约 15–25 分钟",
    },
    logs: {
      title: "运行监控",
      sub: "实时耗时、流水线进度与 LangGraph 步骤日志",
    },
    curve: {
      title: "学习曲线",
      sub: "按宏观迭代轮次展示 Judge 加权正确率",
    },
    compare: {
      title: "实验对比",
      sub: "对比不同参数配置下的学习曲线",
    },
  };

  const statusLabel: Record<string, string> = {
    running: "运行中",
    success: "成功",
    failed: "失败",
    cancelled: "已取消",
    stagnated: "停滞",
    max_iter_reached: "达上限",
    interrupted: "已中断",
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <div className="brand-icon">
              <Zap size={20} strokeWidth={2.5} />
            </div>
            <div>
              <h1>CogniForge</h1>
              <p>Loop Engineering</p>
            </div>
          </div>
        </div>
        <nav className="nav">
          {navItems.map((item) => (
            <button
              key={item.id}
              className={`nav-btn ${tab === item.id ? "active" : ""}`}
              onClick={() => setTab(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
              {item.id === "logs" && isRunning && <span className="nav-live" />}
            </button>
          ))}
        </nav>
        {isRunning && (
          <div className="sidebar-run-timer">
            <Timer size={14} />
            <span>{formatDuration(timing.runElapsedMs)}</span>
          </div>
        )}
        <div className="sidebar-footer">
          认知闭环引擎
          <br />
          <span className="muted">摄入 → 学习 → 考试 → 评判 → 观察</span>
        </div>
      </aside>

      <main className="main">
        <header className="main-header">
          <div>
            <h2>{titles[tab].title}</h2>
            <p className="subtitle">{titles[tab].sub}</p>
          </div>
          {activeSummary && (
            <div className="header-status">
              {isRunning && timing.currentStep && (
                <div className="current-step-chip">
                  {timing.currentStep.stepLabel}
                  <span>{formatDuration(timing.currentStepElapsedMs)}</span>
                </div>
              )}
              <div className={`status-pill ${activeSummary.status}`}>
                <span className="status-dot" />
                {statusLabel[activeSummary.status] ?? activeSummary.status}
                <span className="status-task">{activeSummary.task_id}</span>
              </div>
            </div>
          )}
        </header>

        {error && <div className="alert alert-error">{error}</div>}

        {tab === "launch" && (
          <div className="content-scroll">
            <div className="grid-2">
              <div className="panel">
                <div className="panel-head">
                  <h3>任务配置</h3>
                  <span className="panel-badge">输入</span>
                </div>
                <div className="panel-body">
                  <div className="field">
                    <label>学习 URL</label>
                    <textarea
                      value={urlsText}
                      disabled={isRunning}
                      onChange={(e) => setUrlsText(e.target.value)}
                      placeholder="每行一个或逗号分隔"
                    />
                  </div>
                  <div className="field">
                    <label>学习目标</label>
                    <input
                      type="text"
                      value={goal}
                      disabled={isRunning}
                      onChange={(e) => setGoal(e.target.value)}
                    />
                  </div>
                  <div className="field">
                    <label>实验标签</label>
                    <input
                      type="text"
                      value={label}
                      disabled={isRunning}
                      onChange={(e) => setLabel(e.target.value)}
                      placeholder="用于曲线对比，如：调试-50题"
                    />
                  </div>
                  <div className="action-bar">
                    <button
                      className="btn btn-primary"
                      disabled={isRunning || starting}
                      onClick={handleStart}
                    >
                      <Play size={17} />
                      {starting ? "启动中…" : "启动学习 Loop"}
                    </button>
                    <button
                      className="btn btn-danger"
                      disabled={!isRunning}
                      onClick={handleStop}
                    >
                      <Square size={15} fill="currentColor" />
                      停止
                    </button>
                  </div>
                </div>
              </div>
              <div className="panel">
                <div className="panel-head">
                  <h3>Loop 参数</h3>
                  <div className="preset-chips">
                    {presets.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        className={`preset-chip ${activePreset === p.id ? "active" : ""}`}
                        disabled={isRunning}
                        title={p.description}
                        onClick={() => applyPreset(p)}
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="panel-body panel-body-scroll">
                  <ParamFields
                    fields={fields}
                    values={params}
                    onChange={setParam}
                    disabled={isRunning}
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {tab === "logs" && (
          <div className="logs-layout">
            <TimingPanel
              runElapsedMs={timing.runElapsedMs}
              currentStep={timing.currentStep}
              currentStepElapsedMs={timing.currentStepElapsedMs}
              stepTotals={timing.stepTotals}
              maxStepMs={timing.maxStepMs}
              totalTrackedMs={timing.totalTrackedMs}
              latestMacro={timing.latestMacro}
              macroDurations={timing.macroDurations}
              isRunning={!!isRunning}
              tokenTotal={activeSummary?.token_total ?? 0}
              tokensByStep={activeSummary?.tokens_by_step ?? {}}
            />

            {activeSummary && (
              <>
                <PipelineProgress
                  records={timing.records}
                  currentStep={timing.currentStep}
                  macroIter={activeSummary.macro_iter}
                />
                <div className="metric-cards">
                  <MetricCard label="宏观轮次" value={`M${String(activeSummary.macro_iter + 1).padStart(3, "0")}`} />
                  <MetricCard
                    label="正确率"
                    value={`${(activeSummary.batch_accuracy * 100).toFixed(1)}%`}
                    accent
                  />
                  <MetricCard label="阶段" value={phaseLabel(activeSummary.phase)} />
                  <MetricCard
                    label="当前出题数量"
                    value={String(activeSummary.current_questions ?? 0)}
                    gold
                    live={isRunning}
                  />
                </div>
              </>
            )}

            <LogViewer events={events} />
          </div>
        )}

        {tab === "curve" && (
          <div className="content-scroll">
            {activeSummary && (
              <div className="metric-cards" style={{ marginBottom: 20 }}>
                <MetricCard label="任务" value={activeSummary.task_id} compact />
                <MetricCard
                  label="最新正确率"
                  value={`${(activeSummary.batch_accuracy * 100).toFixed(1)}%`}
                  accent
                />
                <MetricCard label="状态" value={statusLabel[activeSummary.status] ?? activeSummary.status} />
                <MetricCard
                  label="目标"
                  value={`${((params.target_accuracy as number) ?? 0.85) * 100}%`}
                  gold
                />
              </div>
            )}
            <LearningCurve
              runs={activeSummary ? [activeSummary] : []}
              targetAccuracy={(params.target_accuracy as number) ?? 0.85}
              liveHistory={liveHistory}
              liveMacro={activeSummary?.macro_iter}
              roundRecords={activeSummary?.round_records}
            />
          </div>
        )}

        {tab === "compare" && <ComparePanel />}
      </main>
    </div>
  );
}

function phaseLabel(phase: string): string {
  const map: Record<string, string> = {
    fetch: "抓取",
    generate_material: "生成资料",
    student_study: "学习",
    prepare_exam: "准备考试",
    persona_exam_fanout: "出题",
    student_answer_batch: "作答",
    exam_batch_router: "批次调度",
    judge_score: "评分",
    observer_analyze: "观察",
    macro_router: "迭代判定",
    done: "完成",
  };
  return map[phase] || phase || "—";
}

function MetricCard({
  label,
  value,
  accent,
  gold,
  compact,
  live,
}: {
  label: string;
  value: string;
  accent?: boolean;
  gold?: boolean;
  compact?: boolean;
  live?: boolean;
}) {
  return (
    <div className={`metric-card ${live ? "live" : ""}`}>
      <div className="label">{label}</div>
      <div
        className={`value ${accent ? "accent" : ""} ${gold ? "gold" : ""}`}
        style={{
          fontSize: compact || value.length > 14 ? "1.05rem" : undefined,
        }}
      >
        {value}
      </div>
    </div>
  );
}
