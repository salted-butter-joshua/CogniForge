import { useEffect, useRef } from "react";
import type { RunEvent } from "../types";
import { formatClock } from "../utils/format";

interface Props {
  events: RunEvent[];
  autoScroll?: boolean;
}

export default function LogViewer({ events, autoScroll = true }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [events, autoScroll]);

  const logEvents = events.filter(
    (e) =>
      e.type === "log" ||
      e.type === "metric" ||
      e.type === "error" ||
      e.type === "stop_requested" ||
      e.type === "step_timing"
  );

  return (
    <div className="panel log-viewer">
      <div className="log-toolbar">
        <span>
          日志流 <strong>{logEvents.length}</strong> 条
        </span>
        <span className="log-toolbar-meta">SSE 实时 · 含步骤耗时</span>
      </div>
      <div className="log-stream">
        {logEvents.length === 0 ? (
          <div className="empty-state">
            <ScrollIcon />
            <p>启动任务后，流水线日志将在此实时显示</p>
            <p className="muted">步骤完成时会标注耗时（duration=）</p>
          </div>
        ) : (
          logEvents.map((e, i) => <LogLine key={`${e.type}-${e.ts}-${i}`} event={e} />)
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function LogLine({ event }: { event: RunEvent }) {
  if (event.type === "step_timing") {
    return (
      <div className="log-line timing">
        <span className="log-ts">{event.ts ? formatClock(event.ts) : ""}</span>
        <span className="log-tag">DONE</span>
        {event.step_label || event.step}
        <span className="log-duration">{event.duration_label}</span>
        {event.batch ? <span className="log-meta">B{event.batch}</span> : null}
      </div>
    );
  }
  if (event.type === "metric") {
    const pct =
      event.accuracy_pct ??
      (event.accuracy != null ? (event.accuracy * 100).toFixed(1) : "?");
    return (
      <div className="log-line metric">
        <span className="log-tag">METRIC</span>
        M{String((event.macro_iter ?? 0) + 1).padStart(3, "0")} 正确率 {pct}%
      </div>
    );
  }
  if (event.type === "stop_requested") {
    return (
      <div className="log-line warning">
        <span className="log-tag">STOP</span>
        {event.message}
      </div>
    );
  }
  if (event.type === "error") {
    return (
      <div className="log-line error">
        <span className="log-tag">ERR</span>
        {event.message}
      </div>
    );
  }
  const level = (event.level || "INFO").toLowerCase();
  const cls =
    level === "error" ? "error" : level === "warning" || level === "warn" ? "warning" : "info";
  const isDone = event.message?.includes(" DONE ");
  return (
    <div className={`log-line ${cls} ${isDone ? "step-done" : ""}`}>
      {event.ts && <span className="log-ts">{formatClock(event.ts)}</span>}
      {event.message}
    </div>
  );
}

function ScrollIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.35">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  );
}
