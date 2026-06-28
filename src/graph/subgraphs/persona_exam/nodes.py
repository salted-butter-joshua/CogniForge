"""PersonaExam subgraph nodes — RAG, search, fuse, validate loop."""

from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END

from src.config import get_settings, load_loop_config
from src.graph.subgraphs.persona_exam.state import PersonaExamState, QuestionDraft
from src.models.llm_factory import persona_llm
from src.tools.json_utils import extract_json, llm_retry
from src.tools.learning_policy import (
    curriculum_page_range_label,
    diversity_validation_errors,
    exam_difficulty_hint,
)
from src.tools.rag import retrieve_chunks, search_corpus, valid_evidence_refs

logger = logging.getLogger(__name__)
loop_cfg = load_loop_config()
MAX_VALIDATE = loop_cfg.get("exam", {}).get("max_validate_rounds", 3)


def inject_snapshot(state: PersonaExamState) -> dict:
    """Ensure defaults for per-invocation subgraph state."""
    return {
        "validate_round": state.get("validate_round", 0),
        "max_validate_rounds": state.get("max_validate_rounds", MAX_VALIDATE),
        "retrieved_chunks": [],
        "search_queries": [],
        "search_results": [],
        "draft_questions": [],
        "validation_errors": [],
        "validation_passed": False,
        "final_questions": [],
    }


def rag_retrieve(state: PersonaExamState) -> dict:
    chunks = state.get("chunks_snapshot") or []
    weak = state.get("weak_topics_snapshot") or []
    style = state.get("persona_style") or ""
    level = state.get("curriculum_level_snapshot") or 0
    top_k = 8 + min(level, 4) * 2
    retrieved = retrieve_chunks(chunks, weak, style, top_k=top_k)
    return {"retrieved_chunks": retrieved}


@llm_retry()
def _plan_search_queries(state: PersonaExamState) -> list[str]:
    llm = persona_llm()
    weak = ", ".join(state.get("weak_topics_snapshot") or []) or "无"
    prompt = f"""你是搜索策划助手。根据出题角色与薄弱点，生成 2-3 个搜索查询词（用于检索相关知识）。
角色：{state.get('persona_name')}（{state.get('persona_style')})
薄弱点：{weak}

输出 JSON 数组，例如：["query1", "query2"]"""
    resp = llm.invoke([HumanMessage(content=prompt)])
    data = extract_json(resp.content)
    if isinstance(data, dict):
        data = data.get("queries", [])
    return [str(q) for q in data][:3]


def web_search(state: PersonaExamState) -> dict:
    """Supplement knowledge via corpus search (private search_results)."""
    try:
        queries = _plan_search_queries(state)
        chunks = state.get("chunks_snapshot") or []
        results = search_corpus(chunks, queries)
        return {"search_queries": queries, "search_results": results}
    except Exception as exc:
        logger.debug("web_search fallback: %s", exc)
        return {"search_queries": [], "search_results": []}


def _format_chunks_for_prompt(chunks: list[dict], max_chars: int = 6000) -> str:
    parts: list[str] = []
    total = 0
    for c in chunks:
        block = f"[{c.get('id')}] {c.get('title', '')}\n{c.get('content', '')}\n"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)
    return "\n---\n".join(parts)


