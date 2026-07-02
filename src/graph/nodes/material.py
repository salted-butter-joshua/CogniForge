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
    cap_study_notes,
    chapter_label,
    chapter_material_char_basis,
    chunks_for_chapter,
    compute_study_context_budget,
    compute_study_notes_budget,
    current_chapter,
    curriculum_chunks,
    curriculum_delta_chunks,
    curriculum_page_range_label,
    effective_study_notes_ratio,
    format_wrong_qa_feedback,
    guard_incremental_notes,
    init_chapter_mastery_dict,
    is_chapter_mastery_mode,
    sanitize_prior_study_notes,
    study_notes_output_paths,
    upsert_chapter_long_term_block,
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



def _study_notes_structure_hint() -> str:
    return """记忆分层要求（必须按此结构输出 Markdown）：
1. **## 知识框架** 与 **## 核心概念与要点** — 完整、详尽，用于学习过程与最终归档（闭卷时不可全文查阅）
2. **## 机制与边界条件** — 写清「什么情况下成立 / 不成立」、触发条件、默认行为 vs 需手动开启的行为（避免模糊词如「会自动提示」而不说明拒绝/报错）
3. **## 薄弱点强化梳理**、**## 待澄清 / 易混淆点** — 含易错机制（如：冲突≠管理不同字段；SSA 默认拒绝 apply 而非仅警告）
4. **## 自测要点** — 5 条检验题，含 1–2 道「边界/否定案例」题
5. 可选 **## 关键术语速查** — 术语对照表

准确性要求：
- 用自己的话组织，但**机制描述必须与资料一致**；不确定处写入「待澄清」，不要编造看似合理的因果
- 不要大段照抄原文或完整 YAML/配置
- 可适度外延（对比、类比、操作后果），但**不得引入资料未支持的新机制或错误边界**"""


@llm_retry()
def _study_llm_initial(
    material: str,
    weak_topics: list[str],
    *,
    notes_max_chars: int,
    notes_target_chars: int,
    material_chars: int,
    macro_iter: int,
    scope_label: str,
    wrong_feedback: str = "",
) -> str:
    """First study round for a chapter — create notes from scratch."""
    llm = student_llm()
    weak_text = ", ".join(weak_topics) if weak_topics else "无"
    ratio = effective_study_notes_ratio()
    wrong_section = f"\n{wrong_feedback.strip()}\n" if wrong_feedback.strip() else ""

    prompt = f"""你是认真严谨的学习者 A。请在充分理解以下资料的基础上，整理一份清晰、专业且易懂的学习笔记。

{_study_notes_structure_hint()}

篇幅要求（重要）：
- 本次学习资料约 {material_chars} 字；笔记目标篇幅约 **{notes_target_chars} 字**（约为资料的 {ratio:.2f} 倍，允许 1.5–2.0 倍外延展开）
- 上限 {notes_max_chars} 字；**不要写短笔记**，核心概念需充分展开（机制、对比、反例、操作后果）
- 宁可写满目标篇幅，也不要只写摘要式 bullet

其他：
- 当前为第 {macro_iter + 1} 轮学习，**本章首次整理笔记**（从零撰写，勿引用不存在的「上轮笔记」）
- {scope_label}；只学本窗口内容

薄弱点（需重点强化）：{weak_text}
{wrong_section}
学习资料（与课程解锁窗口对齐，约 {material_chars} 字）：

{material}

输出 Markdown，必须包含：知识框架、核心概念与要点、机制与边界条件、薄弱点强化梳理、待澄清/易混淆点、自测要点（恰好 5 条）"""

    resp = llm.invoke([HumanMessage(content=prompt)])
    return cap_study_notes(llm_content_to_str(resp.content), notes_max_chars)


