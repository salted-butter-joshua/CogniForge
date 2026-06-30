"""Learning realism: curriculum, evidence bundles, persona weights, judge helpers."""

from __future__ import annotations

import re

from src.config import get_settings, load_personas

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
    semantic_lenient: bool = False,
) -> tuple[float, str]:
    """Penalize answers that introduce many terms absent from evidence."""
    # Lexical term overlap contradicts semantic judging — skip when lenient mode is on.
    if semantic_lenient:
        return score, ""
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
    novel_threshold = 0.58 if semantic_lenient else 0.45
    min_novel = 10 if semantic_lenient else 6
    if ratio > novel_threshold and len(novel) >= min_novel:
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


# ---------------------------------------------------------------------------
# Chapter mastery mode + memory helpers (P0–P3)
# ---------------------------------------------------------------------------


def is_chapter_mastery_mode() -> bool:
    return get_settings().learning_mode.strip().lower() == "chapter_mastery"


def init_chapter_mastery_dict(registry: list[dict]) -> dict[str, dict]:
    mastery: dict[str, dict] = {}
    for ch in registry:
        cid = ch.get("chapter_id", "")
        if not cid:
            continue
        mastery[cid] = {
            "chapter_id": cid,
            "chapter_title": ch.get("chapter_title", ""),
            "accuracy": 0.0,
            "best_accuracy": 0.0,
            "attempts": 0,
            "mastered": False,
            "mastered_at_iter": -1,
            "weak_subtopics": [],
        }
    return mastery


def current_chapter(registry: list[dict], index: int) -> dict | None:
    if not registry or index < 0 or index >= len(registry):
        return None
    return registry[index]


def chunks_for_chapter(chunks: list[dict], chapter_id: str) -> list[dict]:
    return [c for c in chunks if c.get("chapter_id") == chapter_id]


def chunks_for_exam(
    chunks: list[dict],
    registry: list[dict],
    chapter_index: int,
    chapter_mastery: dict[str, dict],
    *,
    review_ratio: float = 0.1,
    chapter_mastery_mode: bool = False,
) -> list[dict]:
    """Exam chunk scope aligned with study scope.

    In chapter mastery mode: only current-chapter primary chunks (no cross-chapter
    review) until the design explicitly enables review after mastery.
    """
    ch = current_chapter(registry, chapter_index)
    if not ch:
        return filter_content_chunks(chunks)
    primary = chunks_for_chapter(chunks, ch["chapter_id"])
    if chapter_mastery_mode:
        return primary or filter_content_chunks(chunks)

    if review_ratio <= 0:
        return primary or filter_content_chunks(chunks)

    mastered_ids = [
        cid
        for cid, m in chapter_mastery.items()
        if m.get("mastered") and cid != ch.get("chapter_id")
    ]
    if not mastered_ids:
        return primary

    review_cap = max(1, int(len(primary) * review_ratio)) if primary else 1
    review: list[dict] = []
    for cid in mastered_ids:
        review.extend(chunks_for_chapter(chunks, cid)[:1])
        if len(review) >= review_cap:
            break
    return primary + review


def _terms_in_text(terms: set[str], text: str) -> int:
    text_l = text.lower()
    return sum(1 for t in terms if len(t) >= 2 and t.lower() in text_l)


def study_aligned_chunk_ids(
    chunks: list[dict],
    chapter_id: str,
    *,
    study_material: str = "",
    short_term_notes: str = "",
    knowledge_cards: list[dict] | None = None,
) -> set[str]:
    """Chunk IDs plausibly covered in this round's study (P1 exam alignment)."""
    chapter_chunks = chunks_for_chapter(chunks, chapter_id)
    if not chapter_chunks:
        return set()

    material = (study_material or "").strip()
    notes = (short_term_notes or "").strip()
    combined = f"{material}\n{notes}"
    allowed: set[str] = set()

    for c in chapter_chunks:
        cid = c.get("id", "")
        if not cid:
            continue
        if cid in combined:
            allowed.add(cid)
            continue
        heading = (c.get("heading") or c.get("title") or "").strip()
        if len(heading) >= 2 and heading in combined:
            allowed.add(cid)
            continue
        content_terms = _answer_terms((c.get("content") or "")[:400])
        if notes and content_terms and _terms_in_text(content_terms, notes) >= 2:
            allowed.add(cid)

    for card in knowledge_cards or []:
        ref = (card.get("source_ref") or "").strip()
        if ref:
            allowed.add(ref)

    if not allowed:
        return {c.get("id") for c in chapter_chunks if c.get("id")}
    return allowed


