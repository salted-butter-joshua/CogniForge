"""Judge batch scoring and Observer analysis nodes."""

from __future__ import annotations


import json

import logging

from collections import Counter


from langchain_core.messages import HumanMessage, SystemMessage


from langgraph.types import Overwrite


from src.config import ensure_output_dir, get_settings, load_rubric

from src.graph.state import ExamQA, LearnLoopState, ObservationRecord

from src.logging_config import log_student_progress

from src.models.llm_factory import judge_llm, observer_llm

from src.tools.json_utils import extract_json, llm_retry
from src.tools.learning_policy import (
    all_chapters_mastered,
    apply_evidence_cap,
    adjust_difficulty_level,
    build_judge_scoring_context,
    chapter_exam_accuracy,
    chapter_label,
    current_chapter,
    effective_judge_scoring_mode,
    exam_notes_char_budget,
    format_evidence_context,
    is_chapter_mastery_mode,
    judge_system_message_for_mode,
    mastery_progress_summary,
    maybe_advance_curriculum_level,
    select_exam_notes,
    should_apply_evidence_cap,
    update_chapter_mastery_record,
    update_reinforce_pool,
    weighted_accuracy,
)
from src.tools.run_trace import (
    append_round_trace,
    chapter_question_counts,
    judge_batch_diagnostics,
    memory_snapshot,
)
from src.tools.token_tracker import tracker as token_tracker


logger = logging.getLogger(__name__)

RUBRIC = load_rubric()

CORRECT_THRESHOLD = RUBRIC.get("rubric", {}).get("correct_threshold", 0.85)

SCORING_RULES = RUBRIC.get("rubric", {}).get("scoring_rules", [])


@llm_retry()
def _judge_batch(
    batch: list[ExamQA],
    chunks: list[dict],
    *,
    scoring_mode: str,
    evidence_max_chars: int,
    exam_memory_text: str = "",
    study_material: str = "",
) -> list[dict]:

    llm = judge_llm()

    items = [
        {
            "qa_id": q.get("qa_id"),
            "question": q.get("question"),
            "answer": q.get("answer"),
            "evidence_refs": q.get("evidence_refs", []),
            "persona": q.get("persona_name"),
            "persona_id": q.get("persona_id"),
        }
        for q in batch
    ]

    rubric_text = json.dumps(RUBRIC, ensure_ascii=False, indent=2)

    rules_text = "\n".join(f"- {r}" for r in SCORING_RULES)

    material_section = build_judge_scoring_context(
        chunks=chunks,
        qa_batch=batch,
        mode=scoring_mode,
        exam_memory_text=exam_memory_text,
        study_material=study_material,
        evidence_max_chars=evidence_max_chars,
    )

    mode_label = {
        "evidence_only": "evidence-only",
        "exam_memory": "exam_memory（闭卷记忆 + evidence 锚点）",
        "contradiction_only": "contradiction-only",
    }.get(scoring_mode, scoring_mode)

    prompt = f"""你是独立 Judge B。根据下列参考资料与评分标准给每道题打分。

当前判分模式：{mode_label}



评分标准：

{rubric_text}



硬性规则：

{rules_text}



{material_section}



待评题目：

{json.dumps(items, ensure_ascii=False, indent=2)}



输出 JSON 数组（与题目顺序一致）：

[

  {{

    "qa_id": "...",

    "score": 0.0到1.0,

    "is_correct": true/false,

    "reason": "评分理由",

    "topic_tag": "主题",

    "missing_points": ["遗漏点"]

  }}

]

score >= {CORRECT_THRESHOLD} 则 is_correct=true。

评分原则：
- 以「题目是否答对」为主，而非「答案是否仅复述 evidence 字面内容」
- 答案与参考资料中心意思一致即可判对，不要求用词与原文一致
- 合理扩展、同义改写、笔记/先验中的额外正确细节不应单独扣分
- 仅当核心概念错误、机制条件写反、或与参考资料明显矛盾时才判错
- reason 必须写完整：若扣分，指出哪一句与哪份材料矛盾或何处机制错误"""

    resp = llm.invoke(
        [
            SystemMessage(content=judge_system_message_for_mode(scoring_mode)),
            HumanMessage(content=prompt),
        ]
    )

    data = extract_json(resp.content)

    if isinstance(data, dict):

        data = data.get("results", data.get("scores", []))

    return data