@llm_retry()
def _fuse_questions_llm(state: PersonaExamState) -> list[dict]:
    llm = persona_llm()
    count = state.get("questions_target", 10)
    weak = state.get("weak_topics_snapshot") or []
    difficulty = state.get("difficulty_level_snapshot") or 0
    curriculum_level = state.get("curriculum_level_snapshot") or 0
    diff_hint = exam_difficulty_hint(difficulty)
    weak_hint = ""
    if weak and difficulty >= 1:
        weak_hint = (
            f"本轮聚焦薄弱点：{', '.join(weak)}。"
            f"约一半题目围绕这些主题，难度等级 {difficulty}。"
        )
    range_hint = ""
    if curriculum_level >= 0:
        ppr = get_settings().curriculum_pages_per_round
        range_hint = f"出题范围仅限：{curriculum_page_range_label(curriculum_level, ppr)}。"

    focus = state.get("focus_hint") or ""
    focus_hint_text = (
        f"本角色的出题重点章节：{focus}。请优先围绕这些章节命题，"
        f"尽量与其他出题角色错开，不要和别人重复同一个最基础的概念题。"
        if focus
        else ""
    )

    rag_ctx = _format_chunks_for_prompt(state.get("retrieved_chunks") or [])
    search_ctx = json.dumps(state.get("search_results") or [], ensure_ascii=False)[:4000]
    errors = state.get("validation_errors") or []
    error_hint = ""
    if errors:
        error_hint = f"上次自检失败原因（请修正）：\n" + "\n".join(f"- {e}" for e in errors)

    prompt = f"""你扮演「{state.get('persona_name')}」（{state.get('persona_style')}）。
{state.get('persona_prompt_hint')}
{range_hint}
{focus_hint_text}
{diff_hint}
{weak_hint}
{error_hint}

学习资料（只读快照，出题勿超出已解锁范围）：
{(state.get('material_snapshot') or '')[:6000]}

RAG 检索证据（优先从不同 chunk 出题，避免全部引用同一 chunk）：
{rag_ctx}

搜索补充结果（私有，可融合出题）：
{search_ctx}

请出 {count} 道题。输出 JSON 数组：
[
  {{
    "question": "题目",
    "evidence_refs": ["chunk_id"],
    "topic_tag": "主题",
    "weak_topic_focus": ""
  }}
]"""
    resp = llm.invoke(
        [
            SystemMessage(content="题目必须有 evidence_refs，且引用 ID 必须来自 RAG/资料。"),
            HumanMessage(content=prompt),
        ]
    )
    data = extract_json(resp.content)
    if isinstance(data, dict):
        data = data.get("questions", data.get("results", []))
    if not isinstance(data, list):
        data = [data] if data else []
    return data[:count]


def fuse_questions(state: PersonaExamState) -> dict:
    try:
        raw = _fuse_questions_llm(state)
        drafts: list[QuestionDraft] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            drafts.append(
                QuestionDraft(
                    question=item.get("question", ""),
                    evidence_refs=item.get("evidence_refs", []),
                    topic_tag=item.get("topic_tag", ""),
                    weak_topic_focus=item.get("weak_topic_focus", ""),
                    persona_id=state.get("persona_id", ""),
                    persona_name=state.get("persona_name", ""),
                )
            )
        return {"draft_questions": drafts}
    except Exception as exc:
        logger.exception("fuse_questions failed")
        return {"draft_questions": [], "validation_errors": [str(exc)]}


def validate_questions(state: PersonaExamState) -> dict:
    chunks = state.get("chunks_snapshot") or []
    drafts = state.get("draft_questions") or []
    target = state.get("questions_target", 10)
    difficulty = state.get("difficulty_level_snapshot") or 0
    errors: list[str] = []

    if len(drafts) < max(1, target // 2):
        errors.append(f"题目数量不足：{len(drafts)}/{target}")

    min_unique = 3 + min(difficulty, 2)
    errors.extend(diversity_validation_errors(drafts, min_unique_refs=min_unique))

    seen_questions: set[str] = set()
    for i, q in enumerate(drafts):
        text = (q.get("question") or "").strip()
        if not text:
            errors.append(f"第 {i + 1} 题为空")
            continue
        if text in seen_questions:
            errors.append(f"第 {i + 1} 题与前面重复")
        seen_questions.add(text)
        refs = q.get("evidence_refs") or []
        if not valid_evidence_refs(refs, chunks):
            if chunks:
                q["evidence_refs"] = [chunks[0].get("id", "")]
            else:
                errors.append(f"第 {i + 1} 题 evidence_refs 无效且无可用 chunk")

    passed = len(errors) == 0
    round_num = (state.get("validate_round") or 0) + 1
    return {
        "validation_errors": errors,
        "validation_passed": passed,
        "validate_round": round_num,
    }


def finalize_questions(state: PersonaExamState) -> dict:
    drafts = state.get("draft_questions") or []
    return {"final_questions": drafts}


def validate_router(state: PersonaExamState) -> str:
    if state.get("persona_status") == "failed":
        return END
    if state.get("validation_passed"):
        return "finalize_questions"
    if (state.get("validate_round") or 0) >= (state.get("max_validate_rounds") or MAX_VALIDATE):
        logger.debug(
            "persona=%s | validation max rounds reached, using best-effort drafts",
            state.get("persona_id"),
        )
        return "finalize_questions"
    return "fuse_questions"