def filter_chunks_by_ids(chunks: list[dict], allowed_ids: set[str]) -> list[dict]:
    if not allowed_ids:
        return chunks
    filtered = [c for c in chunks if c.get("id") in allowed_ids]
    return filtered or chunks


def reinforce_pool_cap(
    new_question_count: int,
    *,
    macro_iter: int,
    chapter_attempts: int,
    ratio: float | None = None,
) -> int:
    """How many reinforce (wrong-question retry) items to inject this batch."""
    settings = get_settings()
    base = ratio if ratio is not None else settings.reinforce_pool_ratio
    if chapter_attempts <= 2 or macro_iter <= 1:
        effective = min(0.65, base + 0.15)
    elif chapter_attempts <= 4:
        effective = base
    else:
        effective = max(0.3, base - 0.05)
    return max(1, int(new_question_count * effective))


def chapter_label(registry: list[dict], index: int) -> str:
    ch = current_chapter(registry, index)
    if not ch:
        return "（无章节）"
    total = len(registry)
    return f"第 {index + 1}/{total} 章：{ch.get('chapter_title', '')}"


def _split_markdown_sections(text: str) -> list[str]:
    parts = re.split(r"(?=^#{1,4}\s)", text.strip(), flags=re.MULTILINE)
    return [p.strip() for p in parts if p.strip()]


# Shallow cues at closed-book exam (NOT full exposition — that lives in long-term).
WORKING_EXAM_SECTION_HINTS: tuple[str, ...] = (
    "自测",
    "易错",
    "易混淆",
    "待澄清",
    "薄弱",
    "口诀",
    "对比",
    "参考层",
)

# Internalized knowledge — synced into long_term_notes each study round.
CORE_MEMORY_SECTION_HINTS: tuple[str, ...] = (
    "知识框架",
    "核心概念",
    "关键术语",
)


def extract_core_memory_layer(notes: str, max_chars: int) -> str:
    """Extract internalized core (framework + concepts) for closed-book long-term memory."""
    notes = (notes or "").strip()
    if not notes or max_chars <= 0:
        return ""

    sections = _split_markdown_sections(notes)
    picked: list[str] = []
    for sec in sections:
        header = sec.split("\n", 1)[0].lower()
        if any(hint in header for hint in CORE_MEMORY_SECTION_HINTS):
            picked.append(sec)

    if not picked:
        return ""

    return _truncate_sections("\n\n".join(picked), max_chars)


def _replace_chapter_block(long_term: str, chapter_title: str, new_block: str) -> str:
    """Replace or append a ## chapter_title section in long-term notes."""
    title = (chapter_title or "").strip()
    if not title:
        return (long_term + "\n\n" + new_block).strip() if new_block.strip() else long_term

    marker = f"## {title}"
    text = (long_term or "").strip()
    if not text:
        return new_block.strip()

    parts = re.split(r"(?=^##\s)", text, flags=re.MULTILINE)
    kept: list[str] = []
    replaced = False
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith(marker):
            if not replaced:
                kept.append(new_block.strip())
                replaced = True
            continue
        kept.append(part)
    if not replaced:
        kept.append(new_block.strip())
    return "\n\n".join(kept).strip()


def sync_chapter_long_term_notes(
    long_term_notes: str,
    short_term_notes: str,
    chapter_title: str,
    *,
    per_chapter_max_chars: int,
    total_max_chars: int,
) -> str:
    """After each study round, mirror note core into exam long-term memory (same chapter)."""
    core = extract_core_memory_layer(short_term_notes, per_chapter_max_chars)
    if not core.strip():
        return long_term_notes or ""
    return upsert_chapter_long_term_block(
        long_term_notes,
        chapter_title,
        core,
        total_max_chars=total_max_chars,
    )


def upsert_chapter_long_term_block(
    long_term_notes: str,
    chapter_title: str,
    body: str,
    *,
    total_max_chars: int,
) -> str:
    """Replace ## chapter section in long-term notes (study sync or mastery compress)."""
    if not body.strip():
        return long_term_notes or ""
    block = f"## {chapter_title}\n{body.strip()}"
    merged = _replace_chapter_block(long_term_notes or "", chapter_title, block)
    if len(merged) > total_max_chars:
        merged = _truncate_sections(merged, total_max_chars)
    return merged