@llm_retry()
def _study_llm_revise(
    material: str,
    weak_topics: list[str],
    *,
    prior_notes: str,
    notes_max_chars: int,
    notes_target_chars: int,
    material_chars: int,
    macro_iter: int,
    scope_label: str,
    wrong_feedback: str = "",
) -> str:
    """Same-chapter follow-up — revise and extend prior notes, do not rewrite from scratch."""
    llm = student_llm()
    weak_text = ", ".join(weak_topics) if weak_topics else "无"
    ratio = effective_study_notes_ratio()
    prior_body = sanitize_prior_study_notes(prior_notes)
    prior_len = len(prior_body)
    wrong_section = f"\n{wrong_feedback.strip()}\n" if wrong_feedback.strip() else ""

    prompt = f"""你是认真严谨的学习者 A。你正在**同一章节的多轮学习**中维护一份工作笔记。

## 任务（增量修订，禁止整篇重写）
- **必须**在下方「当前章节笔记（完整）」基础上修订：保留已有正确内容，仅修正错误、补充遗漏、强化薄弱点与边界条件
- **禁止**清空结构、缩写成摘要、或另起炉灶重写
- 输出必须是**合并后的完整笔记**（含所有章节标题），不是 diff、不是变更说明
- 篇幅应 **≥ {prior_len} 字**，目标 **{notes_target_chars} 字**，上限 **{notes_max_chars} 字**
- 资料约 {material_chars} 字；笔记相对资料约 {ratio:.2f} 倍，可适度外延对比/后果，但不得捏造机制

{_study_notes_structure_hint()}

修订重点：
- 对照学习资料与上轮错题，修正机制/边界描述错误
- 在「机制与边界条件」「待澄清/易混淆点」「自测要点」中补充否定案例与触发条件
- 若某节已完整且无误，**原样保留**，不要为改而改

当前为第 {macro_iter + 1} 轮学习 · {scope_label}（仍为同一章，勿切换到其他章内容）
薄弱点（需重点强化）：{weak_text}
{wrong_section}
## 当前章节笔记（完整，请在此基础上修订）
{prior_body}

## 学习资料（约 {material_chars} 字，用于核对与补漏）
{material}

输出合并后的完整 Markdown 笔记（保留上述结构，总长不超过 {notes_max_chars} 字）。"""

    resp = llm.invoke([HumanMessage(content=prompt)])
    revised = llm_content_to_str(resp.content).strip()
    return guard_incremental_notes(
        prior_body,
        revised,
        notes_max_chars=notes_max_chars,
    )


