"""Graph nodes — fetch, material, study, refine, consolidate."""

from __future__ import annotations


import json

import logging

from pathlib import Path


from langchain_core.messages import HumanMessage, SystemMessage


from langgraph.types import Overwrite


from src.config import ensure_output_dir, get_settings, load_loop_config, load_personas

from src.graph.state import LearnLoopState

from src.models.llm_factory import material_llm, student_llm

from src.tools.json_utils import extract_json, llm_content_to_str, llm_retry

from src.logging_config import get_loop_logger

from src.tools.learning_policy import (
    append_chapter_archive,
    build_chapter_study_context,
    build_learning_journal,
    build_study_context,
    chapter_label,
    chunks_for_chapter,
    current_chapter,
    curriculum_chunks,
    curriculum_delta_chunks,
    curriculum_page_range_label,
    format_wrong_qa_feedback,
    init_chapter_mastery_dict,
    is_chapter_mastery_mode,
)

from src.tools.web_fetch import build_chapter_registry, fetch_and_chunk_urls, material_context


logger = get_loop_logger()

loop_cfg = load_loop_config()


def fetch_pages(state: LearnLoopState) -> dict:

    urls = state.get("urls") or []

    if not urls:

        return {
            "status": "failed",
            "error_message": "No URLs provided",
            "phase": "fetch",
        }

    try:

        chunks, manifest = fetch_and_chunk_urls(
            urls,
            crawl_enabled=state.get("crawl_enabled", True),
        )

        task_id = state.get("task_id", "default")

        out = ensure_output_dir(task_id)

        registry = manifest.get("chapter_registry") or build_chapter_registry(chunks)

        (out / "raw_chunks.json").write_text(
            json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        (out / "chapter_registry.json").write_text(
            json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        (out / "crawl_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        logger.info(
            "crawl discovered=%s fetched=%s chunks=%s chapters=%s images=%s",
            manifest.get("discovered_per_seed"),
            manifest.get("fetched_per_seed"),
            manifest.get("total_chunks"),
            len(registry),
            sum(p.get("images", 0) for p in manifest.get("pages", [])),
        )

        return {
            "raw_chunks": chunks,
            "chapter_registry": registry,
            "chapter_mastery": init_chapter_mastery_dict(registry),
            "current_chapter_index": 0,
            "long_term_notes": "",
            "short_term_notes": "",
            "phase": "generate_material",
        }

    except Exception as exc:

        logger.exception("fetch_pages failed")

        return {"status": "failed", "error_message": str(exc), "phase": "fetch"}


def _study_scope_chunks(state: LearnLoopState) -> list[dict]:
    settings = get_settings()
    chunks = state.get("raw_chunks") or []
    if is_chapter_mastery_mode():
        registry = state.get("chapter_registry") or []
        idx = int(state.get("current_chapter_index", 0) or 0)
        ch = current_chapter(registry, idx)
        if ch:
            scoped = chunks_for_chapter(chunks, ch["chapter_id"])
            return scoped or chunks
    curriculum_level = state.get("curriculum_level", 0)
    return curriculum_chunks(chunks, curriculum_level, settings.curriculum_pages_per_round)


@llm_retry()
def _generate_material_llm(goal: str, context: str, macro_iter: int, scope_label: str) -> dict:

    llm = material_llm()

    prompt = f"""你是学习资料编写专家。仅根据以下网页原文生成学习资料，禁止臆造。

当前为第 {macro_iter + 1} 学习阶段，资料只需覆盖：{scope_label}，不要超前编写未提供的内容。



学习目标：{goal}



原文分块：

{context}



输出 JSON：

{{

  "study_material": "本阶段 Markdown 学习资料，含章节、要点、术语表",

  "knowledge_cards": [

    {{"question": "...", "answer": "...", "source_ref": "chunk_id"}}

  ]

}}"""

    resp = llm.invoke(
        [
            SystemMessage(content="只使用提供的原文事实，标注来源 chunk id。"),
            HumanMessage(content=prompt),
        ]
    )

    return extract_json(resp.content)


def generate_material(state: LearnLoopState) -> dict:

    chunks = state.get("raw_chunks") or []

    goal = state.get("goal", "掌握网页核心知识")

    settings = get_settings()

    macro = state.get("macro_iter", 0)
    unlocked = _study_scope_chunks(state)

    if is_chapter_mastery_mode():
        registry = state.get("chapter_registry") or []
        idx = int(state.get("current_chapter_index", 0) or 0)
        scope_label = chapter_label(registry, idx)
    else:
        scope_label = curriculum_page_range_label(
            state.get("curriculum_level", 0), settings.curriculum_pages_per_round
        )

    context = material_context(unlocked, max_chars=settings.material_context_max_chars)

    logger.info(
        "generate_material macro=%s scope=%s unlocked_chunks=%d/%d mode=%s",
        macro,
        scope_label,
        len(unlocked),
        len(chunks),
        settings.learning_mode,
    )

    try:

        data = _generate_material_llm(goal, context, macro, scope_label)

        material = data.get("study_material", "")

        cards = data.get("knowledge_cards", [])

        task_id = state.get("task_id", "default")

        out = ensure_output_dir(task_id)

        suffix = f"_iter_{macro}" if macro else ""

        (out / f"study_material{suffix}.md").write_text(material, encoding="utf-8")

        return {
            "study_material": material,
            "knowledge_cards": cards,
            "regenerate_material": False,
            "phase": "student_study",
        }

    except Exception as exc:

        logger.exception("generate_material failed")

        return {"status": "failed", "error_message": str(exc)}


@llm_retry()
def _study_llm(
    material: str,
    weak_topics: list[str],
    *,
    notes_max_chars: int,
    macro_iter: int,
    scope_label: str,
    prior_notes: str = "",
    wrong_feedback: str = "",
) -> str:

    llm = student_llm()

    weak_text = ", ".join(weak_topics) if weak_topics else "无"
    prior_section = ""
    if prior_notes.strip():
        prior_section = f"""
## 上轮笔记（请在此基础上增量完善、查漏补缺）
{prior_notes.strip()[: notes_max_chars // 2]}

"""
    wrong_section = ""
    if wrong_feedback.strip():
        wrong_section = f"""
{wrong_feedback.strip()}

"""

    prompt = f"""你是认真严谨的学习者 A。请在充分理解以下资料的基础上，整理一份清晰、专业且易懂的学习笔记。

记忆分层要求（必须按此结构输出 Markdown）：
1. **## 知识框架** 与 **## 核心概念与要点** — 完整、详尽，用于学习过程与最终归档（闭卷时不可全文查阅）
2. **## 薄弱点强化梳理**、**## 待澄清 / 易混淆点** — 可标注为浅层参考，闭卷时仅这部分的摘录可辅助回忆
3. **## 自测要点** — 5 条检验题，属于浅层参考层（闭卷时可看摘录，非完整笔记）
4. 可选 **## 关键术语速查** — 术语对照表，属于浅层参考层

要求：
- 在理解之后用自己的话条理化组织，知识点结构清晰、层次分明
- 完整覆盖本课程窗口的核心要点，不遗漏关键概念
- 对资料未讲透或你存疑之处，在「待澄清」中明确标注并补全理解
- 表述准确专业，同时通俗易懂；不要大段照抄原文或完整 YAML/配置
- 总长度不超过 {notes_max_chars} 字
- 当前为第 {macro_iter + 1} 轮学习，在上一轮笔记基础上增量完善、查漏补缺
- {scope_label}；只学本窗口内容，不要编造未提供章节

薄弱点（需重点强化）：{weak_text}
{prior_section}{wrong_section}
学习资料（与课程解锁窗口对齐）：

{material}

输出 Markdown，必须包含以下章节标题（顺序可调整）：
1. 知识框架
2. 核心概念与要点
3. 薄弱点强化梳理
4. 待澄清 / 易混淆点
5. 自测要点（恰好 5 条）"""

    resp = llm.invoke([HumanMessage(content=prompt)])

    notes = llm_content_to_str(resp.content)

    if len(notes) > notes_max_chars:

        notes = notes[:notes_max_chars] + "\n\n…（笔记已达长度上限，部分细节未记录）"

    return notes


def student_study(state: LearnLoopState) -> dict:

    weak = state.get("weak_topics") or []

    settings = get_settings()

    macro = state.get("macro_iter", 0)
    raw_chunks = state.get("raw_chunks") or []

    if is_chapter_mastery_mode():
        registry = state.get("chapter_registry") or []
        idx = int(state.get("current_chapter_index", 0) or 0)
        scope_label = chapter_label(registry, idx)
        prior = state.get("short_term_notes") or state.get("study_notes") or ""
        notes_max = settings.short_term_notes_max_chars
        study_ctx = build_chapter_study_context(
            raw_chunks=raw_chunks,
            chapter_registry=registry,
            current_chapter_index=idx,
            study_material=state.get("study_material") or "",
            long_term_notes=state.get("long_term_notes") or "",
            short_term_notes=prior,
            max_chars=settings.student_material_study_max_chars,
        )
    else:
        curriculum_level = state.get("curriculum_level", 0)
        scope_label = curriculum_page_range_label(
            curriculum_level, settings.curriculum_pages_per_round
        )
        prior = state.get("study_notes") or ""
        notes_max = settings.student_notes_study_max_chars
        study_ctx = build_study_context(
            raw_chunks=raw_chunks,
            study_material=state.get("study_material") or "",
            curriculum_level=curriculum_level,
            pages_per_round=settings.curriculum_pages_per_round,
            max_chars=settings.student_material_study_max_chars,
        )

    try:

        wrong_feedback = format_wrong_qa_feedback(
            list(state.get("current_batch_qa") or []),
            max_items=8,
        )

        notes = _study_llm(
            study_ctx,
            weak,
            notes_max_chars=notes_max,
            macro_iter=macro,
            scope_label=scope_label,
            prior_notes=prior,
            wrong_feedback=wrong_feedback,
        )

        task_id = state.get("task_id", "default")

        out = ensure_output_dir(task_id)

        (out / f"study_notes_iter_{macro}.md").write_text(notes, encoding="utf-8")

        result = {
            "study_notes": notes,
            "phase": "prepare_exam",
        }
        if is_chapter_mastery_mode():
            result["short_term_notes"] = notes
            registry = state.get("chapter_registry") or []
            idx = int(state.get("current_chapter_index", 0) or 0)
            ch = current_chapter(registry, idx)
            archive = list(state.get("chapter_notes_archive") or [])
            journal = build_learning_journal(
                archive,
                goal=state.get("goal", ""),
                in_progress_chapter=ch,
                in_progress_notes=notes,
            )
            result["learning_journal"] = journal
            (out / "learning_journal.md").write_text(journal, encoding="utf-8")
        return result

    except Exception as exc:

        logger.exception("student_study failed")

        return {"status": "failed", "error_message": str(exc)}


def prepare_exam(state: LearnLoopState) -> dict:
    """Determine how many exam batches to run this macro iteration.

    One batch = questions_per_persona × (number of personas) questions.
    """

    settings = get_settings()

    macro = state.get("macro_iter", 0)

    is_first = macro == 0

    num_personas = max(1, len(load_personas()))

    questions_per_batch = max(1, settings.questions_per_persona * num_personas)

    if is_first:

        batches_target = settings.first_round_total_questions // questions_per_batch

    else:

        batches_target = settings.focused_round_questions // questions_per_batch

    return {
        "exam_batch_index": 0,
        "exam_batches_target": max(1, batches_target),
        "current_batch_qa": Overwrite([]),
        "current_batch_questions": [],
        "phase": "persona_exam_fanout",
    }


@llm_retry()
def _refine_material_llm(
    material: str,
    weak_topics: list[str],
    judge_report: str,
    new_context: str,
    macro_iter: int,
    scope_label: str,
) -> str:

    llm = material_llm()

    new_section = ""

    if new_context.strip():

        new_section = f"""

本阶段新解锁章节原文：

{new_context}

"""

    prompt = f"""根据测验薄弱点，在原有学习资料基础上：

1. 补充「薄弱点强化章节」（始终执行）

2. 若下方提供了新解锁章节原文，则合并其要点；若无新原文，不要编造新章节

只补充有依据的内容，不可臆造。当前课程窗口：{scope_label}。



薄弱点：{json.dumps(weak_topics, ensure_ascii=False)}

Judge 报告摘要：

{judge_report[:4000]}

{new_section}

原资料（节选）：

{material[:12000]}



输出完整更新后的 Markdown 学习资料。"""

    resp = llm.invoke([HumanMessage(content=prompt)])

    return llm_content_to_str(resp.content)


def refine_material(state: LearnLoopState) -> dict:

    material = state.get("study_material") or ""

    weak = state.get("weak_topics") or []

    report = state.get("judge_report") or ""

    settings = get_settings()

    macro = state.get("macro_iter", 0)

    raw_chunks = state.get("raw_chunks") or []

    try:

        if is_chapter_mastery_mode():
            registry = state.get("chapter_registry") or []
            idx = int(state.get("current_chapter_index", 0) or 0)
            scope_label = chapter_label(registry, idx)
            new_context = ""
        else:
            curriculum_level = state.get("curriculum_level", 0)
            scope_label = curriculum_page_range_label(
                curriculum_level, settings.curriculum_pages_per_round
            )
            advanced = state.get("curriculum_advanced", False)
            delta = (
                curriculum_delta_chunks(
                    raw_chunks, curriculum_level - 1, settings.curriculum_pages_per_round
                )
                if advanced and curriculum_level > 0
                else []
            )
            new_context = material_context(
                delta, max_chars=settings.material_context_max_chars // 2
            )

        updated = _refine_material_llm(
            material, weak, report, new_context, macro, scope_label
        )

        task_id = state.get("task_id", "default")

        out = ensure_output_dir(task_id)

        (out / f"study_material_iter_{macro + 1}.md").write_text(
            updated, encoding="utf-8"
        )

        logger.info(
            "refine_material macro=%s scope=%s mode=%s",
            macro,
            scope_label,
            settings.learning_mode,
        )

        result = {
            "study_material": updated,
            "macro_iter": 1,
            "phase": "student_study",
        }
        if not is_chapter_mastery_mode():
            result["curriculum_advanced"] = False
        return result

    except Exception as exc:

        logger.exception("refine_material failed")

        return {"status": "failed", "error_message": str(exc)}


@llm_retry()
def _consolidate_notes_llm(chapter_title: str, notes: str, max_chars: int) -> str:
    llm = student_llm()
    prompt = f"""请将以下关于「{chapter_title}」的学习笔记压缩为**长期记忆（内化层）**摘要。
要求：
- 只保留已理解、可脱离笔记回忆的核心概念、原理、关键术语与易错点
- 删除详细展开、大段解释、例题步骤（那些留在归档笔记中，不属于长期记忆）
- 200–{max_chars} 字，Markdown 小节格式
- 不要添加原文中没有的内容

完整工作笔记（从中提取内化层）：
{notes[:8000]}

输出 Markdown 摘要（不要 JSON）。"""
    resp = llm.invoke([HumanMessage(content=prompt)])
    summary = llm_content_to_str(resp.content).strip()
    if len(summary) > max_chars:
        return summary[:max_chars] + "…"
    return summary


def consolidate_chapter_notes(state: LearnLoopState) -> dict:
    """Compress short-term notes into long-term memory after chapter mastery."""
    if not is_chapter_mastery_mode():
        return {"phase": "observer_analyze"}

    settings = get_settings()
    registry = state.get("chapter_registry") or []
    idx = int(state.get("current_chapter_index", 0) or 0)
    ch = current_chapter(registry, idx)
    if not ch:
        return {"phase": "observer_analyze"}

    chapter_id = ch["chapter_id"]
    mastery = dict(state.get("chapter_mastery") or {})
    rec = mastery.get(chapter_id) or {}
    if not rec.get("mastered"):
        return {"phase": "observer_analyze"}

    short_notes = state.get("short_term_notes") or state.get("study_notes") or ""
    long_term = state.get("long_term_notes") or ""
    archive = list(state.get("chapter_notes_archive") or [])
    per_chapter_budget = max(200, settings.long_term_notes_max_chars // max(len(registry), 1))
    macro = state.get("macro_iter", 0)

    try:
        if short_notes.strip():
            archive = append_chapter_archive(
                archive,
                ch,
                short_notes,
                macro_iter=macro,
            )
            summary = _consolidate_notes_llm(
                ch.get("chapter_title", ""),
                short_notes,
                per_chapter_budget,
            )
            block = f"## {ch.get('chapter_title', '')}\n{summary}"
            long_term = (long_term + "\n\n" + block).strip()
            if len(long_term) > settings.long_term_notes_max_chars:
                long_term = long_term[-settings.long_term_notes_max_chars :]
                long_term = "…（早期摘要已截断）\n" + long_term
        else:
            summary = ""

        journal = build_learning_journal(
            archive,
            goal=state.get("goal", ""),
        )

        task_id = state.get("task_id", "default")
        out = ensure_output_dir(task_id)
        (out / f"long_term_notes_iter_{macro}.md").write_text(long_term, encoding="utf-8")
        (out / "learning_journal.md").write_text(journal, encoding="utf-8")
        (out / f"chapter_archive_{ch.get('chapter_id', 'unknown')}.md").write_text(
            short_notes or "（空）", encoding="utf-8"
        )

        new_index = idx
        regenerate = False
        if idx < len(registry) - 1:
            new_index = idx + 1
            regenerate = True
            logger.info(
                "consolidate chapter=%s mastered -> next index=%s",
                chapter_id,
                new_index,
            )

        return {
            "long_term_notes": long_term,
            "short_term_notes": "",
            "study_notes": "",
            "chapter_notes_archive": archive,
            "learning_journal": journal,
            "reinforce_questions": [],
            "current_chapter_index": new_index,
            "regenerate_material": regenerate,
            "chapter_advanced": False,
            "phase": "observer_analyze",
        }
    except Exception as exc:
        logger.exception("consolidate_chapter_notes failed")
        return {"status": "failed", "error_message": str(exc)}
