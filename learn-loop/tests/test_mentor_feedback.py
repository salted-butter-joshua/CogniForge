"""Tests for mentor feedback formatting."""
from src.tools.learning_policy import format_mentor_feedback


def test_format_mentor_feedback_new_fields():
    obs = {
        "mentor_summary": "先停止抄笔记",
        "performance_diagnosis": "综合题弱",
        "habit_corrections": "不要堆术语",
        "methodology_advice": "用主动回忆",
        "study_plan": "先复习存储",
    }
    text = format_mentor_feedback(obs)
    assert "先停止抄笔记" in text
    assert "主动回忆" in text
    assert "存储" in text


def test_format_mentor_feedback_legacy_fallback():
    obs = {
        "improvement_suggestions": "多练错题",
        "learning_patterns": "爱猜",
    }
    text = format_mentor_feedback(obs)
    assert "多练错题" in text
