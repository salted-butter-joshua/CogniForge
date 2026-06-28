"""Graph nodes — fetch, material, study, refine."""

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
    build_study_context,
    curriculum_chunks,
    curriculum_delta_chunks,
    curriculum_page_range_label,
)

from src.tools.web_fetch import fetch_and_chunk_urls, material_context


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

        (out / "raw_chunks.json").write_text(
            json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        (out / "crawl_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        logger.info(
            "crawl discovered=%s fetched=%s chunks=%s images=%s",
            manifest.get("discovered_per_seed"),
            manifest.get("fetched_per_seed"),
            manifest.get("total_chunks"),
            sum(p.get("images", 0) for p in manifest.get("pages", [])),
        )

        return {"raw_chunks": chunks, "phase": "generate_material"}

    except Exception as exc:

        logger.exception("fetch_pages failed")

        return {"status": "failed", "error_message": str(exc), "phase": "fetch"}


@llm_retry()
def _generate_material_llm(goal: str, context: str, macro_iter: int) -> dict:

    llm = material_llm()

    prompt = f"""你是学习资料编写专家。仅根据以下网页原文生成学习资料，禁止臆造。

当前为第 {macro_iter + 1} 学习阶段，资料只需覆盖本阶段已解锁章节，不要超前编写未提供的内容。



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
    curriculum_level = state.get("curriculum_level", 0)

    unlocked = curriculum_chunks(
        chunks, curriculum_level, settings.curriculum_pages_per_round
    )

    context = material_context(unlocked, max_chars=settings.material_context_max_chars)

    logger.info(
        "generate_material macro=%s curriculum_level=%s unlocked_chunks=%d/%d pages_round=%d",
        macro,
        curriculum_level,
        len(unlocked),
        len(chunks),
        settings.curriculum_pages_per_round,
    )

    try:

        data = _generate_material_llm(goal, context, macro)

        material = data.get("study_material", "")

        cards = data.get("knowledge_cards", [])

        task_id = state.get("task_id", "default")

        out = ensure_output_dir(task_id)

        suffix = f"_iter_{macro}" if macro else ""

        (out / f"study_material{suffix}.md").write_text(material, encoding="utf-8")

        return {
            "study_material": material,
            "knowledge_cards": cards,
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
    curriculum_level: int,
    pages_per_round: int,
) -> str:

    llm = student_llm()

    weak_text = ", ".join(weak_topics) if weak_topics else "无"
    range_label = curriculum_page_range_label(curriculum_level, pages_per_round)

    prompt = f"""你是认真严谨的学习者 A。请在充分理解以下资料的基础上，整理一份清晰、专业且易懂的学习笔记。

要求：
- 在理解之后用自己的话条理化组织，知识点结构清晰、层次分明，便于复习
- 完整覆盖本课程窗口的核心要点，不遗漏关键概念
- 对资料未讲透或你存疑之处，明确标注「待澄清」并补全你的理解
- 表述准确专业，同时通俗易懂；不要大段照抄原文或完整 YAML/配置
- 总长度不超过 {notes_max_chars} 字
- 当前为第 {macro_iter + 1} 轮学习，在上一轮笔记基础上增量完善、查漏补缺
- {range_label}；只学本窗口内容，不要编造未提供章节

薄弱点（需重点强化）：{weak_text}

学习资料（与课程解锁窗口对齐）：

{material}

输出 Markdown 学习笔记，包含：

1. 知识框架（清晰的树状结构，覆盖本窗口全部要点）

2. 核心概念与要点（准确、成体系）

3. 薄弱点强化梳理

4. 待澄清 / 易混淆点（列出疑问并给出你的理解）

5. 自测要点（5 条，用于检验掌握程度）"""

    resp = llm.invoke([HumanMessage(content=prompt)])

    notes = llm_content_to_str(resp.content)

    if len(notes) > notes_max_chars:

        notes = notes[:notes_max_chars] + "\n\n…（笔记已达长度上限，部分细节未记录）"

    return notes


def student_study(state: LearnLoopState) -> dict:

    weak = state.get("weak_topics") or []

    settings = get_settings()

    macro = state.get("macro_iter", 0)
    curriculum_level = state.get("curriculum_level", 0)
    raw_chunks = state.get("raw_chunks") or []

    study_ctx = build_study_context(
        raw_chunks=raw_chunks,
        study_material=state.get("study_material") or "",
        curriculum_level=curriculum_level,
        pages_per_round=settings.curriculum_pages_per_round,
        max_chars=settings.student_material_study_max_chars,
    )

    try:

        notes = _study_llm(
            study_ctx,
            weak,
            notes_max_chars=settings.student_notes_study_max_chars,
            macro_iter=macro,
            curriculum_level=curriculum_level,
            pages_per_round=settings.curriculum_pages_per_round,
        )

        task_id = state.get("task_id", "default")

        out = ensure_output_dir(task_id)

        (out / f"study_notes_iter_{macro}.md").write_text(notes, encoding="utf-8")

        return {"study_notes": notes, "phase": "prepare_exam"}

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
    curriculum_level: int,
) -> str:

    settings = get_settings()

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

只补充有依据的内容，不可臆造。当前课程窗口：{curriculum_page_range_label(curriculum_level, settings.curriculum_pages_per_round)}。



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

    curriculum_level = state.get("curriculum_level", 0)

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

    try:

        updated = _refine_material_llm(
            material, weak, report, new_context, macro, curriculum_level
        )

        task_id = state.get("task_id", "default")

        out = ensure_output_dir(task_id)

        (out / f"study_material_iter_{macro + 1}.md").write_text(
            updated, encoding="utf-8"
        )

        logger.info(
            "refine_material macro=%s curriculum_level=%s advanced=%s new_chunks=%d",
            macro,
            curriculum_level,
            advanced,
            len(delta),
        )

        return {
            "study_material": updated,
            "macro_iter": 1,
            "curriculum_advanced": False,
            "phase": "student_study",
        }

    except Exception as exc:

        logger.exception("refine_material failed")

        return {"status": "failed", "error_message": str(exc)}
