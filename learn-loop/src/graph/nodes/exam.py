"""Parent graph exam nodes — persona fan-out + student answers."""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage
from langgraph.types import Overwrite

from src.config import ensure_output_dir, get_settings, load_loop_config, load_personas
from src.graph.state import ExamQA, LearnLoopState, QuestionItem
from src.graph.subgraphs.persona_exam.build import get_compiled_persona_exam
from src.graph.subgraphs.persona_exam.state import PersonaExamState
from src.logging_config import get_loop_logger
from src.models.llm_factory import student_llm
from src.tools.json_utils import extract_json, llm_retry
from src.tools.learning_policy import curriculum_chunks

logger = get_loop_logger()
PERSONAS = load_personas()
loop_cfg = load_loop_config()
MAX_VALIDATE = loop_cfg.get("exam", {}).get("max_validate_rounds", 3)
_persona_subgraph = get_compiled_persona_exam()


def build_persona_exam_input(
    parent: LearnLoopState,
    persona: dict,
    batch_idx: int,
) -> PersonaExamState:
    settings = get_settings()
    macro = parent.get("macro_iter", 0)
    all_chunks = list(parent.get("raw_chunks") or [])
    unlocked = curriculum_chunks(
        all_chunks, macro, settings.curriculum_pages_per_round
    )
    return PersonaExamState(
        persona_id=persona["id"],
        persona_name=persona["name"],
        persona_style=persona.get("style", ""),
        persona_prompt_hint=persona.get("prompt_hint", ""),
        material_snapshot=parent.get("study_material") or "",
        chunks_snapshot=unlocked,
        weak_topics_snapshot=list(parent.get("weak_topics") or []),
        macro_iter_snapshot=macro,
        exam_batch_index_snapshot=batch_idx,
        questions_target=settings.questions_per_persona,
        max_validate_rounds=MAX_VALIDATE,
        validate_round=0,
        retrieved_chunks=[],
        search_queries=[],
        search_results=[],
        draft_questions=[],
        validation_errors=[],
        validation_passed=False,
        final_questions=[],
        persona_status="running",
    )


def _invoke_persona_exam(state: PersonaExamState) -> list[QuestionItem]:
    persona_id = state.get("persona_id", "?")
    try:
        result = _persona_subgraph.invoke(dict(state))
        questions = list(result.get("final_questions") or [])
        if not questions:
            errors = result.get("validation_errors") or []
            logger.warning(
                "persona=%s questions=0 validation_errors=%s",
                persona_id,
                errors[:2],
            )
        else:
            logger.info("persona=%s questions=%d", persona_id, len(questions))
        return questions
    except Exception:
        logger.exception("persona=%s invoke failed", persona_id)
        return []


