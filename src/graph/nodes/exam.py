"""Parent graph exam nodes — persona fan-out + student answers."""

from __future__ import annotations

import json
import os
from collections import Counter

from langchain_core.messages import HumanMessage

from src.config import ensure_output_dir, get_settings, load_loop_config, load_personas
from src.graph.state import ExamQA, LearnLoopState, QuestionItem
from src.graph.subgraphs.persona_exam.build import get_compiled_persona_exam
from src.graph.subgraphs.persona_exam.state import PersonaExamState
from src.logging_config import get_loop_logger
from src.models.llm_factory import student_exam_llm
from src.tools.json_utils import extract_json, llm_retry
from src.tools.learning_policy import (
    chapter_label,
    chunks_for_exam,
    current_chapter,
    curriculum_chunks,
    exam_notes_char_budget,
    filter_chunks_by_ids,
    is_chapter_mastery_mode,
    normalize_exam_memory_mode,
    normalize_topic_key,
    question_content_fingerprint,
    reinforce_pool_cap,
    select_exam_notes,
    study_aligned_chunk_ids,
    _dup_tokens,
)

logger = get_loop_logger()
PERSONAS = load_personas()
loop_cfg = load_loop_config()
_persona_subgraph = get_compiled_persona_exam()


def _max_validate_rounds() -> int:
    raw = os.getenv("MAX_VALIDATE_ROUNDS")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return int(loop_cfg.get("exam", {}).get("max_validate_rounds", 3))