def _study_llm(
    material: str,
    weak_topics: list[str],
    *,
    notes_max_chars: int,
    notes_target_chars: int,
    material_chars: int,
    macro_iter: int,
    scope_label: str,
    prior_notes: str = "",
    wrong_feedback: str = "",
) -> str:
    if prior_notes.strip():
        return _study_llm_revise(
            material,
            weak_topics,
            prior_notes=prior_notes,
            notes_max_chars=notes_max_chars,
            notes_target_chars=notes_target_chars,
            material_chars=material_chars,
            macro_iter=macro_iter,
            scope_label=scope_label,
            wrong_feedback=wrong_feedback,
        )
    return _study_llm_initial(
        material,
        weak_topics,
        notes_max_chars=notes_max_chars,
        notes_target_chars=notes_target_chars,
        material_chars=material_chars,
        macro_iter=macro_iter,
        scope_label=scope_label,
        wrong_feedback=wrong_feedback,
    )


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
        ch = current_chapter(registry, idx)
        material_basis = chapter_material_char_basis(
            state.get("study_material") or "",
            raw_chunks,
            (ch or {}).get("chapter_id", ""),
        )
        study_window = compute_study_context_budget(
            material_basis,
            len(prior),
            floor=settings.student_material_study_max_chars,
        )
        study_ctx = build_chapter_study_context(
            raw_chunks=raw_chunks,
            chapter_registry=registry,
            current_chapter_index=idx,
            study_material=state.get("study_material") or "",
            long_term_notes=state.get("long_term_notes") or "",
            short_term_notes=prior,
            max_chars=study_window,
        )
        notes_max, notes_target = compute_study_notes_budget(
            material_basis,
            prior_chars=len(prior),
        )
    else:
        curriculum_level = state.get("curriculum_level", 0)
        scope_label = curriculum_page_range_label(
            curriculum_level, settings.curriculum_pages_per_round
        )
        prior = state.get("study_notes") or ""
        unlocked = curriculum_chunks(
            raw_chunks, curriculum_level, settings.curriculum_pages_per_round
        )
        material_basis = max(
            len((state.get("study_material") or "").strip()),
            len(material_context(unlocked, max_chars=500_000).strip()),
            500,
        )
        study_window = compute_study_context_budget(
            material_basis,
            len(prior),
            floor=settings.student_material_study_max_chars,
        )
        study_ctx = build_study_context(
            raw_chunks=raw_chunks,
            study_material=state.get("study_material") or "",
            curriculum_level=curriculum_level,
            pages_per_round=settings.curriculum_pages_per_round,
            max_chars=study_window,
            prior_notes=prior,
        )
        notes_max, notes_target = compute_study_notes_budget(
            material_basis,
            prior_chars=len(prior),
        )

    try:

        wrong_feedback = format_wrong_qa_feedback(
            list(state.get("current_batch_qa") or []),
            max_items=8,
        )

        study_mode = "revise" if prior.strip() else "initial"
        notes = _study_llm(
            study_ctx,
            weak,
            notes_max_chars=notes_max,
            notes_target_chars=notes_target,
            material_chars=len(study_ctx),
            macro_iter=macro,
            scope_label=scope_label,
            prior_notes=prior,
            wrong_feedback=wrong_feedback,
        )

        task_id = state.get("task_id", "default")

        out = ensure_output_dir(task_id)

        chapter_id = None
        if is_chapter_mastery_mode():
            registry = state.get("chapter_registry") or []
            idx = int(state.get("current_chapter_index", 0) or 0)
            ch = current_chapter(registry, idx)
            chapter_id = (ch or {}).get("chapter_id")

        notes_path, meta_path = study_notes_output_paths(out, chapter_id=chapter_id)
        notes_path.write_text(notes, encoding="utf-8")
        meta_path.write_text(
            json.dumps(
                {
                    "macro_iter": macro,
                    "study_mode": study_mode,
                    "chapter_id": chapter_id,
                    "prior_notes_chars": len(prior),
                    "material_basis_chars": material_basis,
                    "study_window_chars": study_window,
                    "material_chars": len(study_ctx),
                    "notes_chars": len(notes),
                    "notes_target_chars": notes_target,
                    "notes_max_chars": notes_max,
                    "ratio_actual": round(len(notes) / max(len(study_ctx), 1), 3),
                    "study_notes_ratio": effective_study_notes_ratio(),
                    "notes_path": notes_path.name,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        result = {
            "study_notes": notes,
            "phase": "prepare_exam",
        }
        if is_chapter_mastery_mode():
            result["short_term_notes"] = notes
            registry = state.get("chapter_registry") or []
            idx = int(state.get("current_chapter_index", 0) or 0)
            ch = current_chapter(registry, idx)
            # Long-term memory is written only after chapter mastery (consolidate),
            # not each study round — avoids duplicating short_term in context & state.
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
    lt_enabled = int(settings.long_term_notes_max_chars) > 0

    try:
        if short_notes.strip():
            archive = append_chapter_archive(
                archive,
                ch,
                short_notes,
                macro_iter=macro,
            )
            if lt_enabled:
                summary = _consolidate_notes_llm(
                    ch.get("chapter_title", ""),
                    short_notes,
                    per_chapter_budget,
                )
                long_term = upsert_chapter_long_term_block(
                    long_term,
                    ch.get("chapter_title", ""),
                    summary,
                    total_max_chars=settings.long_term_notes_max_chars,
                )
            else:
                summary = ""
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
            "topic_reinforce_streaks": {},
            "graduated_topic_tags": [],
            "current_chapter_index": new_index,
            "regenerate_material": regenerate,
            "chapter_advanced": False,
            "phase": "observer_analyze",
        }
    except Exception as exc:
        logger.exception("consolidate_chapter_notes failed")
        return {"status": "failed", "error_message": str(exc)}
