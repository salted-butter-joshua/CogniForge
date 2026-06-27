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
    curriculum_level: int,
    pages_per_round: int,
) -> list[dict]:
    """Cumulative unlock: levels 0..N map to pages 1..(level+1)*pages_per_round."""
    filtered = filter_content_chunks(chunks)
    if not filtered or pages_per_round <= 0:
        return filtered

    by_url: dict[str, list[dict]] = {}
    for c in filtered:
        by_url.setdefault(c.get("url", ""), []).append(c)

    level = max(0, curriculum_level)
    unlocked_count = max(1, pages_per_round * (level + 1))
    urls = _url_order(filtered)[:unlocked_count]

    result: list[dict] = []
    for url in urls:
        result.extend(by_url.get(url, []))
    return result or filtered[: max(1, pages_per_round * 3)]


def max_curriculum_level(chunks: list[dict], pages_per_round: int) -> int:
    """Highest curriculum level before all handbook pages are unlocked."""
    urls = _url_order(filter_content_chunks(chunks))
    if not urls or pages_per_round <= 0:
        return 0
    if len(urls) <= pages_per_round:
        return 0
    return (len(urls) - 1) // pages_per_round


def curriculum_delta_chunks(
    chunks: list[dict],
    curriculum_level: int,
    pages_per_round: int,
) -> list[dict]:
    """Chunks from pages newly unlocked when advancing to curriculum_level + 1."""
    prev_urls = {
        c.get("url") for c in curriculum_chunks(chunks, curriculum_level, pages_per_round)
    }
    nxt = curriculum_chunks(chunks, curriculum_level + 1, pages_per_round)
    return [c for c in nxt if c.get("url") not in prev_urls]


def curriculum_page_range_label(curriculum_level: int, pages_per_round: int) -> str:
    """Human-readable page window for prompts."""
    level = max(0, curriculum_level)
    start = 1
    end = pages_per_round * (level + 1)
    if level == 0:
        return f"第 {start}–{end} 页（首段课程）"
    prev_end = pages_per_round * level
    return f"第 {start}–{prev_end} 页（已学）+ 第 {prev_end + 1}–{end} 页（本轮新解锁）"


def adjust_difficulty_level(
    current: int,
    accuracy: float,
    *,
    advance_threshold: float = 0.90,
    retreat_threshold: float = 0.50,
    max_level: int = 4,
) -> int:
    """Raise difficulty only after strong accuracy; lower when struggling."""
    level = max(0, min(max_level, int(current)))
    if accuracy >= advance_threshold:
        return min(level + 1, max_level)
    if accuracy < retreat_threshold:
        return max(level - 1, 0)
    return level


def maybe_advance_curriculum_level(
    current: int,
    accuracy: float,
    chunks: list[dict],
    pages_per_round: int,
    *,
    advance_threshold: float = 0.85,
) -> tuple[int, bool]:
    """Advance cumulative page window only when accuracy meets the bar."""
    level = max(0, int(current))
    cap = max_curriculum_level(chunks, pages_per_round)
    if level >= cap:
        return level, False
    if accuracy < advance_threshold:
        return level, False
    return min(level + 1, cap), True


def build_study_context(
    *,
    raw_chunks: list[dict],
    study_material: str,
    curriculum_level: int,
    pages_per_round: int,
    max_chars: int,
) -> str:
    """Align student-readable content with the cumulative unlocked curriculum window."""
    from src.tools.web_fetch import material_context

    unlocked = curriculum_chunks(raw_chunks, curriculum_level, pages_per_round)
    range_label = curriculum_page_range_label(curriculum_level, pages_per_round)
    chunk_budget = max(max_chars * 2 // 3, 1000)
    chunk_text = material_context(unlocked, max_chars=chunk_budget)
    material_budget = max(max_chars - len(chunk_text) - 200, 500)
    material_excerpt = (study_material or "").strip()[:material_budget]

    parts: list[str] = [
        f"【课程范围】{range_label}。请只学习此范围内内容，不要超前。",
    ]
    if material_excerpt:
        parts.append(f"## 已整理学习资料（与上述范围对应）\n{material_excerpt}")
    parts.append(f"## 本阶段已解锁原文\n{chunk_text}")
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        return text[: max_chars - 20] + "\n\n…（已达学习上下文上限）"
    return text


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


def exam_difficulty_hint(difficulty_level: int) -> str:
    """Adaptive exam difficulty (0=easiest .. 4=hardest), not tied to macro round."""
    level = max(0, min(4, int(difficulty_level)))
    hints = {
        0: (
            "难度：入门。60% 基础回忆，30% 理解说明，10% 简单应用。"
            "题目以单个 evidence chunk 为主，禁止跨章综合。"
        ),
        1: (
            "难度：基础。50% 回忆，35% 理解，15% 简单应用。"
            "仍以单 chunk 为主，最多 1 题可引用第二个 chunk。"
        ),
        2: (
            "难度：进阶。40% 回忆，35% 理解，25% 场景应用。"
            "约 2 道题需结合两个 evidence chunk。"
        ),
        3: (
            "难度：挑战。30% 回忆，35% 理解，35% 应用/排错。"
            "至少 3 道题跨多个 evidence chunk。"
        ),
        4: (
            "难度：综合。20% 回忆，30% 理解，50% 综合应用与边界条件。"
            "至少 4 道题必须串联多个 evidence_refs。"
        ),
    }
    return hints[level]


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


def format_observer_report(obs: dict) -> str:
    """Render observer record as Markdown (archival / human review only)."""
    if not obs:
        return ""

    sections: list[str] = []
    summary = obs.get("observer_summary", "")
    if summary:
        sections.append(f"**观察摘要**：{summary}")

    mapping = [
        ("learning_patterns", "学习规律"),
        ("knowledge_framework", "知识框架观察"),
        ("note_style_observations", "笔记风格与习惯"),
        ("recurring_blind_spots", "反复盲区"),
    ]
    for key, title in mapping:
        text = obs.get(key, "")
        if text:
            sections.append(f"**{title}**\n{text}")

    return "\n\n".join(sections)


def build_observer_qa_payload(qa_list: list[dict], *, max_items: int = 40) -> dict:
    """Summarize exam outcomes for optional observer context (not primary input)."""
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