def extract_working_exam_layer(notes: str, max_chars: int) -> str:
    """Extract shallow reference snippets from working notes — not the full manual."""
    notes = (notes or "").strip()
    if not notes or max_chars <= 0:
        return ""

    sections = _split_markdown_sections(notes)
    picked: list[str] = []
    for sec in sections:
        header = sec.split("\n", 1)[0].lower()
        if any(hint in header for hint in WORKING_EXAM_SECTION_HINTS):
            picked.append(sec)

    if not picked:
        # Fallback: bullet lists only (typically cues, not full exposition)
        bullets = [
            ln
            for ln in notes.splitlines()
            if ln.strip().startswith(("-", "*", "1.", "2."))
        ]
        if bullets:
            picked = ["\n".join(bullets[:12])]

    if not picked:
        return ""

    text = _truncate_sections("\n\n".join(picked), max_chars)
    return text


def append_chapter_archive(
    archive: list[dict],
    chapter: dict,
    full_notes: str,
    *,
    macro_iter: int,
) -> list[dict]:
    """Persist full chapter working notes for display / learning journal."""
    if not full_notes.strip():
        return list(archive)
    cid = chapter.get("chapter_id", "")
    entry = {
        "chapter_id": cid,
        "chapter_title": chapter.get("chapter_title", ""),
        "part_title": chapter.get("part_title", ""),
        "chapter_order": chapter.get("chapter_order", 0),
        "macro_iter": macro_iter,
        "full_notes": full_notes.strip(),
    }
    updated = [e for e in archive if e.get("chapter_id") != cid]
    updated.append(entry)
    updated.sort(key=lambda e: int(e.get("chapter_order") or 0))
    return updated


