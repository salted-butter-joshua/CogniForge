"""Aggregate Q&A after all exam batches in one macro iteration."""

from __future__ import annotations

import json
import logging

from src.config import ensure_output_dir
from src.graph.state import LearnLoopState

logger = logging.getLogger(__name__)


def aggregate_qa(state: LearnLoopState) -> dict:
    if state.get("status") == "failed":
        return {}
    qa_list = state.get("current_batch_qa") or []
    task_id = state.get("task_id", "default")
    macro = state.get("macro_iter", 0)

    if not qa_list:
        return {
            "status": "failed",
            "error_message": f"No Q&A to aggregate (macro={macro})",
            "phase": "judge_score",
        }

    logger.info("aggregate_qa macro=%s total_qa=%d", macro, len(qa_list))

    by_persona: dict[str, list] = {}
    by_topic: dict[str, list] = {}
    for qa in qa_list:
        pid = qa.get("persona_id", "unknown")
        topic = qa.get("topic_tag") or "未分类"
        by_persona.setdefault(pid, []).append(qa)
        by_topic.setdefault(topic, []).append(qa)

    summary = {
        "macro_iter": macro,
        "total_questions": len(qa_list),
        "by_persona_counts": {k: len(v) for k, v in by_persona.items()},
        "by_topic_counts": {k: len(v) for k, v in by_topic.items()},
    }

    out = ensure_output_dir(task_id)
    (out / f"qa_aggregate_iter_{macro}.json").write_text(
        json.dumps({"summary": summary, "qa": qa_list}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {"phase": "judge_score"}
