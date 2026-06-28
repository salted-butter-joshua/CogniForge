"""Execute CogniForge graph runs for the web API."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from src.api.event_bus import RunEventBus, attach_broadcast_handler, detach_broadcast_handler
from src.api.models import RunParams, RunSummary
from src.config import ensure_output_dir, get_settings
from src.graph.build_graph import build_graph
from src.graph.runner import is_cancel_requested, request_cancel, reset_cancel_state
from src.logging_config import (
    get_loop_logger,
    log_boot,
    log_finish,
    set_step_event_hook,
    setup_logging,
)
from src.main import build_initial_state
from src.models.router import llm_runtime_info, validate_api_keys
from src.tools.token_tracker import tracker as token_tracker

logger = get_loop_logger()


def _registry_dir() -> Path:
    base = Path(get_settings().output_dir) / ".registry"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _save_summary(summary: RunSummary) -> None:
    path = _registry_dir() / f"{summary.run_id}.json"
    path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")


def load_summary(run_id: str) -> RunSummary | None:
    path = _registry_dir() / f"{run_id}.json"
    if not path.exists():
        return None
    return RunSummary.model_validate_json(path.read_text(encoding="utf-8"))


def reconcile_stale_runs() -> int:
    """Mark runs left in 'running' (process died mid-run) as interrupted.

    Called at server startup: a fresh process means any previously-running run
    is dead, so it should become terminal — otherwise it stays invisible to the
    compare list (which filters out 'running') and its curve is never shown.
    """
    count = 0
    for summary in list_summaries():
        if summary.status == "running":
            summary = summary.model_copy(
                update={
                    "status": "interrupted",
                    "finished_at": summary.finished_at or time.time(),
                    "error_message": summary.error_message or "进程中断（未正常结束）",
                }
            )
            _save_summary(summary)
            count += 1
    return count


def list_summaries() -> list[RunSummary]:
    out: list[RunSummary] = []
    for p in sorted(_registry_dir().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            out.append(RunSummary.model_validate_json(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def _apply_env_overrides(params: RunParams) -> None:
    get_settings.cache_clear()
    mapping = {
        "TARGET_ACCURACY": str(params.target_accuracy),
        "MIN_MACRO_ITER": str(params.min_macro_iter),
        "MAX_MACRO_ITER": str(params.max_macro_iter),
        "CONSECUTIVE_PASS_ROUNDS": str(params.consecutive_pass_rounds),
        "FIRST_ROUND_TOTAL_QUESTIONS": str(params.first_round_total_questions),
        "FOCUSED_ROUND_QUESTIONS": str(params.focused_round_questions),
        "QUESTIONS_PER_PERSONA": str(params.questions_per_persona),
        "CLOSED_BOOK_EXAM": "1" if params.closed_book_exam else "0",
        "STUDENT_NOTES_MAX_CHARS": str(params.student_notes_max_chars),
        "STUDENT_NOTES_STUDY_MAX_CHARS": str(params.student_notes_study_max_chars),
        "CURRICULUM_PAGES_PER_ROUND": str(params.curriculum_pages_per_round),
        "JUDGE_EVIDENCE_ONLY": "1" if params.judge_evidence_only else "0",
        "EVIDENCE_CAP_SCORE": str(params.evidence_cap_score),
        "CRAWL_ENABLED": "1" if params.crawl_enabled else "0",
        "CRAWL_MAX_PAGES": str(params.crawl_max_pages),
        "CRAWL_INCLUDE_IMAGES": "1" if params.crawl_include_images else "0",
        "JUDGE_BATCH_SIZE": str(params.judge_batch_size),
        "STUDENT_ANSWER_BATCH_SIZE": str(params.student_answer_batch_size),
        "MAX_VALIDATE_ROUNDS": str(params.max_validate_rounds),
    }
    os.environ.update(mapping)
    get_settings.cache_clear()


def _build_init_state(params: RunParams, task_id: str) -> dict:
    settings = get_settings()
    state = build_initial_state(
        params.urls,
        params.goal,
        task_id,
        crawl_enabled=params.crawl_enabled,
    )
    state.update(
        {
            "max_macro_iter": params.max_macro_iter,
            "min_macro_iter": params.min_macro_iter,
            "consecutive_pass_rounds": params.consecutive_pass_rounds,
            "target_accuracy": params.target_accuracy,
            "questions_per_persona": params.questions_per_persona,
        }
    )
    return state


def _questions_in_state(state: dict) -> int:
    """Questions generated so far this macro round (answered, else just generated)."""
    return len(state.get("current_batch_qa") or []) or len(
        state.get("current_batch_questions") or []
    )


def execute_run(run_id: str, params: RunParams, bus: RunEventBus, label: str = "") -> RunSummary:
    setup_logging()
    reset_cancel_state()
    token_tracker.reset()
    _apply_env_overrides(params)
    settings = get_settings()

    task_id = params.task_id or f"web_{uuid.uuid4().hex[:8]}"
    thread_id = params.thread_id or task_id
    out_dir = ensure_output_dir(task_id)
    created_at = time.time()

    summary = RunSummary(
        run_id=run_id,
        task_id=task_id,
        status="running",
        urls=params.urls,
        goal=params.goal,
        params=params.model_dump(),
        created_at=created_at,
        label=label or task_id,
    )
    # Persist the run record BEFORE validating keys, so a config error surfaces
    # as a visible `failed` run instead of an invisible 404.
    _save_summary(summary)
    bus.publish({"type": "run_start", "task_id": task_id, "summary": summary.model_dump()})

    ok, err = validate_api_keys(settings)
    if not ok:
        summary = summary.model_copy(
            update={
                "status": "failed",
                "error_message": err or "API keys not configured",
                "finished_at": time.time(),
            }
        )
        _save_summary(summary)
        bus.publish({"type": "error", "message": summary.error_message})
        bus.close(summary.model_dump())
        raise RuntimeError(summary.error_message)

    runtime = llm_runtime_info(settings)
    log_boot(f"router={runtime['router']} preset={runtime['preset']}")
    for role, model in runtime["models"].items():
        log_boot(f"role={role} model={model}")
    log_boot(f"task={task_id} output={out_dir}")
    log_boot(f"urls={params.urls}")

    handler = attach_broadcast_handler(bus)
    set_step_event_hook(bus.publish)
    result: dict[str, Any] = {}
    last_history: list[float] = []
    last_macro = 0

    try:
        app = build_graph()
        init_state = _build_init_state(params, task_id)
        config = {"configurable": {"thread_id": thread_id}}

        for state in app.stream(init_state, config=config, stream_mode="values"):
            if is_cancel_requested():
                raise KeyboardInterrupt
            if not isinstance(state, dict):
                continue
            result = state

            macro = int(state.get("macro_iter", 0) or 0)
            history = list(state.get("accuracy_history") or [])
            accuracy = float(state.get("batch_accuracy", 0.0) or 0.0)
            phase = str(state.get("phase", ""))

            if history != last_history and history:
                point = {
                    "type": "metric",
                    "macro_iter": macro,
                    "accuracy": history[-1],
                    "accuracy_pct": round(history[-1] * 100, 2),
                    "history": history,
                    "weak_topics": state.get("weak_topics") or [],
                }
                bus.publish(point)
                last_history = list(history)

            if macro != last_macro:
                bus.publish(
                    {
                        "type": "state",
                        "macro_iter": macro,
                        "phase": phase,
                        "batch_accuracy": accuracy,
                    }
                )
                last_macro = macro

            q_count = _questions_in_state(state)

            live = summary.model_copy(
                update={
                    "macro_iter": macro,
                    "batch_accuracy": accuracy,
                    "current_questions": q_count,
                    "accuracy_history": history,
                    "round_records": list(state.get("round_records") or []),
                    "weak_topics": list(state.get("weak_topics") or []),
                    "phase": phase,
                    **token_tracker.snapshot(),
                }
            )
            _save_summary(live)

    except KeyboardInterrupt:
        partial = result
        summary = summary.model_copy(
            update={
                "status": "cancelled",
                "macro_iter": int(partial.get("macro_iter", 0) or 0),
                "batch_accuracy": float(partial.get("batch_accuracy", 0.0) or 0.0),
                "current_questions": _questions_in_state(partial),
                "accuracy_history": list(partial.get("accuracy_history") or []),
                "round_records": list(partial.get("round_records") or []),
                "weak_topics": list(partial.get("weak_topics") or []),
                "phase": str(partial.get("phase", "")),
                "error_message": "用户通过控制台停止",
                "finished_at": time.time(),
                **token_tracker.snapshot(),
            }
        )
        _write_final_summary(task_id, summary)
        log_finish(
            f"task={task_id} status=cancelled macro={summary.macro_iter}",
            level=logging.WARNING,
        )
        bus.close(summary.model_dump())
        return summary

    except Exception as exc:
        logger.exception("run failed run_id=%s", run_id)
        summary = summary.model_copy(
            update={
                "status": "failed",
                "error_message": str(exc),
                "finished_at": time.time(),
            }
        )
        _save_summary(summary)
        bus.publish({"type": "error", "message": str(exc)})
        bus.close(summary.model_dump())
        raise

    finally:
        set_step_event_hook(None)
        detach_broadcast_handler(handler)

    status = str(result.get("status", "unknown"))
    summary = summary.model_copy(
        update={
            "status": status,
            "macro_iter": int(result.get("macro_iter", 0) or 0),
            "batch_accuracy": float(result.get("batch_accuracy", 0.0) or 0.0),
            "current_questions": _questions_in_state(result),
            "accuracy_history": list(result.get("accuracy_history") or []),
            "round_records": list(result.get("round_records") or []),
            "weak_topics": list(result.get("weak_topics") or []),
            "phase": str(result.get("phase", "")),
            "error_message": str(result.get("error_message", "")),
            "finished_at": time.time(),
            **token_tracker.snapshot(),
        }
    )
    _save_summary(summary)
    _write_final_summary(task_id, summary)
    log_finish(
        f"task={task_id} status={status} macro={summary.macro_iter} "
        f"accuracy={summary.batch_accuracy * 100:.2f}%"
    )
    bus.close(summary.model_dump())
    return summary


def _write_final_summary(task_id: str, summary: RunSummary) -> None:
    out = ensure_output_dir(task_id)
    payload = {
        "task_id": task_id,
        "run_id": summary.run_id,
        "status": summary.status,
        "macro_iter": summary.macro_iter,
        "batch_accuracy": summary.batch_accuracy,
        "accuracy_history": summary.accuracy_history,
        "weak_topics": summary.weak_topics,
        "phase": summary.phase,
        "error_message": summary.error_message,
        "params": summary.params,
        "output_dir": str(out),
    }
    (out / "final_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def stop_run() -> None:
    request_cancel()
