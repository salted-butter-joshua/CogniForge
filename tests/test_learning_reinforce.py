"""Tests for learning reinforcement and memory layers."""

from src.tools.learning_policy import (
    append_chapter_archive,
    build_learning_journal,
    exam_notes_char_budget,
    extract_working_exam_layer,
    format_wrong_qa_feedback,
    select_exam_notes,
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


def test_extract_working_exam_layer_excludes_framework():
    layer = extract_working_exam_layer(SAMPLE_NOTES, max_chars=2000)
    assert "自测" in layer or "薄弱" in layer or "待澄清" in layer
    assert "Pod 是一组容器的集合" not in layer


def test_select_exam_notes_uses_layers_not_full_working_notes():
    bundle = select_exam_notes(
        max_chars=2000,
        long_term_notes="## 已掌握\n- Etcd 是分布式 KV",
        short_term_notes=SAMPLE_NOTES,
        chapter_title="概述",
    )
    assert "长期记忆" in bundle
    assert "参考层" in bundle
    assert "Pod 是一组容器的集合" not in bundle


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
    pool = update_reinforce_pool(pool, scored_wrong)
    assert len(pool) == 1

    scored_retry_ok = [
        {
            **scored_wrong[0],
            "answer": "分布式键值存储",
            "is_correct": True,
            "is_reinforce": True,
        }
    ]
    pool = update_reinforce_pool(pool, scored_retry_ok)
    assert len(pool) == 0


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
    assert "闭卷考试时仅使用" in journal
