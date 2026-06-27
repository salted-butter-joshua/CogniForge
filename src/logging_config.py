"""Structured logging for Learn Loop — suppress noisy libs, uniform step logs."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

# Human-readable step names (parent graph)
STEP_LABELS: dict[str, str] = {
    "fetch_pages": "抓取网页",
    "generate_material": "生成学习资料",
    "student_study": "学生学习",
    "prepare_exam": "准备考试",
    "begin_persona_fanout": "出题批次准备",
    "fanout_persona_exams": "五角色出题",
    "persona_exam": "五角色并行出题",
    "merge_persona_questions": "合并题目",
    "student_answer_batch": "学生作答",
    "aggregate_qa": "汇总 Q&A",
    "judge_score": "Judge 评分",
    "student_progress": "答题进度",
    "observer_analyze": "观察者分析",
    "refine_material": "补强资料",
    "finalize": "结束",
}

# Column widths for aligned terminal output (ASCII fields only)
_TASK_W = 18
_LOOP_W = 8
_STEP_W = 26
_EVENT_W = 5

_QUIET_LOGGERS = (
    "litellm",
    "LiteLLM",
    "httpx",
    "httpcore",
    "openai",
    "urllib3",
    "langchain",
    "langchain_core",
    "langchain_litellm",
    "langgraph",
    "langgraph.checkpoint.redis",
)

# Nodes that return macro_iter as +N delta (state reducer = operator.add)
_MACRO_DELTA_STEPS = frozenset({"refine_material"})

_step_starts: dict[tuple, float] = {}
_step_hook: Callable[[dict[str, Any]], None] | None = None
_hook_lock = threading.Lock()


def set_step_event_hook(fn: Callable[[dict[str, Any]], None] | None) -> None:
    """Register callback for step start/done events (used by web console SSE)."""
    global _step_hook
    with _hook_lock:
        _step_hook = fn


def _step_key(state: dict[str, Any], step: str) -> tuple:
    return (
        state.get("task_id", "-"),
        int(state.get("macro_iter", 0) or 0),
        int(state.get("exam_batch_index", 0) or 0),
        step,
    )


def _emit_step_event(payload: dict[str, Any]) -> None:
    with _hook_lock:
        hook = _step_hook
    if hook:
        try:
            hook(payload)
        except Exception:
            pass


def _unwrap_value(value: Any) -> Any:
    if value is None:
        return None
    if type(value).__name__ == "Overwrite" and hasattr(value, "value"):
        return value.value
    return value


def _safe_len(value: Any) -> int | None:
    value = _unwrap_value(value)
    if isinstance(value, (list, tuple, dict, str)):
        n = len(value)
        return n if n else None
    return None


def setup_logging(level: str | None = None) -> None:
    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    fmt = "%(asctime)s | %(levelname)-5s | %(message)s"
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO), format=fmt, force=True)

    quiet = os.getenv("LOG_LLM", "").lower() not in ("1", "true", "yes")
    if quiet:
        for name in _QUIET_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger("learn_loop").setLevel(getattr(logging, log_level, logging.INFO))


def get_loop_logger() -> logging.Logger:
    return logging.getLogger("learn_loop")


def _ctx(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": state.get("task_id", "-"),
        "macro": int(state.get("macro_iter", 0) or 0),
        "batch": int(state.get("exam_batch_index", 0) or 0),
        "status": state.get("status", "running"),
    }


def _loop_tag(macro: int, batch: int = 0, show_batch: bool = False) -> str:
    tag = f"M{macro:03d}"
    if show_batch and batch:
        tag += f"/B{batch:02d}"
    return tag


def _macro_after(step: str, state_macro: int, result: dict[str, Any]) -> int | None:
    if "macro_iter" not in result:
        return None
    raw = result["macro_iter"]
    if not isinstance(raw, int):
        return None
    if step in _MACRO_DELTA_STEPS:
        return state_macro + raw
    return raw if raw != state_macro else None


def _format_line(
    task: str,
    macro: int,
    step: str,
    event: str,
    *,
    batch: int = 0,
    show_batch: bool = False,
    detail: str = "",
) -> str:
    task_s = (task[: _TASK_W - 1] + "…") if len(task) > _TASK_W else task
    label = STEP_LABELS.get(step, "")
    core = (
        f"{task_s:<{_TASK_W}} "
        f"{_loop_tag(macro, batch, show_batch):<{_LOOP_W}} "
        f"{step:<{_STEP_W}} "
        f"{event:<{_EVENT_W}} "
        f"{label}"
    )
    if detail:
        return f"{core} | {detail}"
    return core


def _batch_relevant(step: str) -> bool:
    return step in {
        "begin_persona_fanout",
        "fanout_persona_exams",
        "persona_exam",
        "merge_persona_questions",
        "student_answer_batch",
        "prepare_exam",
    }


def _build_detail(state: dict[str, Any], step: str, *, result: dict[str, Any] | None = None) -> str:
    parts: list[str] = []
    src = result if result is not None else state

    if state.get("phase") and step not in ("finalize",):
        parts.append(f"phase={src.get('phase', state.get('phase'))}")

    if _batch_relevant(step) and state.get("exam_batches_target"):
        parts.append(f"batches={state['exam_batches_target']}")

    if step in {"begin_persona_fanout", "fanout_persona_exams", "persona_exam", "merge_persona_questions"}:
        if state.get("questions_per_persona"):
            parts.append(f"q/persona={state['questions_per_persona']}")
        parts.append("personas=5")

    if result is not None:
        chunks = _safe_len(result.get("raw_chunks"))
        if chunks:
            parts.append(f"chunks={chunks}")

        questions_n = _safe_len(result.get("current_batch_questions"))
        if questions_n is None:
            questions_n = _safe_len(result.get("final_questions"))
        if questions_n:
            parts.append(f"questions={questions_n}")

        qa_n = _safe_len(result.get("current_batch_qa"))
        if qa_n:
            parts.append(f"qa={qa_n}")
        if result.get("judge_skipped"):
            parts.append("judge_skipped=true")
            if result.get("judge_skip_reason"):
                parts.append(f"reason={result['judge_skip_reason']}")

        acc = result.get("batch_accuracy")
        if isinstance(acc, (int, float)):
            parts.append(f"accuracy={acc * 100:.1f}%")

        counts = result.get("persona_counts")
        if isinstance(counts, dict) and counts:
            summary = ",".join(f"{pid}:{n}" for pid, n in sorted(counts.items()))
            parts.append(f"by_persona={summary}")

        macro_after = _macro_after(step, _ctx(state)["macro"], result)
        if macro_after is not None and macro_after != _ctx(state)["macro"]:
            parts.append(f"next=M{macro_after:03d}")

        if result.get("status") == "failed":
            err = result.get("error_message", "")
            if err:
                parts.append(f"error={err}")

    return " ".join(parts)


def log_step_start(state: dict[str, Any], step: str, **extra: Any) -> None:
    c = _ctx(state)
    _step_starts[_step_key(state, step)] = time.perf_counter()
    detail = _build_detail(state, step)
    if extra:
        extra_s = " ".join(f"{k}={v}" for k, v in extra.items())
        detail = f"{detail} {extra_s}".strip()
    line = _format_line(
        c["task"],
        c["macro"],
        step,
        "START",
        batch=c["batch"],
        show_batch=_batch_relevant(step),
        detail=detail,
    )
    get_loop_logger().info(line)
    _emit_step_event(
        {
            "type": "step_start",
            "step": step,
            "step_label": STEP_LABELS.get(step, step),
            "macro_iter": c["macro"],
            "batch": c["batch"],
            "ts": time.time(),
        }
    )


def _format_duration(ms: int) -> str:
    if ms < 1000:
        return f"{ms}ms"
    sec = ms / 1000
    if sec < 60:
        return f"{sec:.1f}s"
    minutes = int(sec // 60)
    rem = sec % 60
    if minutes < 60:
        return f"{minutes}m{rem:02.0f}s"
    hours = minutes // 60
    return f"{hours}h{minutes % 60:02d}m"


def log_step_done(state: dict[str, Any], step: str, result: dict[str, Any], **extra: Any) -> None:
    c = _ctx(state)
    outcome = result.get("status", "ok")
    if outcome == "running" or not outcome:
        outcome = "ok"

    key = _step_key(state, step)
    started = _step_starts.pop(key, None)
    duration_ms: int | None = None
    if started is not None:
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))

    detail = _build_detail(state, step, result=result)
    if duration_ms is not None:
        detail = f"duration={_format_duration(duration_ms)} {detail}".strip()
    if extra:
        extra_s = " ".join(f"{k}={v}" for k, v in extra.items())
        detail = f"{detail} {extra_s}".strip()
    if outcome not in ("ok", "running"):
        detail = f"outcome={outcome} {detail}".strip()

    batch = int(result.get("exam_batch_index", c["batch"]) or 0)
    line = _format_line(
        c["task"],
        c["macro"],
        step,
        "DONE",
        batch=batch,
        show_batch=_batch_relevant(step),
        detail=detail,
    )

    logger = get_loop_logger()
    if outcome == "failed":
        logger.error(line)
    else:
        logger.info(line)

    if duration_ms is not None:
        _emit_step_event(
            {
                "type": "step_timing",
                "step": step,
                "step_label": STEP_LABELS.get(step, step),
                "duration_ms": duration_ms,
                "duration_label": _format_duration(duration_ms),
                "macro_iter": c["macro"],
                "batch": batch,
                "outcome": outcome,
                "ts": time.time(),
            }
        )


def log_step_warn(state: dict[str, Any], step: str, message: str, **extra: Any) -> None:
    c = _ctx(state)
    detail = f"msg={message}"
    if extra:
        detail += " " + " ".join(f"{k}={v}" for k, v in extra.items())
    line = _format_line(c["task"], c["macro"], step, "WARN", detail=detail)
    get_loop_logger().warning(line)


def log_boot(message: str) -> None:
    get_loop_logger().info(f"{'BOOT':<{_TASK_W}} {'':<{_LOOP_W}} {'':<{_STEP_W}} {'':<{_EVENT_W}} {message}")


def log_finish(message: str, *, level: int = logging.INFO) -> None:
    get_loop_logger().log(
        level,
        f"{'FINISH':<{_TASK_W}} {'':<{_LOOP_W}} {'':<{_STEP_W}} {'':<{_EVENT_W}} {message}",
    )


def _progress_interval() -> int:
    raw = os.getenv("LOG_PROGRESS_EVERY", "5")
    try:
        n = int(raw)
        return max(1, n)
    except ValueError:
        return 5


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _indent_line(text: str) -> str:
    return f"{'':<{_TASK_W}} {'':<{_LOOP_W}} {'':<{_STEP_W}} {'':<{_EVENT_W}} {text}"


def log_student_progress(
    state: dict[str, Any],
    scored_qa: list[dict[str, Any]],
    accuracy: float,
    weak_topics: list[str],
    *,
    weak_counter: dict[str, int] | None = None,
) -> None:
    """Every N macro rounds, emit a multi-line student answer summary."""
    macro = int(state.get("macro_iter", 0) or 0)
    interval = _progress_interval()
    if (macro + 1) % interval != 0:
        return

    task = state.get("task_id", "-")
    total = len(scored_qa)
    correct = sum(1 for q in scored_qa if q.get("is_correct"))
    wrong = total - correct

    by_persona: dict[str, list[dict]] = {}
    for qa in scored_qa:
        pid = qa.get("persona_id") or qa.get("persona_name") or "?"
        by_persona.setdefault(pid, []).append(qa)

    persona_parts: list[str] = []
    for pid in sorted(by_persona):
        items = by_persona[pid]
        ok = sum(1 for q in items if q.get("is_correct"))
        persona_parts.append(f"{pid}={ok}/{len(items)}")

    history = list(state.get("accuracy_history") or [])
    history.append(accuracy)
    recent = history[-interval:]
    trend = "->".join(f"{a * 100:.0f}%" for a in recent)

    weak_parts: list[str] = []
    if weak_counter:
        for topic, cnt in sorted(weak_counter.items(), key=lambda x: -x[1])[:5]:
            weak_parts.append(f"{topic}({cnt})")
    elif weak_topics:
        weak_parts = weak_topics[:5]

    wrong_samples: list[dict] = [q for q in scored_qa if not q.get("is_correct")][:3]

    header_detail = (
        f"round={macro + 1} total={total} correct={correct} wrong={wrong} "
        f"accuracy={accuracy * 100:.1f}% trend=[{trend}]"
    )
    logger = get_loop_logger()
    logger.info(
        _format_line(task, macro, "student_progress", "REPORT", detail=header_detail)
    )
    logger.info(_indent_line(f"by_persona: {' '.join(persona_parts) or 'n/a'}"))
    if weak_parts:
        logger.info(_indent_line(f"weak_topics: {', '.join(weak_parts)}"))
    for i, qa in enumerate(wrong_samples, 1):
        pid = qa.get("persona_id") or qa.get("persona_name") or "?"
        topic = qa.get("topic_tag") or qa.get("weak_topic_focus") or "-"
        q = _clip(qa.get("question", ""), 50)
        a = _clip(qa.get("answer", ""), 40)
        reason = _clip(qa.get("judge_reason", ""), 50)
        logger.info(
            _indent_line(f"wrong#{i} [{pid}|{topic}] Q:{q} | A:{a} | {reason}")
        )
    if not wrong_samples and total:
        logger.info(_indent_line("wrong#0 all correct this round"))
