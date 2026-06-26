"""Unit tests for learning realism helpers."""
from src.tools.learning_policy import (
    apply_evidence_cap,
    curriculum_chunks,
    filter_content_chunks,
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
