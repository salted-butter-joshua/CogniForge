"""Tests for learning reinforcement and memory layers."""

from src.tools.learning_policy import (
    append_chapter_archive,
    build_learning_journal,
    exam_notes_char_budget,
    extract_core_memory_layer,
    extract_working_exam_layer,
    format_wrong_qa_feedback,
    normalize_topic_key,
    question_content_fingerprint,
    select_exam_notes,
    sync_chapter_long_term_notes,
    update_reinforce_pool,
)

SAMPLE_NOTES = """
## 知识框架
- Pod 是最小调度单元
- Service 提供服务发现

## 核心概念与要点
Pod 是一组容器的集合，共享网络与存储……（很长）

## 薄弱点强化梳理
- 容易混淆 Pod 与 Deployment

## 自测要点
1. Pod 和容器的区别？
2. Etcd 的作用？

## 待澄清 / 易混淆点
- ReplicaSet 与 Deployment 关系
"""


def test_extract_working_exam_layer_picks_study_sections():
    layer = extract_working_exam_layer(SAMPLE_NOTES, max_chars=2000)
    assert "自测" in layer or "薄弱" in layer or "易混淆" in layer
    assert len(layer) > 0


def test_extract_core_memory_layer_for_exam_long_term():
    core = extract_core_memory_layer(SAMPLE_NOTES, max_chars=2000)
    assert "Pod" in core or "Service" in core or "知识框架" in core
    assert "薄弱点" not in core


def test_sync_chapter_long_term_after_study():
    short = SAMPLE_NOTES
    lt = sync_chapter_long_term_notes(
        "",
        short,
        "概述",
        per_chapter_max_chars=2000,
        total_max_chars=6000,
    )
    assert "## 概述" in lt
    assert "Pod" in lt
    lt2 = sync_chapter_long_term_notes(
        lt,
        short + "\n\n## 核心概念与要点\n- 新增：Deployment 管理副本",
        "概述",
        per_chapter_max_chars=2000,
        total_max_chars=6000,
    )
    assert lt2.count("## 概述") == 1
    assert "Deployment" in lt2


def test_apply_evidence_cap_skipped_when_semantic_lenient():
    from src.tools.learning_policy import apply_evidence_cap

    score, reason = apply_evidence_cap(
        "这是完全换词但语义正确的长篇回答" * 5,
        "evidence 只有很少术语",
        0.95,
        semantic_lenient=True,
    )
    assert score == 0.95
    assert reason == ""


def test_select_exam_notes_uses_layers_not_full_working_notes():
    import os

    from src.config import get_settings

    os.environ["EXAM_MEMORY_MODE"] = "layered"
    get_settings.cache_clear()
    bundle = select_exam_notes(
        max_chars=2000,
        long_term_notes="## 已掌握\n- Etcd 是分布式 KV",
        short_term_notes=SAMPLE_NOTES,
        chapter_title="概述",
    )
    assert "长期记忆" in bundle
    assert "参考层" in bundle or "核心概念" in bundle
    assert "闭卷记忆规则" in bundle
    get_settings.cache_clear()


def test_format_wrong_qa_feedback():
    qa = [
        {"question": "什么是 Pod?", "answer": "不知道", "is_correct": False, "topic_tag": "Pod", "judge_reason": "未作答"},
        {"question": "什么是 Service?", "answer": "负载均衡", "is_correct": True, "topic_tag": "Service"},
    ]
    text = format_wrong_qa_feedback(qa)
    assert "Pod" in text
    assert "Service" not in text


def test_update_reinforce_pool_adds_wrong_and_drops_correct_retry():
    pool = []
    streaks: dict[str, int] = {}
    graduated: set[str] = set()
    scored_wrong = [
        {
            "question": "Etcd 的作用是什么？",
            "answer": "不知道",
            "is_correct": False,
            "evidence_refs": ["c1"],
            "topic_tag": "etcd",
            "persona_id": "p1",
            "persona_name": "考官",
        }
    ]
    pool, streaks, graduated = update_reinforce_pool(pool, scored_wrong, streaks, graduated)
    assert len(pool) == 1

    scored_retry_ok = [
        {
            **scored_wrong[0],
            "answer": "分布式键值存储",
            "is_correct": True,
            "is_reinforce": True,
        }
    ]
    pool, streaks, graduated = update_reinforce_pool(
        pool, scored_retry_ok, streaks, graduated
    )
    assert len(pool) == 0
    assert "etcd" in graduated


def test_topic_graduation_same_tag_different_wording():
    """Same topic_tag + correct reinforce should graduate the topic, not only exact fingerprint."""
    pool = [
        {
            "question": "Etcd 的作用是什么？",
            "topic_tag": "etcd",
            "is_reinforce": True,
            "evidence_refs": ["c1"],
        }
    ]
    streaks: dict[str, int] = {}
    graduated: set[str] = set()
    scored = [
        {
            "question": "请说明 ETCD 在集群中的职责",  # different wording, same topic
            "answer": "分布式键值存储，保存集群状态",
            "is_correct": True,
            "is_reinforce": True,
            "topic_tag": "etcd",
            "evidence_refs": ["c1"],
        }
    ]
    pool, streaks, graduated = update_reinforce_pool(pool, scored, streaks, graduated)
    assert len(pool) == 0
    assert "etcd" in graduated


