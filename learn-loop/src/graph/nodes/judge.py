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

    apply_evidence_cap,

    adjust_difficulty_level,

    format_batch_evidence_context,

    format_evidence_context,

    maybe_advance_curriculum_level,

    weighted_accuracy,

)



logger = logging.getLogger(__name__)

RUBRIC = load_rubric()

CORRECT_THRESHOLD = RUBRIC.get("rubric", {}).get("correct_threshold", 0.85)

SCORING_RULES = RUBRIC.get("rubric", {}).get("scoring_rules", [])





@llm_retry()

def _judge_batch(

    batch: list[ExamQA],

    chunks: list[dict],

    *,

    evidence_only: bool,

    evidence_max_chars: int,

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



    if evidence_only:

        evidence_ctx = format_batch_evidence_context(

            chunks, batch, max_chars=evidence_max_chars

        )

        material_section = f"""每道题可引用的 evidence 原文（仅此范围，无学生笔记、无完整教材）：

{evidence_ctx}"""

    else:

        material_section = "（未启用 evidence-only 模式）"



    prompt = f"""你是独立 Judge B。根据 evidence 原文和评分标准给每道题打分。

你不能看到学生的笔记或完整教材。



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

证据未覆盖的细节不得因「合理推断」给高分。"""

    resp = llm.invoke(

        [

            SystemMessage(content="严格客观评分，禁止放水，禁止接受 evidence 外的细节。"),

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

                evidence_only=settings.judge_evidence_only,

                evidence_max_chars=settings.judge_evidence_max_chars,

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

                    tag = updated.get("topic_tag") or updated.get("weak_topic_focus") or "未知主题"

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
        new_curr, curr_advanced = maybe_advance_curriculum_level(
            old_curr,
            accuracy,
            chunks,
            settings.curriculum_pages_per_round,
            advance_threshold=settings.curriculum_advance_accuracy,
        )

        history = list(state.get("accuracy_history") or [])

        history.append(accuracy)



        report_lines = [

            f"## Judge Report — Macro Iter {state.get('macro_iter', 0)}",

            f"- Total questions: {len(scored)}",

            f"- Correct: {correct}",

            f"- Plain accuracy: {plain_accuracy:.2%}",

            f"- Weighted accuracy: {accuracy:.2%} (used for loop)",

            f"- Threshold: {CORRECT_THRESHOLD:.0%}",

            f"- Difficulty level: {old_diff} -> {new_diff}",

            f"- Curriculum level: {old_curr} -> {new_curr}"

            + (" (advanced)" if curr_advanced else " (held)"),

            f"- Weak topics: {', '.join(weak_topics) or 'none'}",

            "",

            "### Per-question",

        ]

        for q in scored:

            mark = "✓" if q.get("is_correct") else "✗"

            report_lines.append(

                f"- [{mark}] {q.get('qa_id')} ({q.get('persona_name')}): "

                f"score={q.get('judge_score', 0):.2f} — {q.get('judge_reason', '')[:80]}"

            )

        report = "\n".join(report_lines)



        task_id = state.get("task_id", "default")

        macro = state.get("macro_iter", 0)

        out = ensure_output_dir(task_id)

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

            "batch_accuracy": accuracy,

            "accuracy_history": history,

            "weak_topics": weak_topics,

            "difficulty_level": new_diff,

            "curriculum_level": new_curr,

            "curriculum_advanced": curr_advanced,

            "judge_report": report,

            "phase": "observer_analyze",

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
        logger.exception("observer_analyze failed")
        return {"status": "failed", "error_message": str(exc)}
