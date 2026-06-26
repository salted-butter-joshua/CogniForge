"""Learning realism: curriculum, evidence bundles, persona weights, judge helpers."""

from __future__ import annotations

import re

from src.config import load_personas

_PERSONA_WEIGHTS: dict[str, float] | None = None


def persona_weights() -> dict[str, float]:
    global _PERSONA_WEIGHTS
    if _PERSONA_WEIGHTS is None:
        weights: dict[str, float] = {}
        for p in load_personas():
            weights[p["id"]] = float(p.get("difficulty_weight", 1.0))
        _PERSONA_WEIGHTS = weights
    return _PERSONA_WEIGHTS


def _is_toc_chunk(content: str) -> bool:
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if len(lines) < 4:
        return False
    short_lines = sum(1 for ln in lines if len(ln) < 40)
    return short_lines / len(lines) > 0.65


def filter_content_chunks(chunks: list[dict]) -> list[dict]:
    """Drop thin navigation / TOC-like chunks."""
    kept: list[dict] = []
    for c in chunks:
        content = c.get("content", "") or ""
        if len(content) < 180 and content.count("\n") >= 3:
            continue
        if _is_toc_chunk(content):
            continue
        kept.append(c)
    return kept or list(chunks)


def _url_order(chunks: list[dict]) -> list[str]:
    seen: list[str] = []
    for c in chunks:
        url = c.get("url", "")
        if url and url not in seen:
            seen.append(url)
    return seen


def curriculum_chunks(
    chunks: list[dict],
    macro_iter: int,
    pages_per_round: int,
) -> list[dict]:
    """Progressively unlock handbook pages across macro iterations."""
    filtered = filter_content_chunks(chunks)
    if not filtered or pages_per_round <= 0:
        return filtered

    by_url: dict[str, list[dict]] = {}
    for c in filtered:
        by_url.setdefault(c.get("url", ""), []).append(c)

    unlocked_count = max(1, pages_per_round * (macro_iter + 1))
    urls = _url_order(filtered)[:unlocked_count]

    result: list[dict] = []
    for url in urls:
        result.extend(by_url.get(url, []))
    return result or filtered[: max(1, pages_per_round * 3)]


def curriculum_delta_chunks(
    chunks: list[dict],
    macro_iter: int,
    pages_per_round: int,
) -> list[dict]:
    """Chunks from pages newly unlocked at macro_iter + 1."""
    prev_urls = {c.get("url") for c in curriculum_chunks(chunks, macro_iter, pages_per_round)}
    nxt = curriculum_chunks(chunks, macro_iter + 1, pages_per_round)
    return [c for c in nxt if c.get("url") not in prev_urls]


def chunks_by_ids(chunks: list[dict], ids: list[str]) -> list[dict]:
    id_set = set(ids)
    return [c for c in chunks if c.get("id") in id_set]


def format_evidence_context(
    chunks: list[dict],
    evidence_ids: list[str],
    *,
    max_chars: int = 8000,
) -> str:
    """Build judge-visible context: only cited evidence chunks."""
    selected = chunks_by_ids(chunks, evidence_ids)
    if not selected:
        return "（无有效 evidence_refs，仅根据答案是否承认不知道评分）"

    parts: list[str] = []
    total = 0
    for c in selected:
        block = f"[{c.get('id')}] ({c.get('title', '')})\n{c.get('content', '')}\n"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)
    return "\n---\n".join(parts)


def format_batch_evidence_context(
    chunks: list[dict],
    qa_batch: list[dict],
    *,
    max_chars: int = 12000,
) -> str:
    """Union of all evidence_refs in a judge batch."""
    ids: list[str] = []
    seen: set[str] = set()
    for qa in qa_batch:
        for ref in qa.get("evidence_refs") or []:
            if ref and ref not in seen:
                seen.add(ref)
                ids.append(ref)
    return format_evidence_context(chunks, ids, max_chars=max_chars)