def fanout_persona_exams(state: LearnLoopState) -> dict:
    """Run five persona subgraphs sequentially and collect all questions."""
    if state.get("status") == "failed":
        return {}

    batch_idx = state.get("exam_batch_index", 0)
    macro = state.get("macro_iter", 0)
    task_id = state.get("task_id", "default")

    all_questions: list[QuestionItem] = []
    by_persona: dict[str, int] = {}

    for persona in PERSONAS:
        inp = build_persona_exam_input(state, persona, batch_idx)
        qs = _invoke_persona_exam(inp)
        pid = persona["id"]
        by_persona[pid] = len(qs)
        all_questions.extend(qs)

    logger.info(
        "fanout macro=%s batch=%s total_questions=%d by_persona=%s",
        macro,
        batch_idx,
        len(all_questions),
        by_persona,
    )

    out = ensure_output_dir(task_id)
    (out / f"persona_questions_iter{macro}_batch{batch_idx}.json").write_text(
        json.dumps(all_questions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if not all_questions:
        return {
            "status": "failed",
            "error_message": (
                f"Persona exam produced 0 questions (macro={macro}, batch={batch_idx}, "
                f"by_persona={by_persona})"
            ),
            "phase": "persona_exam_fanout",
            "persona_counts": by_persona,
        }

    return {
        "current_batch_questions": all_questions,
        "phase": "student_answer_batch",
        "persona_counts": by_persona,
    }


def begin_persona_fanout(state: LearnLoopState) -> dict:
    """Prepare next exam batch within the same macro iteration."""
    return {
        "current_batch_questions": [],
        "phase": "persona_exam_fanout",
    }


@llm_retry()
def _answer_questions_batch(
    questions: list[QuestionItem],
    study_notes: str,
    *,
    closed_book: bool,
    notes_max_chars: int,
) -> list[str]:
    llm = student_llm()
    q_payload = json.dumps(questions, ensure_ascii=False, indent=2)
    notes_excerpt = study_notes[:notes_max_chars]

    if closed_book:
        prompt = f"""你是学生 A，正在进行闭卷考试。
你只能依靠自己之前整理的学习笔记（记忆可能不完整、有模糊之处）作答。
禁止查阅原文、禁止编造未在笔记中出现的细节。
记不清的内容请明确说「不确定」或「不知道」。
回答用自然语言，不要贴完整 YAML/大段代码。

你的笔记（可能不完整）：
{notes_excerpt or "（尚无笔记）"}

题目列表：
{q_payload}

输出 JSON 数组，与题目顺序一一对应：
[{{"answer": "你的回答"}}]"""
    else:
        prompt = f"""你是学生 A。根据学习笔记作答。不知道请明确说「不知道」。

学习笔记（节选）：
{notes_excerpt}

题目列表：
{q_payload}

输出 JSON 数组，与题目顺序一一对应：
[{{"answer": "你的回答"}}]"""

    resp = llm.invoke([HumanMessage(content=prompt)])
    data = extract_json(resp.content)
    if isinstance(data, dict):
        data = data.get("answers", data.get("responses", []))
    if not isinstance(data, list):
        data = [data] if data else []
    answers: list[str] = []
    for item in data:
        if isinstance(item, str):
            answers.append(item)
        elif isinstance(item, dict):
            answers.append(str(item.get("answer", item.get("content", ""))))
        elif item is not None:
            answers.append(str(item))
        else:
            answers.append("")
    while len(answers) < len(questions):
        answers.append("")
    return answers[: len(questions)]


def student_answer_batch(state: LearnLoopState) -> dict:
    """Parent node: student A answers all questions from persona fan-out."""
    if state.get("status") == "failed":
        return {}

    questions = list(state.get("current_batch_questions") or [])
    study_notes = state.get("study_notes") or ""
    batch_idx = state.get("exam_batch_index", 0)
    macro = state.get("macro_iter", 0)
    settings = get_settings()

    if not questions:
        logger.error(
            "student_answer_batch: no questions macro=%s batch=%s",
            macro,
            batch_idx,
        )
        return {
            "status": "failed",
            "error_message": f"No questions to answer (macro={macro}, batch={batch_idx})",
            "exam_batch_index": batch_idx + 1,
            "phase": "exam_batch_router",
        }

    try:
        chunk_size = settings.student_answer_batch_size
        logger.info(
            "student_answer_batch: answering macro=%s batch=%s count=%d closed_book=%s",
            macro,
            batch_idx,
            len(questions),
            settings.closed_book_exam,
        )

        batch_qa: list[ExamQA] = []
        for start in range(0, len(questions), chunk_size):
            sub_qs = questions[start : start + chunk_size]
            answers = _answer_questions_batch(
                sub_qs,
                study_notes,
                closed_book=settings.closed_book_exam,
                notes_max_chars=settings.student_notes_max_chars,
            )
            for i, (q, a) in enumerate(zip(sub_qs, answers)):
                global_i = start + i
                pid = q.get("persona_id", "unknown")
                batch_qa.append(
                    ExamQA(
                        qa_id=f"iter{macro}_b{batch_idx}_{pid}_{global_i}",
                        macro_iter=macro,
                        exam_batch=batch_idx,
                        persona_id=pid,
                        persona_name=q.get("persona_name", ""),
                        question=q.get("question", ""),
                        answer=a,
                        evidence_refs=q.get("evidence_refs", []),
                        weak_topic_focus=q.get("weak_topic_focus", ""),
                        topic_tag=q.get("topic_tag", ""),
                    )
                )

        existing = list(state.get("current_batch_qa") or [])
        merged_count = len(existing) + len(batch_qa)
        logger.info(
            "student_answer_batch: merged qa macro=%s batch=%s added=%d total=%d",
            macro,
            batch_idx,
            len(batch_qa),
            merged_count,
        )

        return {
            "current_batch_qa": batch_qa,
            "current_batch_questions": [],
            "exam_batch_index": batch_idx + 1,
            "phase": "exam_batch_router",
        }
    except Exception as exc:
        logger.exception("student_answer_batch failed")
        return {"status": "failed", "error_message": str(exc)}
