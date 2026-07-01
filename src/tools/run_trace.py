"""Persist run configuration and per-round diagnostics for post-hoc analysis."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import get_settings


def effective_settings_snapshot() -> dict[str, Any]:
    """Flatten Settings into JSON-safe dict (post env override)."""
    s = get_settings()
    data: dict[str, Any] = {}
    for name in s.model_fields:
        val = getattr(s, name)
        if isinstance(val, (str, int, float, bool)) or val is None:
            data[name] = val
        else:
            data[name] = str(val)
    return data


def write_run_config(
    out_dir: Path,
    *,
    run_id: str,
    params: dict[str, Any],
    urls: list[str] | None = None,
    goal: str = "",
) -> Path:
    """Write once at run start — full parameter trace for debugging."""
    payload = {
        "run_id": run_id,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "goal": goal,
        "urls": urls or [],
        "run_params": params,
        "effective_settings": effective_settings_snapshot(),
    }
    path = out_dir / "run_config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def judge_batch_diagnostics(scored: list[dict]) -> dict[str, Any]:
    """Detect judge parse / scoring anomalies."""
    if not scored:
        return {
            "scored_count": 0,
            "judge_anomaly": True,
            "judge_anomaly_reason": "no_scored_qa",
        }
    scores = [float(q.get("judge_score", 0.0) or 0.0) for q in scored]
    reasons = [str(q.get("judge_reason") or "").strip() for q in scored]
    empty_reason = sum(1 for r in reasons if not r)
    correct = sum(1 for q in scored if q.get("is_correct"))
    all_zero = all(s == 0.0 for s in scores)
    all_empty_reason = empty_reason == len(scored)
    anomaly = all_zero and all_empty_reason and len(scored) > 0
    return {
        "scored_count": len(scored),
        "correct_count": correct,
        "plain_accuracy": correct / len(scored),
        "avg_judge_score": sum(scores) / len(scores),
        "empty_judge_reason_count": empty_reason,
        "judge_anomaly": anomaly,
        "judge_anomaly_reason": (
            "all_scores_zero_with_empty_reasons"
            if anomaly
            else ("all_wrong" if correct == 0 else "")
        ),
    }


def chapter_question_counts(
    scored: list[dict],
    chapter_id: str,
    chunks: list[dict],
) -> dict[str, int]:
    chunk_ids = {c["id"] for c in chunks if c.get("chapter_id") == chapter_id}
    relevant = [
        q
        for q in scored
        if chunk_ids.intersection(set(q.get("evidence_refs") or []))
    ]
    return {
        "chapter_relevant_count": len(relevant),
        "chapter_total_scored": len(scored),
    }


def memory_snapshot(state: dict[str, Any]) -> dict[str, int]:
    lt = state.get("long_term_notes") or ""
    st = state.get("short_term_notes") or state.get("study_notes") or ""
    return {
        "long_term_notes_chars": len(lt),
        "short_term_notes_chars": len(st),
    }


def append_round_trace(
    out_dir: Path,
    record: dict[str, Any],
) -> None:
    """Append one JSON line per macro iteration."""
    line = dict(record)
    line["ts"] = datetime.now(timezone.utc).isoformat()
    path = out_dir / "run_trace.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
