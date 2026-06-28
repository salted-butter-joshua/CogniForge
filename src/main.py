"""CLI entry point for Learn Loop."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.config import ensure_output_dir, get_settings
from src.graph.build_graph import build_graph
from src.graph.runner import run_graph_streaming
from src.models.router import llm_runtime_info, validate_api_keys

from src.logging_config import get_loop_logger, log_boot, log_finish, setup_logging


def build_initial_state(
    urls: list[str],
    goal: str,
    task_id: str,
    *,
    crawl_enabled: bool | None = None,
) -> dict:
    settings = get_settings()
    crawl = settings.crawl_enabled if crawl_enabled is None else crawl_enabled
    return {
        "task_id": task_id,
        "urls": urls,
        "goal": goal,
        "crawl_enabled": crawl,
        "raw_chunks": [],
        "study_material": "",
        "knowledge_cards": [],
        "study_notes": "",
        "macro_iter": 0,
        "curriculum_level": 0,
        "difficulty_level": 0,
        "curriculum_advanced": False,
        "max_macro_iter": settings.max_macro_iter,
        "min_macro_iter": settings.min_macro_iter,
        "consecutive_pass_rounds": settings.consecutive_pass_rounds,
        "target_accuracy": settings.target_accuracy,
        "exam_batch_index": 0,
        "exam_batches_target": 1,
        "questions_per_persona": settings.questions_per_persona,
        "current_batch_questions": [],
        "final_questions": [],
        "current_batch_qa": [],
        "all_qa_archive": [],
        "batch_accuracy": 0.0,
        "accuracy_history": [],
        "round_records": [],
        "weak_topics": [],
        "judge_report": "",
        "observations": [],
        "phase": "fetch",
        "status": "running",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CogniForge — Loop Engineering reference for iterative knowledge mastery"
    )
    parser.add_argument(
        "--urls",
        nargs="+",
        required=True,
        help="Web page URLs to learn from",
    )
    parser.add_argument(
        "--goal",
        default="全面掌握所提供网页的核心知识",
        help="Learning goal description",
    )
    parser.add_argument(
        "--task-id",
        default=None,
        help="Unique task ID for checkpointing and outputs",
    )
    parser.add_argument(
        "--thread-id",
        default=None,
        help="LangGraph thread ID (defaults to task-id)",
    )
    parser.add_argument(
        "--no-crawl",
        action="store_true",
        help="Only fetch the exact URLs given (no sidebar/child page discovery)",
    )
    args = parser.parse_args(argv)

    setup_logging()
    logger = get_loop_logger()

    settings = get_settings()
    ok, err = validate_api_keys(settings)
    if not ok:
        logger.error(err)
        return 1

    runtime = llm_runtime_info(settings)
    log_boot(f"router={runtime['router']} preset={runtime['preset']}")
    for role, model in runtime["models"].items():
        log_boot(f"role={role} model={model}")

    task_id = args.task_id or f"task_{uuid.uuid4().hex[:8]}"
    thread_id = args.thread_id or task_id
    out_dir = ensure_output_dir(task_id)

    log_boot(f"task={task_id} output={out_dir}")
    log_boot(f"urls={args.urls}")
    log_boot(
        f"crawl={'on' if not args.no_crawl else 'off'} "
        f"max_pages={settings.crawl_max_pages} images={settings.crawl_include_images}"
    )

    log_boot(
        f"max_iter={settings.max_macro_iter} min_iter={settings.min_macro_iter} "
        f"target={settings.target_accuracy * 100:.0f}% "
        f"pass_streak={settings.consecutive_pass_rounds} "
        f"first_round={settings.first_round_total_questions} focused={settings.focused_round_questions}"
    )
    log_boot(
        f"learning closed_book={settings.closed_book_exam} "
        f"curriculum_pages={settings.curriculum_pages_per_round} "
        f"judge_evidence_only={settings.judge_evidence_only}"
    )

    app = build_graph()
    init_state = build_initial_state(
        args.urls, args.goal, task_id, crawl_enabled=not args.no_crawl
    )
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = run_graph_streaming(app, init_state, config)
    except KeyboardInterrupt:
        partial = {}
        try:
            snap = app.get_state(config)
            partial = getattr(snap, "values", None) or {}
        except Exception:
            pass
        summary = {
            "task_id": task_id,
            "status": "cancelled",
            "macro_iter": partial.get("macro_iter", 0),
            "batch_accuracy": partial.get("batch_accuracy", 0.0),
            "weak_topics": partial.get("weak_topics", []),
            "phase": partial.get("phase", ""),
            "error_message": "用户中断 (Ctrl+C)",
            "output_dir": str(out_dir),
        }
        (out_dir / "final_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log_finish(
            f"task={task_id} status=cancelled macro={summary['macro_iter']} "
            f"phase={summary['phase'] or '-'} output={out_dir}",
            level=logging.WARNING,
        )
        return 130
    except Exception:
        logger.exception("event=FAIL | task=%s | msg=Learn loop failed", task_id)
        return 1

    status = result.get("status", "unknown")
    accuracy = result.get("batch_accuracy", 0.0)
    macro = result.get("macro_iter", 0)
    error_message = result.get("error_message", "")
    phase = result.get("phase", "")

    summary = {
        "task_id": task_id,
        "status": status,
        "macro_iter": macro,
        "batch_accuracy": accuracy,
        "weak_topics": result.get("weak_topics", []),
        "phase": phase,
        "error_message": error_message,
        "output_dir": str(out_dir),
    }
    (out_dir / "final_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log_finish(
        f"task={task_id} status={status} macro={macro} accuracy={accuracy * 100:.2f}% output={out_dir}"
    )
    if error_message:
        log_finish(f"task={task_id} error={error_message} phase={phase}", level=logging.ERROR)

    return 0 if status == "success" else 0 if status in ("max_iter_reached", "stagnated") else 1


if __name__ == "__main__":
    sys.exit(main())