def build_persona_exam_input(
    parent: LearnLoopState,
    persona: dict,
    batch_idx: int,
    persona_index: int = 0,
    num_personas: int = 1,
) -> PersonaExamState:
    settings = get_settings()
    macro = parent.get("macro_iter", 0)
    curriculum_level = parent.get("curriculum_level", 0)
    difficulty_level = parent.get("difficulty_level", 0)
    all_chunks = list(parent.get("raw_chunks") or [])

    if is_chapter_mastery_mode():
        registry = list(parent.get("chapter_registry") or [])
        ch_index = int(parent.get("current_chapter_index", 0) or 0)
        mastery = dict(parent.get("chapter_mastery") or {})
        ch = current_chapter(registry, ch_index)
        unlocked = chunks_for_exam(
            all_chunks,
            registry,
            ch_index,
            mastery,
            review_ratio=settings.chapter_review_ratio,
            chapter_mastery_mode=True,
        )
        range_hint = chapter_label(registry, ch_index)
        chapter_scope_label = range_hint
        evidence_pool = list(unlocked)
        allowed_ids: set[str] = set()
        if ch:
            allowed_ids = study_aligned_chunk_ids(
                all_chunks,
                ch["chapter_id"],
                study_material=parent.get("study_material") or "",
                short_term_notes=parent.get("short_term_notes")
                or parent.get("study_notes")
                or "",
                knowledge_cards=list(parent.get("knowledge_cards") or []),
            )
            unlocked = filter_chunks_by_ids(unlocked, allowed_ids)
    else:
        unlocked = curriculum_chunks(
            all_chunks, curriculum_level, settings.curriculum_pages_per_round
        )
        evidence_pool = list(unlocked)
        range_hint = ""
        chapter_scope_label = ""
        allowed_ids = set()

    # (A) Give each persona a DIFFERENT focus so they don't all ask the same
    # thing. Weak topics are split round-robin; each persona also gets a distinct
    # slice of chunk titles to emphasize (full chunks still passed for evidence).
    num_personas = max(1, num_personas)
    all_weak = list(parent.get("weak_topics") or [])
    persona_weak = all_weak[persona_index::num_personas]
    focus_titles: list[str] = []
    seen_titles: set[str] = set()
    for chunk in unlocked[persona_index::num_personas]:
        title = (chunk.get("heading") or chunk.get("title") or "").strip()
        if title and title not in seen_titles:
            seen_titles.add(title)
            focus_titles.append(title)
    focus_hint = "、".join(focus_titles[:6])
    if range_hint:
        focus_hint = f"{range_hint} — {focus_hint}" if focus_hint else range_hint

    return PersonaExamState(
        persona_id=persona["id"],
        persona_name=persona["name"],
        persona_style=persona.get("style", ""),
        persona_prompt_hint=persona.get("prompt_hint", ""),
        material_snapshot=parent.get("study_material") or "",
        chunks_snapshot=unlocked,
        evidence_pool_snapshot=evidence_pool,
        weak_topics_snapshot=persona_weak,
        focus_hint=focus_hint,
        chapter_scope_label=chapter_scope_label,
        allowed_evidence_ids=sorted(allowed_ids),
        macro_iter_snapshot=macro,
        difficulty_level_snapshot=difficulty_level,
        curriculum_level_snapshot=curriculum_level,
        exam_batch_index_snapshot=batch_idx,
        questions_target=settings.questions_per_persona,
        max_validate_rounds=_max_validate_rounds(),
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


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _question_fingerprint(text: str) -> str:
    return question_content_fingerprint(text)


def _qa_to_question_item(qa: ExamQA) -> QuestionItem:
    return QuestionItem(
        question=qa.get("question", ""),
        evidence_refs=list(qa.get("evidence_refs") or []),
        topic_tag=qa.get("topic_tag", ""),
        weak_topic_focus=qa.get("weak_topic_focus", ""),
        persona_id=qa.get("persona_id", "reinforce"),
        persona_name=qa.get("persona_name", "巩固复测"),
        is_reinforce=True,
    )


def _merge_reinforce_questions(
    new_questions: list[QuestionItem],
    reinforce_pool: list[QuestionItem],
    *,
    max_reinforce: int,
    graduated_topics: set[str] | None = None,
) -> list[QuestionItem]:
    """Prepend pending wrong questions so the student re-encounters them."""
    if not reinforce_pool or max_reinforce <= 0:
        return new_questions
    graduated = graduated_topics or set()
    existing = {_question_fingerprint(q.get("question", "")) for q in new_questions}
    picked: list[QuestionItem] = []
    for item in reinforce_pool:
        tag = normalize_topic_key(
            item.get("topic_tag", ""),
            item.get("question", ""),
            item.get("weak_topic_focus", ""),
        )
        if tag in graduated:
            continue
        fp = _question_fingerprint(item.get("question", ""))
        if fp in existing:
            continue
        picked.append(dict(item))
        existing.add(fp)
        if len(picked) >= max_reinforce:
            break
    if not picked:
        return new_questions
    return picked + new_questions


def _dedupe_questions(
    questions: list[QuestionItem],
    threshold: float = 0.6,
    same_tag_threshold: float = 0.35,
) -> list[QuestionItem]:
    """(B) Drop near-duplicate questions across personas.

    Two questions are duplicates if their content tokens overlap past
    ``threshold``, OR they share a topic_tag and overlap past the lower
    ``same_tag_threshold`` (same tag strongly signals the same concept, which is
    how reworded "define X" questions slip through plain token overlap).
    """
    kept: list[QuestionItem] = []
    kept_tokens: list[set[str]] = []
    kept_tags: list[str] = []
    for q in questions:
        toks = _dup_tokens(q.get("question", ""))
        tag = (q.get("topic_tag") or "").strip()
        is_dup = False
        for ktoks, ktag in zip(kept_tokens, kept_tags):
            j = _jaccard(toks, ktoks)
            if j >= threshold or (tag and tag == ktag and j >= same_tag_threshold):
                is_dup = True
                break
        if is_dup:
            continue
        kept.append(q)
        kept_tokens.append(toks)
        kept_tags.append(tag)
    return kept


def fanout_persona_exams(state: LearnLoopState) -> dict:
    """Run five persona subgraphs sequentially and collect all questions."""
    if state.get("status") == "failed":
        return {}

    batch_idx = state.get("exam_batch_index", 0)
    macro = state.get("macro_iter", 0)
    task_id = state.get("task_id", "default")

    all_questions: list[QuestionItem] = []
    raw_by_persona: dict[str, int] = {}

    for idx, persona in enumerate(PERSONAS):
        inp = build_persona_exam_input(state, persona, batch_idx, idx, len(PERSONAS))
        qs = _invoke_persona_exam(inp)
        raw_by_persona[persona["id"]] = len(qs)
        all_questions.extend(qs)

    # (B) Remove cross-persona duplicates before scoring.
    deduped = _dedupe_questions(all_questions)
    removed = len(all_questions) - len(deduped)
    all_questions = deduped

    reinforce_pool = list(state.get("reinforce_questions") or [])
    ch_attempts = 0
    if is_chapter_mastery_mode():
        registry = state.get("chapter_registry") or []
        ch_index = int(state.get("current_chapter_index", 0) or 0)
        ch = current_chapter(registry, ch_index)
        if ch:
            rec = (state.get("chapter_mastery") or {}).get(ch.get("chapter_id", "")) or {}
            ch_attempts = int(rec.get("attempts", 0) or 0)
    max_reinforce = reinforce_pool_cap(
        len(all_questions),
        macro_iter=macro,
        chapter_attempts=ch_attempts,
    )
    all_questions = _merge_reinforce_questions(
        all_questions,
        reinforce_pool,
        max_reinforce=max_reinforce,
        graduated_topics=set(state.get("graduated_topic_tags") or []),
    )
    reinforce_added = sum(1 for q in all_questions if q.get("is_reinforce"))

    by_persona = dict(Counter(q.get("persona_id", "?") for q in all_questions))

    logger.info(
        "fanout macro=%s batch=%s total_questions=%d (deduped from %d, -%d, reinforce=%d) by_persona=%s",
        macro,
        batch_idx,
        len(all_questions),
        len(all_questions) + removed,
        removed,
        reinforce_added,
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
    long_term_notes: str = "",
    short_term_notes: str = "",
    chapter_title: str = "",
    chapter_notes_archive: list[dict] | None = None,
    current_chapter_id: str = "",
    exam_memory_mode: str = "full_notes",
) -> list[str]:
    llm = student_exam_llm()
    q_payload = json.dumps(questions, ensure_ascii=False, indent=2)
    mode = normalize_exam_memory_mode(exam_memory_mode)
    notes_excerpt = select_exam_notes(
        notes=study_notes,
        max_chars=notes_max_chars,
        long_term_notes=long_term_notes,
        short_term_notes=short_term_notes,
        chapter_title=chapter_title,
        chapter_notes_archive=chapter_notes_archive,
        current_chapter_id=current_chapter_id,
    )

    reinforce_tags = [
        normalize_topic_key(q.get("topic_tag", ""), q.get("question", ""))
        for q in questions
        if q.get("is_reinforce")
    ]
    reinforce_hint = ""
    if reinforce_tags:
        memory_hint = (
            "请依据可用记忆作答"
            if mode == "full_notes"
            else "请依据长期记忆与当前章笔记作答"
            if mode == "long_term"
            else "请依据长期记忆与参考层作答"
        )
        reinforce_hint = (
            f"\n\n【巩固题提示】含上轮错题复测（考点：{', '.join(sorted(set(reinforce_tags))[:6])}）。"
            f"题目措辞可能与笔记不同，但考点相同；{memory_hint}，语义正确即可。"
        )

    accuracy_rules = """作答精度（与「发散」平衡）：
- 优先准确：只写记忆材料中有的机制；**不要把机制条件写反**
- 对「会自动检测/提示」类问题：写清默认后果，不确定则说「不确定」
- 不要为了显得完整而补充 plausible 但无依据的因果链
- 记不清的内容请明确说「不确定」或「不知道」
- 回答用自然语言，简洁优先；不要贴完整 YAML/大段代码
- 英文术语大小写按你记住的形式书写即可（etcd/Etcd 均可）"""

    if closed_book:
        if mode == "full_notes":
            memory_intro = (
                "你是学生 A，正在进行闭卷考试（可查阅完整工作笔记，不可查阅教材原文）。"
            )
            memory_label = "你的完整工作笔记（含已掌握章节归档 + 当前章）"
        elif mode == "long_term":
            memory_intro = (
                "你是学生 A，正在进行闭卷考试（A-MEM 长期记忆 + 当前章完整笔记，不可查阅教材原文）。"
            )
            memory_label = "你的可用记忆（长期内化摘要 + 当前章工作笔记）"
        else:
            memory_intro = (
                "你是学生 A，正在进行闭卷考试。"
                "你只能依靠「长期记忆（内化知识）」与「工作记忆参考层（术语/易错/自测摘录）」作答。"
                "完整手抄笔记、教材原文不在考场上可用。"
            )
            memory_label = "你的可用记忆（已按人脑分层筛选，非完整笔记）"

        prompt = f"""{memory_intro}

{accuracy_rules}{reinforce_hint}

{memory_label}：
{notes_excerpt or "（尚无可用记忆）"}

题目列表：
{q_payload}

输出 JSON 数组，与题目顺序一一对应：
[{{"answer": "你的回答"}}]"""
    else:
        prompt = f"""你是学生 A。根据学习笔记作答。不知道请明确说「不知道」。
{accuracy_rules}{reinforce_hint}

学习笔记：
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
    short_term = state.get("short_term_notes") or study_notes
    long_term = state.get("long_term_notes") or ""
    batch_idx = state.get("exam_batch_index", 0)
    macro = state.get("macro_iter", 0)
    settings = get_settings()

    chapter_title = ""
    current_chapter_id = ""
    if is_chapter_mastery_mode():
        registry = state.get("chapter_registry") or []
        ch = current_chapter(registry, int(state.get("current_chapter_index", 0) or 0))
        chapter_title = (ch or {}).get("chapter_title", "")
        current_chapter_id = (ch or {}).get("chapter_id", "")

    archive = list(state.get("chapter_notes_archive") or [])
    exam_memory_mode = normalize_exam_memory_mode(
        getattr(settings, "exam_memory_mode", "full_notes")
    )

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
                notes_max_chars=exam_notes_char_budget(),
                long_term_notes=long_term,
                short_term_notes=short_term,
                chapter_title=chapter_title,
                chapter_notes_archive=archive,
                current_chapter_id=current_chapter_id,
                exam_memory_mode=exam_memory_mode,
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
                        is_reinforce=bool(q.get("is_reinforce")),
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