def test_question_fingerprint_case_insensitive_ascii():
    a = question_content_fingerprint("What is etcd?")
    b = question_content_fingerprint("What is ETCD?")
    assert a == b


def test_exam_notes_char_budget_is_closed_book_total():
    import os
    from src.config import get_settings

    os.environ["STUDENT_NOTES_MAX_CHARS"] = "3000"
    os.environ["SHORT_TERM_NOTES_MAX_CHARS"] = "8000"
    get_settings.cache_clear()
    assert exam_notes_char_budget() == 3000
    get_settings.cache_clear()


def test_chapter_archive_and_journal():
    ch = {"chapter_id": "a1", "chapter_title": "概述", "part_title": "Part I", "chapter_order": 1}
    archive = append_chapter_archive([], ch, SAMPLE_NOTES, macro_iter=2)
    assert len(archive) == 1
    journal = build_learning_journal(archive, goal="学 K8s")
    assert "学习全过程笔记" in journal
    assert "知识框架" in journal
    assert "考试时可按参数选择" in journal


def test_chunks_for_exam_chapter_mode_no_review():
    from src.tools.learning_policy import chunks_for_chapter, chunks_for_exam, init_chapter_mastery_dict

    chunks = [
        {"id": "c1", "chapter_id": "ch1", "content": "a"},
        {"id": "c2", "chapter_id": "ch2", "content": "b"},
    ]
    registry = [
        {"chapter_id": "ch1", "chapter_title": "A"},
        {"chapter_id": "ch2", "chapter_title": "B"},
    ]
    mastery = init_chapter_mastery_dict(registry)
    mastery["ch2"]["mastered"] = True
    exam_chunks = chunks_for_exam(
        chunks, registry, 0, mastery, review_ratio=0.5, chapter_mastery_mode=True
    )
    assert {c["id"] for c in exam_chunks} == {c["id"] for c in chunks_for_chapter(chunks, "ch1")}


def test_study_aligned_chunk_ids():
    from src.tools.learning_policy import study_aligned_chunk_ids

    chunks = [
        {"id": "c1", "chapter_id": "ch1", "heading": "Etcd 解析", "content": "etcd 是分布式 kv"},
        {"id": "c2", "chapter_id": "ch1", "heading": "其他", "content": "unrelated topic xyz"},
    ]
    ids = study_aligned_chunk_ids(
        chunks,
        "ch1",
        study_material="",
        short_term_notes="## Etcd 解析\netcd 存储集群状态",
    )
    assert "c1" in ids
    assert "c2" not in ids


def test_reinforce_pool_cap_early_rounds():
    from src.tools.learning_policy import reinforce_pool_cap

    early = reinforce_pool_cap(20, macro_iter=0, chapter_attempts=1, ratio=0.5)
    late = reinforce_pool_cap(20, macro_iter=5, chapter_attempts=6, ratio=0.5)
    assert early >= late


def test_compute_study_notes_budget():
    from src.config import get_settings
    from src.tools.learning_policy import compute_study_notes_budget

    import os

    os.environ["STUDY_NOTES_TARGET_RATIO"] = "1.75"
    os.environ["SHORT_TERM_NOTES_MAX_CHARS"] = "6000"
    get_settings.cache_clear()
    notes_max, target = compute_study_notes_budget(8000)
    assert target == 14000
    assert notes_max >= 14000
    notes_max2, target2 = compute_study_notes_budget(8000, prior_chars=15000)
    assert target2 >= 15000
    assert notes_max2 >= 15000
    get_settings.cache_clear()


def test_guard_incremental_notes_keeps_prior_on_shrink():
    from src.tools.learning_policy import guard_incremental_notes

    prior = "## 知识框架\n" + ("内容段落。" * 200)
    shrunk = "## 知识框架\n简短摘要"
    out = guard_incremental_notes(prior, shrunk, notes_max_chars=50000)
    assert prior in out or out.startswith("## 知识框架")
    assert len(out) >= len(prior) * 0.9


def test_effective_study_notes_ratio_clamps():
    from src.config import get_settings
    from src.tools.learning_policy import effective_study_notes_ratio

    import os

    os.environ["STUDY_NOTES_TARGET_RATIO"] = "3.0"
    get_settings.cache_clear()
    assert effective_study_notes_ratio() == 2.0
    os.environ["STUDY_NOTES_TARGET_RATIO"] = "1.2"
    get_settings.cache_clear()
    assert effective_study_notes_ratio() == 1.5
    get_settings.cache_clear()
