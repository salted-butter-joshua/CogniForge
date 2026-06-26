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

    build_observer_qa_payload,

    format_batch_evidence_context,

    format_evidence_context,

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



        history = list(state.get("accuracy_history") or [])

        history.append(accuracy)



        report_lines = [

            f"## Judge Report — Macro Iter {state.get('macro_iter', 0)}",

            f"- Total questions: {len(scored)}",

            f"- Correct: {correct}",

            f"- Plain accuracy: {plain_accuracy:.2%}",

            f"- Weighted accuracy: {accuracy:.2%} (used for loop)",

            f"- Threshold: {CORRECT_THRESHOLD:.0%}",

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
    qa_payload = build_observer_qa_payload(qa_list)
    history_text = ", ".join(f"{h:.0%}" for h in (accuracy_history or [])[-5:]) or "无"
    weak_text = ", ".join(weak_topics) if weak_topics else "无"

    prompt = f"""你是学习导师 C，同时承担学习规划者与学习方法论教练的角色。
你的任务不是旁观记录，而是基于学生 A 本轮答题表现，给出可执行的指导：
- 诊断知识掌握与答题问题
- 指出并纠正不良学习习惯、错误认知或低效做法
- 提供具体、可操作的学习方法论建议
- 制定下一轮学习规划（优先级、时间分配、复习策略）

原则：
- 建议要具体，避免空泛鼓励
- 区分「知识缺口」与「方法/习惯问题」
- 对重复出现的错误模式要明确指出并给出替代做法
- 规划需与薄弱主题和当前迭代阶段匹配

当前宏观迭代：{macro_iter}
本轮加权正确率：{accuracy:.2%}
历史正确率（近几轮）：{history_text}
薄弱主题：{weak_text}

学生笔记（节选，用于判断学习方式和笔记质量）：
{study_notes[:3500]}

作答数据（优先包含错题及 Judge 评语）：
{json.dumps(qa_payload, ensure_ascii=False, indent=2)}

输出 JSON：
{{
  "performance_diagnosis": "基于答题情况的诊断（Markdown，含按题型/主题的问题归纳）",
  "habit_corrections": "需纠正的学习习惯或错误想法（Markdown，逐条：问题→为何有害→应如何改）",
  "methodology_advice": "学习方法论建议（Markdown，如主动回忆、费曼、间隔复习、错题复盘等，结合本轮表现选型）",
  "study_plan": "下一轮学习规划（Markdown，含优先级排序、建议步骤、自测方式）",
  "mentor_summary": "导师一句话总结（50字内，直接点出最该改的一件事）"
}}"""
    resp = llm.invoke(
        [
            SystemMessage(
                content="你是严厉但支持学生的学习导师。聚焦可改变的习惯与方法，不说空话。"
            ),
            HumanMessage(content=prompt),
        ]
    )
    return extract_json(resp.content)


def _build_mentor_report(record: ObservationRecord, macro: int) -> str:
    return "\n\n".join(
        [
            f"# 学习导师反馈 — 第 {macro} 轮",
            "## 导师寄语\n" + record.get("mentor_summary", ""),
            "## 答题诊断\n" + record.get("performance_diagnosis", ""),
            "## 习惯与认知纠正\n" + record.get("habit_corrections", ""),
            "## 学习方法建议\n" + record.get("methodology_advice", ""),
            "## 下轮学习规划\n" + record.get("study_plan", ""),
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
            performance_diagnosis=data.get("performance_diagnosis", ""),
            habit_corrections=data.get("habit_corrections", ""),
            methodology_advice=data.get("methodology_advice", ""),
            study_plan=data.get("study_plan", ""),
            mentor_summary=data.get("mentor_summary", ""),
        )

        report = _build_mentor_report(record, macro)

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
