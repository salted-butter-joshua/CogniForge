"""Unit tests for learning realism helpers."""
from src.tools.learning_policy import (
    adjust_difficulty_level,
    apply_evidence_cap,
    build_study_context,
    curriculum_chunks,
    filter_content_chunks,
    maybe_advance_curriculum_level,
    weighted_accuracy,
)


def test_curriculum_unlocks_progressively():
    chunks = [
        {"id": f"c{i}", "url": f"http://x/p{i}", "content": "x" * 300}
        for i in range(30)
    ]
    r0 = curriculum_chunks(chunks, 0, pages_per_round=2)
    r1 = curriculum_chunks(chunks, 1, pages_per_round=2)
    assert len(r0) < len(r1)


def test_evidence_cap_penalizes_novel_terms():
    evidence = "kubernetes pod 是最小调度单元"
    answer = "pod 是调度单元，还涉及 cgroup v2 内存压缩与 ebpf 观测面"
    capped, reason = apply_evidence_cap(answer, evidence, 0.95, cap=0.78)
    assert capped <= 0.78
    assert reason


def test_weighted_accuracy_favors_hard_personas():
    scored = [
        {"persona_id": "P1", "is_correct": True},
        {"persona_id": "P5", "is_correct": False},
    ]
    w = weighted_accuracy(scored)
    assert w < 0.5


def test_filter_drops_thin_nav():
    chunks = [
        {"id": "nav", "content": "a\nb\nc\nd\ne\nf", "url": "u"},
        {"id": "ok", "content": "x" * 400, "url": "u2"},
    ]
    out = filter_content_chunks(chunks)
    assert any(c["id"] == "ok" for c in out)


def test_adjust_difficulty_holds_in_middle_band():
    assert adjust_difficulty_level(2, 0.75, advance_threshold=0.90, retreat_threshold=0.50) == 2


def test_adjust_difficulty_advances_on_high_accuracy():
    assert adjust_difficulty_level(1, 0.92, advance_threshold=0.90) == 2


def test_adjust_difficulty_retreats_on_low_accuracy():
    assert adjust_difficulty_level(2, 0.40, retreat_threshold=0.50) == 1


def test_curriculum_only_advances_when_accuracy_met():
    chunks = [{"id": f"c{i}", "url": f"http://x/p{i}", "content": "x" * 300} for i in range(10)]
    level, ok = maybe_advance_curriculum_level(0, 0.90, chunks, pages_per_round=2)
    assert ok is True
    assert level == 1
    level2, ok2 = maybe_advance_curriculum_level(0, 0.60, chunks, pages_per_round=2)
    assert ok2 is False
    assert level2 == 0


def test_build_study_context_uses_cumulative_window():
    chunks = [
        {"id": f"c{i}", "url": f"http://x/p{i}", "title": f"t{i}", "content": "y" * 200}
        for i in range(6)
    ]
    text = build_study_context(
        raw_chunks=chunks,
        study_material="## intro",
        curriculum_level=0,
        pages_per_round=2,
        max_chars=5000,
    )
    assert "课程范围" in text
    assert "c0" in text or "t0" in text
    assert "c4" not in text


def test_select_exam_notes_prefers_short_term():
    from src.tools.learning_policy import select_exam_notes

    short = "## 核心\n" + "pod 调度单元 " * 20
    long = "## 已学\n" + "summary " * 10
    out = select_exam_notes(
        notes="",
        max_chars=800,
        long_term_notes=long,
        short_term_notes=short,
        chapter_title="Pod",
    )
    assert "本章笔记" in out
    assert "Pod" in out


def test_build_chapter_registry_orders_unique():
    from src.tools.web_fetch import build_chapter_registry

    chunks = [
        {"chapter_id": "a", "chapter_title": "A", "chapter_order": 1},
        {"chapter_id": "b", "chapter_title": "B", "chapter_order": 0},
        {"chapter_id": "a", "chapter_title": "A", "chapter_order": 1},
    ]
    reg = build_chapter_registry(chunks)
    assert [r["chapter_id"] for r in reg] == ["b", "a"]


def test_chapter_exam_accuracy_filters_by_evidence():
    from src.tools.learning_policy import chapter_exam_accuracy

    chunks = [
        {"id": "c1", "chapter_id": "ch1"},
        {"id": "c2", "chapter_id": "ch2"},
    ]
    scored = [
        {"persona_id": "P1", "is_correct": True, "evidence_refs": ["c1"]},
        {"persona_id": "P1", "is_correct": False, "evidence_refs": ["c2"]},
    ]
    acc = chapter_exam_accuracy(scored, "ch1", chunks)
    assert acc == 1.0


def test_all_chapters_mastered():
    from src.tools.learning_policy import all_chapters_mastered

    registry = [{"chapter_id": "a"}, {"chapter_id": "b"}]
    mastery = {
        "a": {"mastered": True},
        "b": {"mastered": False},
    }
    assert not all_chapters_mastered(registry, mastery)
    mastery["b"]["mastered"] = True
    assert all_chapters_mastered(registry, mastery)