def build_learning_journal(
    archive: list[dict],
    *,
    goal: str = "",
    in_progress_chapter: dict | None = None,
    in_progress_notes: str = "",
) -> str:
    """Aggregate full study notes across chapters for human-readable output."""
    lines = ["# 学习全过程笔记", ""]
    if goal:
        lines.extend([f"> **学习目标**：{goal}", ""])
    lines.append(
        "> 说明：本文件为学习阶段的完整工作笔记归档；"
        "闭卷考试时仅使用「长期记忆摘要」+「工作记忆参考层（术语/易错/自测）」，"
        "不得查阅本文件全文。"
    )
    lines.append("")

    for entry in archive:
        title = entry.get("chapter_title") or entry.get("chapter_id") or "未命名章节"
        part = entry.get("part_title") or ""
        lines.append(f"## {title}")
        if part:
            lines.append(f"*{part}* · 已于第 {int(entry.get('macro_iter', 0)) + 1} 轮掌握")
        lines.append("")
        lines.append(entry.get("full_notes", ""))
        lines.append("")

    if in_progress_notes.strip() and in_progress_chapter:
        title = in_progress_chapter.get("chapter_title", "当前章节")
        part = in_progress_chapter.get("part_title", "")
        lines.append(f"## {title}（进行中）")
        if part:
            lines.append(f"*{part}*")
        lines.append("")
        lines.append(in_progress_notes.strip())
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _truncate_sections(text: str, max_chars: int) -> str:
    """Section-aware truncation: preserve headings, avoid head-only cut."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    sections = _split_markdown_sections(text)
    if len(sections) <= 1:
        head = max_chars * 2 // 3
        tail = max(max_chars - head - 24, 0)
        if tail <= 0:
            return text[:max_chars]
        return text[:head] + "\n\n…（中间省略）\n\n" + text[-tail:]

    kept: list[str] = []
    total = 0
    per = max(max_chars // len(sections), 120)
    for sec in sections:
        header = sec.split("\n", 1)[0]
        body = sec[len(header) :].strip()
        body_budget = max(per - len(header) - 2, 80)
        snippet = header
        if body:
            snippet += "\n" + (
                body if len(body) <= body_budget else body[: body_budget - 3] + "…"
            )
        if total + len(snippet) + 2 > max_chars:
            break
        kept.append(snippet)
        total += len(snippet) + 2
    if not kept:
        return text[:max_chars]
    return "\n\n".join(kept)


def select_exam_notes(
    *,
    notes: str = "",
    max_chars: int,
    long_term_notes: str = "",
    short_term_notes: str = "",
    chapter_title: str = "",
) -> str:
    """Closed-book memory bundle: deep (long-term) + shallow (working layer only).

    Full working notes and learning journal are NOT included — those are for
    study/archive only, matching human memory: internalized vs cheat-sheet cues.
    """
    settings = get_settings()
    # Body budget split; leave headroom for closed-book preamble (trimmed to max_chars).
    _sum_cap = 0.95
    lt_ratio = min(max(settings.exam_long_term_ratio, 0.0), 0.95)
    wl_ratio = min(max(settings.exam_working_layer_ratio, 0.0), 0.5)
    if lt_ratio + wl_ratio > _sum_cap:
        wl_ratio = max(0.0, _sum_cap - lt_ratio)

    lt_budget = int(max_chars * lt_ratio)
    wl_budget = int(max_chars * wl_ratio)
    parts: list[str] = []

    if long_term_notes.strip() and lt_budget > 120:
        chunk = _truncate_sections(long_term_notes.strip(), lt_budget)
        parts.append(f"【长期记忆·内化知识】\n{chunk}")

    if short_term_notes.strip() and wl_budget > 80:
        layer = extract_working_exam_layer(short_term_notes, wl_budget)
        if layer:
            label = (
                f"【工作记忆·参考层（术语/易错/自测，非完整笔记）·{chapter_title}】"
                if chapter_title
                else "【工作记忆·参考层（术语/易错/自测，非完整笔记）】"
            )
            parts.append(f"{label}\n{layer}")

    if not parts and is_chapter_mastery_mode():
        return (
            "（尚无可用记忆：请继续学习本章并整理笔记。"
            "闭卷时只能依赖已内化的长期记忆与少量参考层摘录。）"
        )

    if not parts and notes.strip():
        parts.append(_truncate_sections(notes.strip(), max_chars))

    preamble = (
        "【闭卷记忆规则】\n"
        "1. 「长期记忆」= 已内化、可回忆的核心概念（答题主要依据）\n"
        "2. 「工作记忆·参考层」= 术语/易错/自测等浅层线索（辅助，非完整笔记）\n"
        "3. 完整手抄笔记与原文不在考场上可用；记不清请说「不确定」"
    )
    body = "\n\n".join(parts).strip()
    text = f"{preamble}\n\n{body}".strip()
    if len(text) > max_chars:
        overflow = len(text) - max_chars
        if body and overflow > 0:
            trimmed_body = body[: max(len(body) - overflow - 3, 80)] + "…"
            text = f"{preamble}\n\n{trimmed_body}"
        else:
            text = text[: max_chars - 12] + "\n…（记忆截断）"
    return text or "（尚无笔记）"


def exam_notes_char_budget() -> int:
    """Total closed-book memory budget (NOT equal to full study notes)."""
    return get_settings().student_notes_max_chars


def format_wrong_qa_feedback(qa_list: list[dict], *, max_items: int = 8) -> str:
    """Summarize wrong answers from the last exam for targeted study."""
    wrong = [q for q in qa_list if not q.get("is_correct")]
    if not wrong:
        return ""
    lines = ["## 上轮错题（请在笔记中重点补强）"]
    for q in wrong[:max_items]:
        topic = q.get("topic_tag") or q.get("weak_topic_focus") or "未分类"
        reason = (q.get("judge_reason") or "").strip()[:120]
        lines.append(
            f"- **{topic}**：{q.get('question', '')[:160]}\n"
            f"  - 你的回答：{(q.get('answer') or '')[:120]}\n"
            f"  - 失分原因：{reason or '未记录'}"
        )
    if len(wrong) > max_items:
        lines.append(f"- …另有 {len(wrong) - max_items} 道错题")
    return "\n".join(lines)


_DUP_STOP = frozenset(
    "的了是在与和及对请吗呢以可并把被为之而其所这那有就都也很还要会能给出"
)


def _dup_tokens(text: str) -> set[str]:
    """Content tokens for near-duplicate / topic clustering (ASCII case-insensitive)."""
    text = text or ""
    cjk = {c for c in text if "一" <= c <= "鿿" and c not in _DUP_STOP}
    words = {w.lower() for w in re.findall(r"[a-zA-Z0-9]+", text) if len(w) > 1}
    return cjk | words


def question_content_fingerprint(text: str) -> str:
    """Stable fingerprint from question wording (case-insensitive for ASCII)."""
    import hashlib

    toks = sorted(_dup_tokens(text))
    raw = " ".join(toks[:40]).encode()
    return hashlib.md5(raw).hexdigest()[:10]


def normalize_topic_key(
    topic_tag: str = "",
    question: str = "",
    weak_topic: str = "",
) -> str:
    """Canonical key for same-type / same-topic tracking."""
    raw = (topic_tag or weak_topic or "").strip().lower()
    if raw and raw not in ("未分类", "未知主题", "?", "unknown"):
        return raw
    return f"q:{question_content_fingerprint(question)}"


def questions_overlap(
    q1: str,
    q2: str,
    *,
    tag1: str = "",
    tag2: str = "",
    threshold: float = 0.6,
    same_tag_threshold: float = 0.35,
) -> bool:
    """Whether two questions target the same type (semantic / topic)."""
    t1 = _dup_tokens(q1)
    t2 = _dup_tokens(q2)
    if not t1 or not t2:
        return False
    j = len(t1 & t2) / len(t1 | t2)
    tg1 = (tag1 or "").strip().lower()
    tg2 = (tag2 or "").strip().lower()
    if tg1 and tg1 == tg2 and j >= same_tag_threshold:
        return True
    return j >= threshold


def update_reinforce_pool(
    pool: list[dict],
    scored: list[dict],
    topic_streaks: dict[str, int] | None = None,
    graduated_topics: set[str] | None = None,
    *,
    max_size: int = 20,
) -> tuple[list[dict], dict[str, int], set[str]]:
    """Keep wrong questions for re-test; graduate topics when semantically mastered."""
    streaks = dict(topic_streaks or {})
    graduated = set(graduated_topics or [])
    by_fp: dict[str, dict] = {
        question_content_fingerprint(item.get("question", "")): dict(item) for item in pool
    }

    def _pool_has_topic(tag: str) -> bool:
        return any(
            normalize_topic_key(
                p.get("topic_tag", ""),
                p.get("question", ""),
                p.get("weak_topic_focus", ""),
            )
            == tag
            for p in by_fp.values()
        )

    def _drop_topic(tag: str) -> None:
        drop_fps = [
            fp
            for fp, item in by_fp.items()
            if normalize_topic_key(
                item.get("topic_tag", ""),
                item.get("question", ""),
                item.get("weak_topic_focus", ""),
            )
            == tag
        ]
        for fp in drop_fps:
            by_fp.pop(fp, None)

    for qa in scored:
        tag = normalize_topic_key(
            qa.get("topic_tag", ""),
            qa.get("question", ""),
            qa.get("weak_topic_focus", ""),
        )

        if qa.get("is_correct"):
            streaks[tag] = streaks.get(tag, 0) + 1
            in_pool = _pool_has_topic(tag)
            should_graduate = (
                qa.get("is_reinforce")
                or in_pool
                or streaks[tag] >= 2
            )
            if should_graduate:
                graduated.add(tag)
                _drop_topic(tag)
                streaks[tag] = max(streaks[tag], 2)
            continue

        streaks[tag] = 0
        graduated.discard(tag)

        fp = question_content_fingerprint(qa.get("question", ""))
        by_fp[fp] = {
            "question": qa.get("question", ""),
            "evidence_refs": list(qa.get("evidence_refs") or []),
            "topic_tag": qa.get("topic_tag", ""),
            "weak_topic_focus": qa.get("weak_topic_focus", ""),
            "persona_id": qa.get("persona_id", "reinforce"),
            "persona_name": qa.get("persona_name", "巩固复测"),
            "is_reinforce": True,
        }

    ordered = list(by_fp.values())
    return ordered[-max_size:], streaks, graduated


def _question_fingerprint(text: str) -> str:
    """Alias for backward compatibility."""
    return question_content_fingerprint(text)


def build_chapter_study_context(
    *,
    raw_chunks: list[dict],
    chapter_registry: list[dict],
    current_chapter_index: int,
    study_material: str,
    long_term_notes: str,
    short_term_notes: str,
    max_chars: int,
) -> str:
    """Sliding window: long-term summaries + prior short-term notes + current chapter."""
    ch = current_chapter(chapter_registry, current_chapter_index)
    if not ch:
        return build_study_context(
            raw_chunks=raw_chunks,
            study_material=study_material,
            curriculum_level=0,
            pages_per_round=max(1, len(chapter_registry)),
            max_chars=max_chars,
        )

    current_chunks = chunks_for_chapter(raw_chunks, ch["chapter_id"])
    chunk_budget = max(max_chars * 2 // 3, 1000)
    from src.tools.web_fetch import material_context

    chunk_text = material_context(current_chunks, max_chars=chunk_budget)
    material_budget = max(max_chars - len(chunk_text) - 400, 400)
    material_excerpt = (study_material or "").strip()[:material_budget]

    lt_budget = min(800, max_chars // 5)
    st_budget = min(1200, max_chars // 4)
    lt = _truncate_sections(long_term_notes or "", lt_budget)
    st = _truncate_sections(short_term_notes or "", st_budget)

    parts = [
        f"【当前章节】{chapter_label(chapter_registry, current_chapter_index)}。"
        "请只学习本章内容，不要超前。",
    ]
    if lt:
        parts.append(f"## 长期记忆（已掌握章节摘要）\n{lt}")
    if st:
        parts.append(f"## 短期记忆（上轮本章笔记，请在此基础上增量完善）\n{st}")
    if material_excerpt:
        parts.append(f"## 本章整理资料\n{material_excerpt}")
    parts.append(f"## 本章原文\n{chunk_text}")

    text = "\n\n".join(parts)
    if len(text) > max_chars:
        return text[: max_chars - 20] + "\n\n…（已达学习上下文上限）"
    return text


def chapter_exam_accuracy(
    scored: list[dict],
    chapter_id: str,
    chunks: list[dict],
) -> float:
    """Weighted accuracy for questions whose evidence belongs to the chapter."""
    chunk_ids = {c["id"] for c in chunks if c.get("chapter_id") == chapter_id}
    if not chunk_ids:
        return weighted_accuracy(scored)
    relevant = [
        q
        for q in scored
        if chunk_ids.intersection(set(q.get("evidence_refs") or []))
    ]
    return weighted_accuracy(relevant) if relevant else 0.0


def maybe_advance_chapter(
    current_index: int,
    chapter_accuracy: float,
    registry: list[dict],
    *,
    threshold: float,
    already_mastered: bool,
) -> tuple[int, bool]:
    """Return (index, should_consolidate). Index advances after consolidate."""
    if already_mastered:
        return current_index, False
    if chapter_accuracy < threshold:
        return current_index, False
    if current_index >= len(registry):
        return current_index, False
    return current_index, True


def all_chapters_mastered(
    registry: list[dict],
    chapter_mastery: dict[str, dict],
) -> bool:
    if not registry:
        return False
    for ch in registry:
        cid = ch.get("chapter_id", "")
        rec = chapter_mastery.get(cid) or {}
        if not rec.get("mastered"):
            return False
    return True


def update_chapter_mastery_record(
    mastery: dict[str, dict],
    chapter_id: str,
    *,
    accuracy: float,
    macro_iter: int,
    weak_subtopics: list[str],
    threshold: float,
) -> dict[str, dict]:
    """Return updated mastery dict for one chapter."""
    updated = dict(mastery)
    rec = dict(updated.get(chapter_id) or {})
    rec["accuracy"] = accuracy
    rec["best_accuracy"] = max(float(rec.get("best_accuracy", 0.0)), accuracy)
    rec["attempts"] = int(rec.get("attempts", 0)) + 1
    rec["weak_subtopics"] = weak_subtopics[:6]
    if accuracy >= threshold and not rec.get("mastered"):
        rec["mastered"] = True
        rec["mastered_at_iter"] = macro_iter
    updated[chapter_id] = rec
    return updated


def mastery_progress_summary(
    registry: list[dict],
    chapter_mastery: dict[str, dict],
) -> list[dict]:
    """UI-friendly chapter progress list."""
    rows: list[dict] = []
    for i, ch in enumerate(registry):
        cid = ch.get("chapter_id", "")
        rec = chapter_mastery.get(cid) or {}
        rows.append(
            {
                "chapter_id": cid,
                "chapter_title": ch.get("chapter_title", ""),
                "chapter_index": i,
                "mastered": bool(rec.get("mastered")),
                "accuracy": float(rec.get("accuracy", 0.0)),
                "best_accuracy": float(rec.get("best_accuracy", 0.0)),
                "attempts": int(rec.get("attempts", 0)),
            }
        )
    return rows