def judge_score(state: LearnLoopState) -> dict:

    if state.get("status") == "failed":

        return {}

    settings = get_settings()

    batch_size = settings.judge_batch_size

    all_qa = list(state.get("current_batch_qa") or [])

    chunks = list(state.get("raw_chunks") or [])

    scoring_mode = effective_judge_scoring_mode(settings)

    chapter_title = ""
    current_chapter_id = ""
    if is_chapter_mastery_mode():
        registry = state.get("chapter_registry") or []
        ch = current_chapter(registry, int(state.get("current_chapter_index", 0) or 0))
        chapter_title = (ch or {}).get("chapter_title", "")
        current_chapter_id = (ch or {}).get("chapter_id", "")

    study_notes = state.get("study_notes") or ""
    short_term = state.get("short_term_notes") or study_notes
    long_term = state.get("long_term_notes") or ""
    archive = list(state.get("chapter_notes_archive") or [])
    exam_memory = ""
    if scoring_mode != "evidence_only":
        exam_memory = select_exam_notes(
            notes=study_notes,
            max_chars=exam_notes_char_budget(),
            long_term_notes=long_term,
            short_term_notes=short_term,
            chapter_title=chapter_title,
            chapter_notes_archive=archive,
            current_chapter_id=current_chapter_id,
        )
    study_material = state.get("study_material") or ""

    if not all_qa:

        logger.warning(
            "judge_score: no Q&A to score macro=%s — accuracy defaults to 0",
            state.get("macro_iter", 0),
        )

        return {
            "batch_accuracy": 0.0,
            "phase": "observer_analyze",
            "judge_skipped": True,
            "judge_skip_reason": "no_qa",
        }

    scored: list[ExamQA] = []

    weak_counter: Counter = Counter()

    try:

        for i in range(0, len(all_qa), batch_size):

            chunk = all_qa[i : i + batch_size]

            results = _judge_batch(
                chunk,
                chunks,
                scoring_mode=scoring_mode,
                evidence_max_chars=settings.judge_evidence_max_chars,
                exam_memory_text=exam_memory,
                study_material=study_material,
            )

            score_map = {r.get("qa_id"): r for r in results if isinstance(r, dict)}

            for j, qa in enumerate(chunk):

                qa_id = qa.get("qa_id")

                r = score_map.get(qa_id)

                if r is None and j < len(results) and isinstance(results[j], dict):

                    r = results[j]

                r = r or {}

                score = float(r.get("score", 0.0))

                evidence_text = format_evidence_context(
                    chunks, qa.get("evidence_refs") or []
                )

                capped, cap_reason = apply_evidence_cap(
                    qa.get("answer", ""),
                    evidence_text,
                    score,
                    cap=settings.evidence_cap_score,
                    semantic_lenient=not should_apply_evidence_cap(
                        scoring_mode,
                        semantic_lenient=settings.judge_semantic_lenient,
                    ),
                )

                if cap_reason:

                    score = capped

                is_correct = bool(r.get("is_correct", score >= CORRECT_THRESHOLD))

                if score < CORRECT_THRESHOLD:

                    is_correct = False

                reason = r.get("reason", "")

                if cap_reason:

                    reason = f"{reason} | {cap_reason}".strip(" |")

                updated = dict(qa)

                updated["judge_score"] = score

                updated["is_correct"] = is_correct

                updated["judge_reason"] = reason

                updated["topic_tag"] = r.get("topic_tag", qa.get("topic_tag", ""))

                scored.append(updated)

                if not is_correct:

                    tag = (
                        updated.get("topic_tag")
                        or updated.get("weak_topic_focus")
                        or "未知主题"
                    )

                    weak_counter[tag] += 1

        correct = sum(1 for q in scored if q.get("is_correct"))

        plain_accuracy = correct / len(scored) if scored else 0.0

        accuracy = weighted_accuracy(scored)

        weak_topics = [t for t, _ in weak_counter.most_common(10)]

        old_diff = int(state.get("difficulty_level", 0) or 0)
        old_curr = int(state.get("curriculum_level", 0) or 0)
        new_diff = adjust_difficulty_level(
            old_diff,
            accuracy,
            advance_threshold=settings.difficulty_advance_accuracy,
            retreat_threshold=settings.difficulty_retreat_accuracy,
        )

        chapter_mastery = dict(state.get("chapter_mastery") or {})
        registry = list(state.get("chapter_registry") or [])
        ch_index = int(state.get("current_chapter_index", 0) or 0)
        ch_acc = accuracy
        ch_rel = len(scored)
        ch_total = len(scored)
        chapter_evidence_fallback = False
        cid = ""
        should_consolidate = False
        new_curr = old_curr
        curr_advanced = False
        chapter_mastered_now = False

        if is_chapter_mastery_mode() and registry:
            ch = current_chapter(registry, ch_index)
            if ch:
                cid = ch["chapter_id"]
                ch_acc, ch_rel, ch_total = chapter_exam_accuracy(scored, cid, chunks)
                chapter_evidence_fallback = ch_rel == 0 and ch_total > 0
                ch_weak = [
                    t
                    for t, _ in weak_counter.most_common(6)
                    if t and t != "未知主题"
                ]
                macro_i = int(state.get("macro_iter", 0) or 0)
                chapter_mastery = update_chapter_mastery_record(
                    chapter_mastery,
                    cid,
                    accuracy=ch_acc,
                    macro_iter=macro_i,
                    weak_subtopics=ch_weak,
                    threshold=settings.chapter_mastery_accuracy,
                )
                rec = chapter_mastery.get(cid) or {}
                should_consolidate = (
                    ch_acc >= settings.chapter_mastery_accuracy
                    and rec.get("mastered_at_iter") == macro_i
                )
                chapter_mastered_now = bool(rec.get("mastered"))
                if not chapter_mastered_now:
                    new_diff = old_diff
        else:
            new_curr, curr_advanced = maybe_advance_curriculum_level(
                old_curr,
                accuracy,
                chunks,
                settings.curriculum_pages_per_round,
                advance_threshold=settings.curriculum_advance_accuracy,
            )

        history = list(state.get("accuracy_history") or [])

        loop_accuracy = ch_acc if is_chapter_mastery_mode() and registry else accuracy
        history.append(loop_accuracy)

        reinforce_questions, topic_streaks, graduated = update_reinforce_pool(
            list(state.get("reinforce_questions") or []),
            scored,
            dict(state.get("topic_reinforce_streaks") or {}),
            set(state.get("graduated_topic_tags") or []),
        )
        reinforce_wrong = sum(1 for q in scored if q.get("is_reinforce") and not q.get("is_correct"))
        reinforce_ok = sum(1 for q in scored if q.get("is_reinforce") and q.get("is_correct"))

        judge_diag = judge_batch_diagnostics(scored)
        mem = memory_snapshot(state)
        token_round = token_tracker.snapshot_round(int(state.get("macro_iter", 0) or 0))
        task_id = state.get("task_id", "default")
        ch_counts = (
            chapter_question_counts(scored, cid, chunks)
            if cid
            else {"chapter_relevant_count": ch_rel, "chapter_total_scored": ch_total}
        )

        # Per-round record for the curve tooltip / clickable detail panel.
        topic_counts = Counter(q.get("topic_tag") or "未分类" for q in scored)
        persona_counts = Counter(
            q.get("persona_name") or q.get("persona_id") or "?" for q in scored
        )
        wrong_samples = [
            {
                "question": q.get("question", ""),
                "answer": q.get("answer", ""),
                "judge_reason": q.get("judge_reason", ""),
                "judge_score": q.get("judge_score", 0.0),
                "topic_tag": q.get("topic_tag", ""),
            }
            for q in scored
            if not q.get("is_correct")
        ][:6]
        round_record = {
            "macro_iter": int(state.get("macro_iter", 0) or 0),
            "accuracy": loop_accuracy,
            "plain_accuracy": plain_accuracy,
            "batch_accuracy": accuracy,
            "chapter_accuracy": ch_acc,
            "difficulty_level": old_diff,
            "curriculum_level": old_curr,
            "current_chapter_index": ch_index,
            "chapter_title": (
                (current_chapter(registry, ch_index) or {}).get("chapter_title", "")
                if registry
                else ""
            ),
            "question_count": len(scored),
            "correct": correct,
            "weak_topics": weak_topics[:6],
            "topic_counts": dict(topic_counts.most_common(8)),
            "persona_counts": dict(persona_counts),
            "chapter_progress": mastery_progress_summary(registry, chapter_mastery),
            "reinforce_correct": reinforce_ok,
            "reinforce_wrong": reinforce_wrong,
            "reinforce_pool_size": len(reinforce_questions),
            "graduated_topic_count": len(graduated),
            "chapter_relevant_count": ch_counts.get("chapter_relevant_count", ch_rel),
            "chapter_total_scored": ch_counts.get("chapter_total_scored", ch_total),
            "chapter_evidence_fallback": chapter_evidence_fallback,
            "judge_anomaly": judge_diag.get("judge_anomaly", False),
            "judge_anomaly_reason": judge_diag.get("judge_anomaly_reason", ""),
            "empty_judge_reason_count": judge_diag.get("empty_judge_reason_count", 0),
            "avg_judge_score": judge_diag.get("avg_judge_score", 0.0),
            "long_term_notes_chars": mem.get("long_term_notes_chars", 0),
            "short_term_notes_chars": mem.get("short_term_notes_chars", 0),
            "token_round_total": token_round.get("token_round_total", 0),
            "token_round_input": token_round.get("token_round_input", 0),
            "token_round_output": token_round.get("token_round_output", 0),
            "token_cumulative_total": token_round.get("token_cumulative_total", 0),
            "token_cumulative_input": token_round.get("token_cumulative_input", 0),
            "token_cumulative_output": token_round.get("token_cumulative_output", 0),
            "token_calls_round": token_round.get("token_calls_round", 0),
            "tokens_by_step_round": token_round.get("tokens_by_step_round", {}),
            "settings_snapshot": {
                "target_accuracy": settings.target_accuracy,
                "chapter_mastery_accuracy": settings.chapter_mastery_accuracy,
                "judge_semantic_lenient": settings.judge_semantic_lenient,
                "judge_scoring_mode": effective_judge_scoring_mode(settings),
                "judge_temperature": settings.judge_temperature,
                "student_exam_temperature": settings.student_exam_temperature,
                "exam_long_term_ratio": settings.exam_long_term_ratio,
                "exam_working_layer_ratio": settings.exam_working_layer_ratio,
                "exam_memory_mode": getattr(settings, "exam_memory_mode", "full_notes"),
                "reinforce_pool_ratio": settings.reinforce_pool_ratio,
                "closed_book_exam": settings.closed_book_exam,
                "study_notes_target_ratio": settings.study_notes_target_ratio,
            },
            "wrong_samples": wrong_samples,
        }

        out = ensure_output_dir(task_id)
        append_round_trace(out, round_record)

        report_lines = [
            f"## Judge Report — Macro Iter {state.get('macro_iter', 0)}",
            f"- Total questions: {len(scored)}",
            f"- Correct: {correct}",
            f"- Plain accuracy: {plain_accuracy:.2%}",
            f"- Weighted accuracy: {accuracy:.2%} (used for loop)",
        ]
        if is_chapter_mastery_mode() and registry:
            report_lines.append(
                f"- Chapter accuracy: {ch_acc:.2%} "
                f"({chapter_label(registry, ch_index)}, "
                f"threshold {settings.chapter_mastery_accuracy:.0%})"
            )
            report_lines.extend(
                [
                    f"- Should consolidate: {should_consolidate}",
                    f"- Chapters mastered: "
                    f"{sum(1 for m in chapter_mastery.values() if m.get('mastered'))}"
                    f"/{len(registry)}",
                ]
            )
        report_lines.extend(
            [
                f"- Threshold: {CORRECT_THRESHOLD:.0%}",
                f"- Difficulty level: {old_diff} -> {new_diff}",
                f"- Curriculum level: {old_curr} -> {new_curr}"
                + (" (advanced)" if curr_advanced else " (held)"),
                f"- Weak topics: {', '.join(weak_topics) or 'none'}",
                "",
                "### Per-question",
            ]
        )

        for q in scored:

            mark = "✓" if q.get("is_correct") else "✗"

            report_lines.append(
                f"- [{mark}] {q.get('qa_id')} ({q.get('persona_name')}): "
                f"score={q.get('judge_score', 0):.2f} — {q.get('judge_reason', '')}"
            )

        report = "\n".join(report_lines)

        macro = state.get("macro_iter", 0)

        (out / f"judge_report_iter_{macro}.md").write_text(report, encoding="utf-8")

        (out / f"qa_scored_iter_{macro}.json").write_text(
            json.dumps(scored, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        log_student_progress(
            state,
            scored,
            accuracy,
            weak_topics,
            weak_counter=dict(weak_counter),
        )

        return {
            "current_batch_qa": Overwrite(scored),
            "all_qa_archive": scored,
            "batch_accuracy": loop_accuracy,
            "accuracy_history": history,
            "weak_topics": weak_topics,
            "difficulty_level": new_diff,
            "curriculum_level": new_curr,
            "curriculum_advanced": curr_advanced,
            "chapter_mastery": chapter_mastery,
            "chapter_advanced": should_consolidate,
            "reinforce_questions": reinforce_questions,
            "topic_reinforce_streaks": topic_streaks,
            "graduated_topic_tags": sorted(graduated),
            "judge_report": report,
            "round_records": [round_record],
            "phase": "consolidate_chapter_notes"
            if should_consolidate
            else "observer_analyze",
        }

    except Exception as exc:

        logger.exception("judge_score failed")

        return {"status": "failed", "error_message": str(exc)}


@llm_retry()
def _observer_analyze_llm(
    qa_list: list[ExamQA],
    study_notes: str,
    accuracy: float,
    macro_iter: int,
    weak_topics: list[str],
    accuracy_history: list[float],
) -> dict:
    llm = observer_llm()
    wrong_count = sum(1 for q in qa_list if not q.get("is_correct"))
    history_text = ", ".join(f"{h:.0%}" for h in (accuracy_history or [])[-5:]) or "无"
    weak_text = ", ".join(weak_topics) if weak_topics else "无"

    prompt = f"""你是独立学习观察者（角色 C），不直接指导学生。
你的任务是阅读学生 A 的本轮学习笔记，总结其学习规律、笔记习惯与知识建构方式，形成观察报告。
报告仅供系统复盘与研究者参考，不会交给学生阅读或影响其下一轮学习。

观察重点：
- 笔记的组织方式与信息取舍（详略、抄录 vs 概括、是否口语化）
- 重复出现的学习模式（如只记结论不记原因、术语堆砌、回避难点）
- 从笔记推断的知识框架是否完整、层级是否清晰
- 与薄弱主题对照，笔记中是否反复遗漏或表述模糊之处
- 若有历史轮次信息，可指出笔记风格的变化趋势

原则：
- 以学习笔记为主要分析对象；答题统计仅作辅助对照
- 区分「观察到的事实」与「推测」，证据不足时明确说明
- 描述现象与规律，不对学生发出指令性建议或学习规划

当前宏观迭代：{macro_iter}
本轮加权正确率：{accuracy:.2%}
历史正确率（近几轮）：{history_text}
薄弱主题（Judge 归纳，辅助对照）：{weak_text}
答题统计（辅助）：共 {len(qa_list)} 题，错题 {wrong_count} 道

学生本轮学习笔记（主要分析对象）：
{study_notes[:6000]}

输出 JSON：
{{
  "learning_patterns": "从笔记中总结的学习规律与行为模式（Markdown）",
  "knowledge_framework": "从笔记结构推断的知识框架掌握情况（Markdown）",
  "note_style_observations": "笔记风格、习惯与信息处理方式（Markdown）",
  "recurring_blind_spots": "反复未覆盖、表述模糊或与薄弱主题相关的盲区（Markdown）",
  "observer_summary": "本轮观察摘要（100字内，供研究者快速浏览）"
}}"""
    resp = llm.invoke(
        [
            SystemMessage(
                content="你是客观的学习观察者。聚焦笔记中的学习规律与发现，不给学生提建议。"
            ),
            HumanMessage(content=prompt),
        ]
    )
    return extract_json(resp.content)


def _build_observer_report(record: ObservationRecord, macro: int) -> str:
    return "\n\n".join(
        [
            f"# 学习观察报告 — 第 {macro} 轮",
            "> 本报告仅供系统复盘，不传入学生学习流程。",
            "## 观察摘要\n" + record.get("observer_summary", ""),
            "## 学习规律\n" + record.get("learning_patterns", ""),
            "## 知识框架观察\n" + record.get("knowledge_framework", ""),
            "## 笔记风格与习惯\n" + record.get("note_style_observations", ""),
            "## 反复盲区\n" + record.get("recurring_blind_spots", ""),
        ]
    )


def observer_analyze(state: LearnLoopState) -> dict:
    if state.get("status") == "failed":
        return {}
    qa_list = state.get("current_batch_qa") or []
    study_notes = state.get("study_notes") or ""
    accuracy = state.get("batch_accuracy", 0.0)
    macro = state.get("macro_iter", 0)
    weak_topics = list(state.get("weak_topics") or [])
    history = list(state.get("accuracy_history") or [])

    try:
        data = _observer_analyze_llm(
            qa_list,
            study_notes,
            accuracy,
            macro,
            weak_topics,
            history,
        )
        record = ObservationRecord(
            macro_iter=macro,
            learning_patterns=data.get("learning_patterns", ""),
            knowledge_framework=data.get("knowledge_framework", ""),
            note_style_observations=data.get("note_style_observations", ""),
            recurring_blind_spots=data.get("recurring_blind_spots", ""),
            observer_summary=data.get("observer_summary", ""),
        )

        report = _build_observer_report(record, macro)

        task_id = state.get("task_id", "default")
        out = ensure_output_dir(task_id)
        (out / f"observer_report_iter_{macro}.md").write_text(report, encoding="utf-8")

        return {
            "observations": [record],
            "latest_observation": record,
            "phase": "macro_router",
        }
    except Exception as exc:
        # The observer report is archival only (never fed back to the student),
        # so a failure here (e.g. malformed LLM JSON) must NOT abort the macro
        # loop. Log it and continue to the router.
        logger.warning("observer_analyze skipped (non-fatal): %s", exc)
        return {"phase": "macro_router"}