def exam_difficulty_hint(macro_iter: int) -> str:
    if macro_iter <= 0:
        return (
            "难度分布：40% 基础回忆，40% 理解说明，20% 简单应用。"
            "禁止出需要跨多章综合的压轴题。"
        )
    if macro_iter == 1:
        return (
            "难度分布：25% 回忆，35% 理解，40% 场景应用/排错。"
            "至少 3 道题要求结合两个以上 evidence chunk。"
        )
    return (
        "难度分布：15% 回忆，30% 理解，55% 综合应用、边界条件、排错推演。"
        "至少 5 道题必须串联多个 evidence_refs；禁止纯术语定义题。"
    )


def diversity_validation_errors(
    drafts: list[dict],
    *,
    min_unique_refs: int,
) -> list[str]:
    errors: list[str] = []
    refs: list[str] = []
    for q in drafts:
        refs.extend(q.get("evidence_refs") or [])
    unique = len(set(refs))
    if unique < min_unique_refs:
        errors.append(
            f"evidence 覆盖不足：{unique} 个不同 chunk，要求至少 {min_unique_refs} 个"
        )
    return errors


def weighted_accuracy(scored: list[dict]) -> float:
    weights = persona_weights()
    num = 0.0
    den = 0.0
    for q in scored:
        w = weights.get(q.get("persona_id", ""), 1.0)
        den += w
        if q.get("is_correct"):
            num += w
    return num / den if den else 0.0


def _answer_terms(text: str) -> set[str]:
    return {t for t in re.findall(r"[\w\u4e00-\u9fff]{3,}", text.lower()) if len(t) > 2}


def apply_evidence_cap(
    answer: str,
    evidence_text: str,
    score: float,
    *,
    cap: float = 0.78,
) -> tuple[float, str]:
    """Penalize answers that introduce many terms absent from evidence."""
    if score < cap or not answer.strip():
        return score, ""
    if any(k in answer for k in ("不知道", "不确定", "记不清", "没学过")):
        return score, ""

    ans_terms = _answer_terms(answer)
    ev_terms = _answer_terms(evidence_text)
    if not ans_terms:
        return score, ""

    novel = ans_terms - ev_terms
    ratio = len(novel) / max(len(ans_terms), 1)
    if ratio > 0.45 and len(novel) >= 6:
        return min(score, cap), f"evidence_cap: 答案含 {len(novel)} 个证据外术语"
    return score, ""


def format_mentor_feedback(obs: dict) -> str:
    """Render mentor record for student study prompt (supports legacy fields)."""
    if not obs:
        return ""

    sections: list[str] = []
    summary = obs.get("mentor_summary", "")
    if summary:
        sections.append(f"**导师寄语**：{summary}")

    mapping = [
        ("performance_diagnosis", "答题诊断"),
        ("habit_corrections", "需纠正的习惯/错误想法"),
        ("methodology_advice", "学习方法建议"),
        ("study_plan", "下轮学习规划"),
    ]
    for key, title in mapping:
        text = obs.get(key, "")
        if text:
            sections.append(f"**{title}**\n{text}")

    if sections:
        return "\n\n".join(sections)

    legacy = [
        ("learning_patterns", "学习规律"),
        ("knowledge_framework", "知识框架"),
        ("answer_style_notes", "答题风格"),
        ("improvement_suggestions", "改进建议"),
    ]
    for key, title in legacy:
        text = obs.get(key, "")
        if text:
            sections.append(f"**{title}**\n{text}")
    return "\n\n".join(sections)


def build_observer_qa_payload(qa_list: list[dict], *, max_items: int = 40) -> dict:
    """Prioritize wrong answers and include judge reasons for mentor diagnosis."""
    wrong = [q for q in qa_list if not q.get("is_correct")]
    correct = [q for q in qa_list if q.get("is_correct")]
    sample = (wrong[: max_items // 2 + 10] + correct[: max_items // 2])[:max_items]

    items = [
        {
            "persona": q.get("persona_name"),
            "question": q.get("question"),
            "answer": q.get("answer"),
            "score": q.get("judge_score"),
            "is_correct": q.get("is_correct"),
            "topic": q.get("topic_tag"),
            "judge_reason": q.get("judge_reason", ""),
        }
        for q in sample
    ]
    return {
        "total": len(qa_list),
        "wrong_count": len(wrong),
        "sample": items,
    }
